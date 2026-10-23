"""데이터 파일·메타데이터·필수 첨부·중복 청크의 검수 보고서."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from .common import file_sha256
from .common import read_json, read_csv, read_jsonl, write_jsonl, write_json, TEXT_READY

from .convert_documents import validate_text_quality


def load_jsonl(path):
    return read_jsonl(path, skip_blank=True)


def clean_chunks(pages, chunks):
    """같은 공고 안의 충분히 긴 동일 페이지만 병합. 모든 대체 출처는 보존."""
    groups = defaultdict(list)
    for page in pages:
        text = re.sub(r"\s+", "", page["text"])
        key = (page["bid_no"], page["bid_order"], text) if len(text) >= 150 else (page["document_id"], page["page"])
        groups[key].append(page)
    canonical, aliases, duplicates = set(), {}, []
    for group in groups.values():
        group.sort(key=lambda p: (p.get("requires_layout_review", False), p["file_name"], p["page"]))
        chosen = group[0]
        key = (chosen["document_id"], chosen["page"])
        canonical.add(key)
        sources = [{k: p.get(k, "") for k in ("file_name", "page", "source_url", "document_id")} for p in group]
        aliases[key] = sources
        if len(group)>1:
            duplicates.append({"kept": sources[0], "equivalent_sources": sources[1:], "bid_no": chosen["bid_no"]})
    result = []
    for chunk in chunks:
        key = (chunk["document_id"], chunk["page"])
        if key in canonical:
            result.append({**chunk, "equivalent_sources": aliases[key]})
    return result, duplicates


def audit(run_dir):
    """자료 개수·필수 첨부·해시·출처·청크만 검증한다."""
    root = Path(run_dir).resolve()
    rows = read_csv(root / "bids.csv")
    pages = load_jsonl(root / "processed/pages.jsonl")
    documents = load_jsonl(root / "processed/documents.jsonl")
    original_chunks = load_jsonl(root / "processed/chunks.jsonl")
    page_reviews = read_json(root/"page_reviews.json") if (root/"page_reviews.json").exists() else []
    reviewed_pages = {(r["document_id"],r["page"]):r for r in page_reviews}
    items = read_json(root / "candidates.json")["items"]
    latest = {}
    for item in items:
        no = str(item["bidNtceNo"])
        if no not in latest or int(item.get("bidNtceOrd") or 0)>int(latest[no].get("bidNtceOrd") or 0):
            latest[no] = item
    failures, warnings, coverage = [], [], []
    keys = {(r["bid_no"],r["bid_order"]) for r in rows}
    if len(keys)!=len(rows):
        failures.append({"issue":"공고번호·차수 중복"})
    for row in rows:
        last = latest.get(row["bid_no"],{})
        if not last or str(last.get("bidNtceOrd") or "000")!=row["bid_order"] or any(w in str(last.get("ntceKindNm", "")) for w in ("취소","철회")):
            failures.append({"bid_no":row["bid_no"],"issue":"이전 차수 또는 취소/철회"})
        own = [d for d in documents if (d["bid_no"],d["bid_order"])==(row["bid_no"],row["bid_order"])]
        notice = [d for d in own if "공고" in d["file_name"] and d["chunk_count"]]
        requirements = [d for d in own if any(w in d["file_name"] for w in ("제안요청","과업지시","과업내용")) and d["chunk_count"]]
        complete = bool(notice and requirements)
        coverage.append({"bid_no":row["bid_no"],"notice_files":len(notice),"requirements_files":len(requirements),"complete":complete})
        if not complete:
            failures.append({"bid_no":row["bid_no"],"issue":"공고문 또는 제안요청서/과업지시서 없음"})
    for doc in documents:
        path = Path(doc["local_path"])
        if not path.is_file() or file_sha256(path)!=doc["sha256"]:
            failures.append({"document_id":doc["document_id"],"issue":"PDF 파일/해시 불일치"})
        if doc["status"] not in TEXT_READY:
            failures.append({"document_id":doc["document_id"],"issue":doc["status"]})
        if doc.get("requires_layout_review"):
            warnings.append({"document_id":doc["document_id"],"issue":"변환 레이아웃 원문 대조 필요"})
        for number in doc.get("empty_pages",[]):
            reviewed = reviewed_pages.get((doc["document_id"],number),{})
            if reviewed.get("sha256")!=doc["sha256"] or reviewed.get("classification") not in ("blank","decorative_border"):
                warnings.append({"document_id":doc["document_id"],"issue":"이미지 부록 원문 열람 필요" if reviewed.get("classification")=="scanned_appendix" else "빈 텍스트 페이지 확인 필요","pages":[number]})
        try:
            validate_text_quality([p["text"] for p in pages if p["document_id"]==doc["document_id"]])
        except RuntimeError:
            failures.append({"document_id":doc["document_id"],"issue":"한글 반복 손상 의심"})
    by_page = {(p["document_id"],p["page"]):p for p in pages}
    for chunk in original_chunks:
        p = by_page.get((chunk["document_id"],chunk["page"]))
        if not p or chunk["text"]!=p["text"][chunk["char_start"]:chunk["char_end"]]:
            failures.append({"chunk_id":chunk["chunk_id"],"issue":"청크/페이지 불일치"})
        if not all(chunk.get(k) for k in ("bid_no","bid_order","file_name","page","source_url","collected_at")):
            failures.append({"chunk_id":chunk["chunk_id"],"issue":"출처 메타데이터 누락"})
    chunks, duplicates = clean_chunks(pages,original_chunks)
    write_jsonl(root/"processed/chunks.jsonl",chunks)
    summary_path = root/"processed/summary.json"
    prepared = read_json(summary_path)
    prepared.update(raw_chunks=sum(d["chunk_count"] for d in documents),chunks=len(chunks),duplicate_page_groups=len(duplicates))
    write_json(summary_path, prepared)
    report = dict(scope="data_pipeline_only",bids=len(rows),documents=len(documents),pages=len(pages),chunks=len(chunks),
                  months=dict(Counter(r["published_at"][:7] for r in rows)),document_coverage=coverage,
                  page_reviews=dict(Counter(r["classification"] for r in page_reviews)),duplicate_pages=duplicates,
                  hard_failures=failures,review_items=warnings)
    write_json(root / "validation.json", report)
    lines=["# 데이터 파이프라인 검수 결과","",f"공고 {len(rows)}건 / 첨부 {len(documents)}개 / {len(pages)}페이지 / {len(chunks)}청크","",
           f"- 필수 첨부 확보: {sum(c['complete'] for c in coverage)}/{len(rows)}건",
           f"- 자동 검사 실패: {len(failures)}건",
           f"- 빈 텍스트 페이지 시각 검수: {report['page_reviews']}",
           "- 변환 레이아웃 원문 대조와 이미지 부록 열람은 별도 확인 대상으로 기록합니다.","",
           "| 공고번호 | 필수 첨부 확보 |","|---|---|"]
    lines.extend(f"| {c['bid_no']} | {'완료' if c['complete'] else '보완 필요'} |" for c in coverage)
    (root/"VALIDATION.md").write_text("\n".join(lines)+"\n")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir",type=Path,required=True)
    args=parser.parse_args()
    report=audit(args.run_dir)
    print(json.dumps({k:report[k] for k in ("bids","documents","pages","chunks","hard_failures")},ensure_ascii=False,indent=2))
    return 2 if report["hard_failures"] else 0


if __name__=="__main__":
    raise SystemExit(main())
