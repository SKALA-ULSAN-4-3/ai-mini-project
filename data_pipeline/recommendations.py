"""PDF 출처·임베딩을 수정하지 않은 bid_logic 추천 함수에 전달한다."""
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from .common import read_json, write_json, stamp, read_jsonl, TEXT_READY

from .bid_workflow import locked
from .knowledge import Embedder, KnowledgeStore
from .prepare_documents import extract_deadlines, region_requirement

ROOT = Path(__file__).resolve().parents[1]


class ProfileError(ValueError):
    pass


@lru_cache(maxsize=1)
def logic():
    # 기존 RAG 서버를 import하거나 bid_logic 코드를 변경하지 않는다.
    path = ROOT / "rag-code-template_ext/bid_logic/__init__.py"
    if not path.is_file():
        raise RuntimeError("feat/bid-logic의 bid_logic 패키지가 필요합니다.")
    name = "_pipeline_bid_logic"
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def company_profile(profile):
    if not isinstance(profile, dict):
        raise ProfileError("기업정보는 JSON 객체여야 합니다.")
    result = dict(profile)
    keywords = profile.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    fields = profile.get("business_fields") or []
    if not isinstance(keywords, list) or not isinstance(fields, list) or any(
            not isinstance(v, str) or not v.strip() for v in keywords + fields):
        raise ProfileError("keywords와 business_fields는 문자열 또는 문자열 목록을 확인하세요.")
    result["keywords"] = list(dict.fromkeys(keywords + fields))
    records = profile.get("track_records") or []
    if not isinstance(records, list) or any(not isinstance(r, dict) or
            not isinstance(r.get("summary", ""), str) for r in records):
        raise ProfileError("track_records는 summary 문자열을 포함한 객체 목록이어야 합니다.")
    result["track_records"] = records
    if not result["keywords"] and not any(r.get("summary", "").strip() for r in records):
        raise ProfileError("사업분야·관심 키워드·과거 실적 요약 중 하나를 입력하세요.")
    return result


def validate_company_profile(profile, start, end):
    profile = company_profile(profile)
    try:
        logic().recommend_bids([], profile, str(start), str(end))
    except ValueError as exc:
        raise ProfileError(str(exc)) from None
    return profile


def input_version(listing):
    return hashlib.sha256(json.dumps(sorted((b["bid_id"], b["evaluation_input_id"])
        for b in listing["items"]), ensure_ascii=False).encode()).hexdigest()


def _source(page, quote=None):
    return {"bid_no": page["bid_no"], "revision": page["bid_order"],
            "filename": page["file_name"], "page": page["page"],
            "url": page["source_url"], "collected_at": page.get("collected_at"),
            **({"quote": quote} if quote else {})}


def _summary_excerpt(pages, labels, limit=500):
    """공고문에 있는 문구만 발췌한다. 없는 사업 내용이나 기간은 만들지 않는다."""
    patterns = [re.compile(r"\s*".join(re.escape(char) for char in label), re.IGNORECASE) for label in labels]
    for pattern in patterns:
        for page in pages:
            text = page["text"]
            match = pattern.search(text)
            if not match:
                continue
            start = text.rfind("\n", 0, match.start()) + 1
            # 표의 항목명과 다음 행까지 보여 주되 새 절이나 참가자격으로 넘어가지 않는다.
            excerpt = text[start:match.end() + limit].splitlines()
            selected = []
            for line in excerpt:
                compact = re.sub(r"\s+", "", line)
                if selected and any(word in compact for word in (
                        "입찰참가자격", "참가자격", "입찰보증금", "제출서류", "계약방법")):
                    break
                selected.append(line)
                if len(selected) >= 4:
                    break
            quote = "\n".join(selected).strip()[:limit]
            if quote:
                return {"text": quote, "sources": [_source(page, quote)]}
    return {"text": None, "sources": []}


def _business_summary(pages):
    fields = {
        "overview": _summary_excerpt(pages, ("사업개요", "과업개요", "용역개요", "입찰건명", "사업명", "용역명")),
        "scope": _summary_excerpt(pages, ("주요과업", "과업내용", "사업내용", "용역내용", "과업범위", "사업목적")),
        "period": _summary_excerpt(pages, ("사업기간", "용역기간", "과업기간", "계약기간", "수행기간"), limit=300),
    }
    fallback = False
    if not fields["overview"]["text"]:
        first = next((p for p in pages if p["text"].strip()), None)
        if first:
            quote = first["text"].strip()[:500]
            fields["overview"] = {"text": quote, "sources": [_source(first, quote)]}
            fallback = True
    return {"summary": fields["overview"]["text"], "summary_sources": fields["overview"]["sources"],
            "project_summary": fields, "summary_method": "notice_extractive_v1",
            "summary_is_notice_preview": fallback,
            "summary_missing_fields": [key for key, value in fields.items() if value["text"] is None]}


