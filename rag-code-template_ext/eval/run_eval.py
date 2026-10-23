"""평가셋으로 /rag-query를 채점한다 (교재 Day3: 정확성 · 근거성 · 환각).

사용 예:
  python eval/run_eval.py --label "chunk500_top5"            # RAG 서버(:8001)에 질의하고 채점
  python eval/run_eval.py --baseline-only                     # LLM 호출 없이 키워드 검색 베이스라인만
  python eval/run_eval.py --token "$TOKEN" --label "jwt"      # JWT가 붙은 뒤

결과: eval/results/<시각>_<label>.csv (질문별) + 화면에 요약.
같은 평가셋으로 개선 전후를 비교하려면 --label만 바꿔 다시 실행한다.
"""
import argparse
import csv
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BASE_DIR = EVAL_DIR.parent


def norm(s: str) -> str:
    # macOS 파일명(NFD)과 비교하기 위해 NFC로 맞추고, 공백 · 괄호 · 점 차이는 무시
    return re.sub(r"[\s()·]", "", unicodedata.normalize("NFC", s or ""))


def contains_all(text: str, groups: list[str]) -> bool:
    t = norm(text)
    return all(any(norm(alt) in t for alt in g.split("|")) for g in groups)


def source_hit(sources: list[str], expected: list[str], documents: dict[str, str]) -> bool:
    # expected 예: "공고문 p.1" → documents["공고문"] 파일의 1쪽이 sources에 있으면 통과
    got = {unicodedata.normalize("NFC", s) for s in sources}
    for e in expected:
        doc, page = e.rsplit(" ", 1)
        if f"{unicodedata.normalize('NFC', documents[doc])} {page}" in got:
            return True
    return False


def ask(url: str, question: str, bid_no: str, token: str | None, top_k: int) -> dict:
    body = json.dumps({"prompt": question, "source": "pdf", "top_k": top_k, "bid_no": bid_no}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{url}/rag-query", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"response": f"HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}", "sources": [],
                "handoff": None, "needs_review": None, "latency_ms": 0}


def keyword_baseline(question: str, chunks: list[str]) -> str:
    # 기존 방식(키워드 검색)의 대리 지표: 질문 단어가 가장 많이 겹치는 조각 1개
    words = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", question)]
    return max(chunks, key=lambda c: sum(w in c for w in words)) if chunks else ""


def load_chunks(bid_no: str) -> list[str]:
    try:
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
        store = FAISS.load_local(str(BASE_DIR / "faiss_db/pdf"), OpenAIEmbeddings(), allow_dangerous_deserialization=True)
        return [d.page_content for d in store.docstore._dict.values() if d.metadata.get("bid_no") == bid_no]
    except Exception as e:  # 베이스라인은 보조 지표이므로 실패해도 평가는 진행
        print(f"[경고] 베이스라인용 조각을 읽지 못했습니다: {e}", file=sys.stderr)
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=str(EVAL_DIR / "eval_set_2026-01.json"))
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--token", default=None)
    ap.add_argument("--label", default="run")
    ap.add_argument("--top-k", type=int, default=10, help="검색할 조각 수 (서버 기본값 10, 최소값 5)")
    ap.add_argument("--baseline-only", action="store_true")
    args = ap.parse_args()

    spec = json.loads(Path(args.set).read_text(encoding="utf-8"))
    bid_no, documents = spec["bid_no"], spec["documents"]
    chunks = load_chunks(bid_no)

    rows = []
    for q in spec["questions"]:
        exception = q["expect_handoff"] is True
        base_text = keyword_baseline(q["question"], chunks)
        base_ok = (not exception) and bool(q["must_include"]) and contains_all(base_text, q["must_include"])

        if args.baseline_only:
            res = {"response": "", "sources": [], "handoff": None, "needs_review": None, "latency_ms": 0}
        else:
            res = ask(args.url, q["question"], bid_no, args.token, args.top_k)

        answer, sources = res.get("response", ""), res.get("sources", [])
        if exception:
            correct = res.get("handoff") is True              # 모르는 것은 모른다고 넘겨야 정답
            grounded = None
            hallucination = res.get("handoff") is False        # 문서에 없는데 답을 만들어 냄
        else:
            correct = contains_all(answer, q["must_include"])
            grounded = source_hit(sources, q["sources"], documents)
            hallucination = None                                # 답이 있는 질문의 환각은 사람이 판정
        review_ok = None if q["expect_needs_review"] is None else res.get("needs_review") == q["expect_needs_review"]

        rows.append({
            "id": q["id"], "category": q["category"], "question": q["question"],
            "expected": q["expected"], "answer": answer.replace("\n", " "),
            "sources": " ; ".join(unicodedata.normalize("NFC", s) for s in sources),
            "correct": correct, "grounded": grounded, "hallucination": hallucination,
            "handoff": res.get("handoff"), "needs_review": res.get("needs_review"), "review_flag_ok": review_ok,
            "baseline_correct": base_ok, "latency_ms": res.get("latency_ms", 0),
            "human_judgement": "",  # 사람이 최종 확인: O / X / 부분
        })
        if not args.baseline_only:
            mark = "O" if correct else "X"
            print(f"{q['id']} {mark} {q['question']}", flush=True)
            time.sleep(0.2)

    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{datetime.now():%Y%m%d-%H%M}_{args.label}.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:  # 엑셀에서 한글이 깨지지 않도록 BOM
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    answerable = [r for r in rows if not r["id"].startswith("E")]
    exceptions = [r for r in rows if r["id"].startswith("E")]
    print(f"\n=== {args.label} ({bid_no}) ===")
    print(f"키워드 검색 베이스라인: {sum(r['baseline_correct'] for r in answerable)}/{len(answerable)} (top-1 조각에 정답 포함)")
    if not args.baseline_only:
        lat = [r["latency_ms"] for r in rows if r["latency_ms"]]
        print(f"정확(답 있는 질문):     {sum(r['correct'] for r in answerable)}/{len(answerable)}")
        print(f"근거성(기대 쪽 인용):   {sum(bool(r['grounded']) for r in answerable)}/{len(answerable)}")
        print(f"예외 처리(handoff):     {sum(r['correct'] for r in exceptions)}/{len(exceptions)}")
        print(f"환각(예외에 답 생성):   {sum(bool(r['hallucination']) for r in exceptions)}/{len(exceptions)}")
        checked = [r for r in rows if r["review_flag_ok"] is not None]
        print(f"needs_review 표시:      {sum(r['review_flag_ok'] for r in checked)}/{len(checked)}")
        if lat:
            print(f"응답 시간: 평균 {sum(lat) / len(lat):.0f}ms, 최대 {max(lat)}ms")
        wrong = [r["id"] for r in rows if not r["correct"]]
        if wrong:
            print(f"틀린 문항: {', '.join(wrong)} → CSV의 answer 열과 원문을 대조하세요")
    print(f"결과 파일: {out}")


if __name__ == "__main__":
    main()