def _bid(request):
    notice, pages = request["notice"], request["notice_pages"]
    region = region_requirement(pages)
    regions = None
    if region["status"] == "explicit_none":
        regions = []
    elif region["status"] == "restricted" and not region.get("complex"):
        # 복잡한 공동수급·시군구 조건을 시도 OR로 단순화하지 않는다.
        regions = region["regions"]
    schedules = extract_deadlines(pages)
    closing = [r for r in schedules if r["kind"] in ("bid", "proposal")]
    deadline_source = min(closing, key=lambda r: r["deadline"]) if closing else None
    deadline = deadline_source["deadline"] if deadline_source else None
    deadline = deadline or notice.get("deadline") or None
    budget = notice.get("allocated_budget") or notice.get("estimated_price") or None
    return {"bid_no": notice["bid_no"], "revision": notice["bid_order"],
            "title": notice["title"], "agency": notice["agency"],
            "published_at": notice["published_at"][:10], "deadline": deadline,
            "budget": str(budget).replace(",", "") if budget is not None else None,
            "regions": regions, "industries": None, "licenses": None,
            "company_sizes": None, "certs": None,
            "filename": request["notice_document"]["file_name"], "url": notice["detail_url"],
            "sources": [_source(p) for p in pages if p["text"].strip()],
            "restriction_evidence": {"regions": region, "deadline": deadline_source},
            "budget_source": "OpenAPI.asignBdgtAmt" if notice.get("allocated_budget") else "OpenAPI.presmptPrce"}


def recommend_run(run_dir, limit=20, now=None):
    """평가용 공고문만 임베딩한다. 원본 평가 알고리즘·필터·순위를 재구현하지 않는다."""
    with locked(run_dir) as root:
        listing = read_json(root / "bid_list.json")
        saved = read_json(root / "candidates.json")
        period = saved["request"]
        profile = validate_company_profile(read_json(root / "company_profile.json"),
                                           period["start"], period["end"])
        requests = read_jsonl(root / "evaluation_inputs.jsonl")
        requests = [r for r in requests if r["notice_document"]["status"] in TEXT_READY]
        bids = [_bid(r) for r in requests]
        records = read_jsonl(root / "processed/chunks.jsonl") if (root / "processed/chunks.jsonl").exists() else []
        allowed = {(b["bid_no"], b["revision"]) for b in bids}
        records = [{**r, "group_id": f"{r['bid_no']}_{r['bid_order']}:{r['source_url']}"}
                   for r in records if (r["bid_no"], r["bid_order"]) in allowed]
        store = KnowledgeStore(root=root / "recommendation_index")
        if records:
            store.upsert(records, replace_all=True)

        def search(query, keys):
            if not records or not keys:
                return []
            index, chunks, manifest = store.load()
            vector = Embedder(manifest["embedding_model"]).embed([query])
            similarities, positions = index.search(vector, len(chunks))
            # 파이프라인은 정규화 IP, bid_logic은 제곱 L2 거리 계약이다.
            hits = []
            for similarity, position in zip(similarities[0], positions[0]):
                chunk = chunks[int(position)]
                key = (chunk["bid_no"], chunk["bid_order"])
                if key in keys:
                    hits.append({"bid_no": key[0], "revision": key[1],
                                 "distance": max(0.0, min(4.0, 2.0 - 2.0 * float(similarity)))})
            return hits

        result = logic().recommend_bids(bids, profile, period["start"], period["end"],
                                         now=now, search=search, limit=limit)
        for bid in result["bids"]:
            bid["bid_id"] = f"{bid['bid_no']}_{bid['revision']}"
            request = next(r for r in requests if r["bid_id"] == bid["bid_id"])
            bid.update(_business_summary(request["notice_pages"]))
        ready = {r["bid_id"] for r in requests}
        result.update(schema_version="bid-recommendations.v1", evaluator="feat/bid-logic",
                      input_version=input_version(listing), evaluated_at=stamp(),
                      recommended_bid_ids=[r["bid_id"] for r in result["bids"]],
                      documents_unavailable=[b["bid_id"] for b in listing["items"] if b["bid_id"] not in ready],
                      embedding_model=store.model, evaluation_kind="eligibility_filter_and_pdf_similarity",
                      score_evaluation="not_performed_no_scoring_table", needs_review=True,
                      next_action="user_select_1_or_2_bids", selection_requires_evaluation=False)
        write_json(root / "recommendations.json", result)
        return result


def read_recommendations(run_dir):
    root = Path(run_dir)
    path = root / "recommendations.json"
    if not path.exists():
        return None
    result = read_json(path)
    listing = read_json(root / "bid_list.json")
    if result["input_version"] != input_version(listing):
        return None
    # 이미 저장된 추천도 재다운로드·재임베딩 없이 표시용 사업 요약만 보완한다.
    if any("project_summary" not in bid for bid in result["bids"]):
        path = root / "evaluation_inputs.jsonl"
        requests = {r["bid_id"]: r for r in read_jsonl(path)} if path.exists() else {}
        for bid in result["bids"]:
            request = requests.get(bid["bid_id"])
            if request:
                bid.update(_business_summary(request["notice_pages"]))
    result.update(next_action="user_select_1_or_2_bids", selection_requires_evaluation=False)
    return result
