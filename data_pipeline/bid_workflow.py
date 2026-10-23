"""목록 탐색 → 공고문 준비 → 외부 평가 연계 → 사용자 선택 시 전체 첨부 다운로드."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re

from . import g2b_client as collector
from . import convert_documents as converter
from .prepare_documents import prepare
from .common import (read_csv, read_json, read_jsonl, write_jsonl, write_json, stamp,
                     directory_lock, DOWNLOAD_SUCCESS, TEXT_READY, HWP_SUFFIXES)

SCHEMA_VERSION = "bid-evaluation-input.v1"


def locked(run_dir):
    return directory_lock(run_dir, ".workflow.lock")


def identity(item):
    return f"{item['bidNtceNo']}_{str(item.get('bidNtceOrd') or '000')}"


def latest_notices(items):
    latest = {}
    for item in sorted(items, key=lambda row: str(row.get("bidNtceOrd") or "000").zfill(8)):
        latest[str(item["bidNtceNo"])] = item
    return latest


def is_active_notice(item, latest):
    return latest[str(item["bidNtceNo"])] is item and not any(
        word in str(item.get("ntceKindNm", "")) for word in ("취소", "철회"))


def _attachment_cache(run_dir):
    return {(r["bid_no"], r["bid_order"], r["url"]): r
            for r in read_csv(run_dir / "attachments.csv")}


def validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError("기업 프로필은 JSON 객체여야 합니다.")
    for key in ("business_fields", "keywords"):
        values = profile.get(key, [])
        if key == "keywords" and isinstance(values, str):
            values = [values]
        if not isinstance(values, list) or any(
                not isinstance(v, str) or not v.strip() for v in values):
            raise ValueError(f"{key}는 비어 있지 않은 문자열 목록이어야 합니다.")
    for key in ("budget_min", "budget_max"):
        if profile.get(key) is not None:
            try:
                value = Decimal(str(profile[key]))
                if not value.is_finite() or value < 0:
                    raise InvalidOperation
            except InvalidOperation:
                raise ValueError(f"{key}는 0 이상의 금액이어야 합니다.") from None
    if profile.get("budget_min") is not None and profile.get("budget_max") is not None:
        if Decimal(str(profile["budget_min"])) > Decimal(str(profile["budget_max"])):
            raise ValueError("budget_min은 budget_max 이하여야 합니다.")
    return profile


def notice_attachment(item):
    """확실한 공고문만 한 개 고른다. 제안요청서·서식으로 임의 대체하지 않는다."""
    options = []
    for position, (name, url) in enumerate(collector.attachments(item), 1):
        compact = re.sub(r"\s+", "", name).lower()
        if any(word in compact for word in ("제안요청", "과업", "서식", "양식", "신청서", "사유", "규격", "주의", "협정")):
            continue
        suffix = Path(name).suffix.lower()
        is_standard = name == "standard_notice"
        is_notice = any(word in compact for word in ("공고문", "공고서", "입찰공고", "입찰안내서", "안내공고")) or bool(
            re.search(r"(?:^|[_\[(\-])공고(?:[)\]_\-]|$)", compact))
        if not is_standard and (suffix not in (".pdf", ".hwp", ".hwpx") or not is_notice):
            continue
        options.append((0 if suffix == ".pdf" else 2 if is_standard else 1, position, name, url))
    if not options:
        return None
    _, position, name, url = min(options)
    return position, name, url


def _download_record(run_dir, row, old):
    target = run_dir / "raw" / collector.safe_name(f"{row['bid_no']}_{row['bid_order']}") / row["storage_name"]
    cached_path = Path(old.get("local_path", "__missing__"))
    if (old.get("status") in DOWNLOAD_SUCCESS and old.get("url") == row["url"]
            and cached_path.resolve().parent == target.parent.resolve() and cached_path.is_file()
            and cached_path.stat().st_size):
        row.update(status="existing", local_path=str(cached_path.resolve()), error="")
        return
    try:
        collector.download_file(row["url"], target)
        # 별도 표준공고서 URL은 파일명 없이 제공될 수 있다. 실제 형식만 판별한다.
        if row["file_name"] == "standard_notice":
            with target.open("rb") as stream:
                signature = stream.read(8)
            suffix = ".pdf" if signature.startswith(b"%PDF-") else ".hwp" if signature.startswith(b"\xd0\xcf\x11\xe0") else ""
            if suffix:
                renamed = target.with_suffix(suffix)
                target.replace(renamed)
                target = renamed
        row.update(status="downloaded", local_path=str(target), error="")
    except collector.CollectionError as exc:
        row.update(status="failed", local_path="", error=str(exc))


def _manifest(run_dir, items, previous, scope, chosen=None):
    records = []
    selections_path = run_dir / "user_selections.json"
    selections = read_json(selections_path) if selections_path.exists() else {}
    latest = latest_notices(items)
    for item in items:
        bid_id = identity(item)
        active = is_active_notice(item, latest)
        notice = notice_attachment(item) if active else None
        for position, (name, url) in enumerate(collector.attachments(item), 1):
            key = (str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000"), url)
            old = previous.get(key, {})
            role = "notice" if notice and url == notice[2] else "supporting"
            selected = active and (role == "notice" or bid_id in selections or scope == "all" and bid_id == chosen)
            record = dict(bid_no=key[0], bid_order=key[1], file_name=name, url=url,
                          selected=selected, status="listed" if selected else "deferred",
                          local_path="", error="", role=role,
                          storage_name=f"{position:02}_{collector.safe_name(name)}")
            if old.get("status") in DOWNLOAD_SUCCESS and old.get("local_path"):
                record.update(status=old["status"], local_path=old["local_path"], error=old.get("error", ""))
            if not active:
                record["selected"] = False
                if not record["local_path"]:
                    record["status"] = "not_selected"
            records.append(record)
    return records, latest


def _save_records(run_dir, records):
    collector.write_csv(run_dir / "attachments.csv", collector.FILE_FIELDS + ["role", "storage_name"], records)


def _prepare_notices(run_dir, records, rhwp=None):
    # 전체 첨부를 받은 뒤에도 초기 판단 자료는 공고문만 사용한다.
    scoped = [{**r, "selected": r["role"] == "notice" and str(r["selected"]).lower() == "true"} for r in records]
    _save_records(run_dir, scoped)
    try:
        pending_hwp = [r for r in scoped if r["selected"] and r["status"] in DOWNLOAD_SUCCESS
                       and Path(r["local_path"]).suffix.lower() in HWP_SUFFIXES]
        conversion_error = None
        if pending_hwp:
            try:
                if rhwp:
                    converter.convert_rhwp(run_dir, rhwp)
                else:
                    converter.convert_run(run_dir)
            except (RuntimeError, OSError) as exc:
                conversion_error = type(exc).__name__
        result = prepare(run_dir)
        if conversion_error:
            result["conversion_error"] = conversion_error
        return result
    finally:
        _save_records(run_dir, records)


def _preliminary(pages, profile, bid):
    if not pages or not any(p["text"].strip() for p in pages):
        return {"status": "notice_review_required", "matched_terms": [], "evidence": [], "needs_review": True}
    keywords = profile.get("keywords", [])
    keywords = [keywords] if isinstance(keywords, str) else keywords
    terms = list(dict.fromkeys(profile.get("business_fields", []) + keywords))
    matches, evidence = [], []
    for term in terms:
        normalized = re.sub(r"\s+", "", term).casefold()
        for page in pages:
            if normalized in re.sub(r"\s+", "", page["text"]).casefold():
                matches.append(term)
                evidence.append({"term": term, "file_name": page["file_name"], "page": page["page"],
                                 "source_url": page["source_url"]})
                break
    if not terms:
        status = "profile_required"
    elif not matches:
        status = "no_text_match"
    else:
        status = "candidate"
    price = bid.get("estimated_price")
    if profile.get("budget_min") is not None or profile.get("budget_max") is not None:
        try:
            amount = Decimal(str(price).replace(",", ""))
            if not amount.is_finite():
                raise InvalidOperation
            if ((profile.get("budget_min") is not None and amount < Decimal(str(profile["budget_min"])))
                    or (profile.get("budget_max") is not None and amount > Decimal(str(profile["budget_max"])))):
                status = "budget_mismatch"
        except InvalidOperation:
            status = "budget_unknown"
    return {"status": status, "method": "notice_text_keyword_match_v1", "matched_terms": matches,
            "evidence": evidence, "needs_review": True,
            "note": "공고문 본문 기반 사전 분류이며 참가자격 확정 또는 점수 평가가 아님"}


def _evaluation_request(row, profile, profile_version, own_pages, own_docs):
    bid_id = f"{row['bid_no']}_{row['bid_order']}"
    preliminary = _preliminary(own_pages, profile, row)
    # 점수는 외부 담당자가 계산한다. 미평가를 0점으로 취급하지 않는다.
    version = hashlib.sha256(json.dumps({"profile": profile_version,
              "bid": {k: row[k] for k in ("bid_no", "bid_order", "title", "agency", "published_at", "deadline",
                                           "estimated_price", "allocated_budget", "detail_url")},
              "documents": sorted((d["sha256"], d["status"]) for d in own_docs)}, sort_keys=True).encode()).hexdigest()
    notice_doc = own_docs[0] if own_docs else None
    request = {"schema_version": SCHEMA_VERSION, "evaluation_input_id": version, "bid_id": bid_id,
               "company_profile": profile, "company_profile_version": profile_version,
               "notice": row, "notice_document": notice_doc, "notice_pages": own_pages,
               "preliminary": preliminary, "expected_result": {"score": "number", "max_score": "positive number",
                   "criteria": "external evaluator defined", "evaluator_version": "string"}}
    return request


def _stored_evaluation(old, request):
    if old.get("evaluation_input_id") == request["evaluation_input_id"] and old.get("evaluation"):
        return old["evaluation"]
    return {"status": "pending", "score": None, "max_score": None, "result": None}


def _public_bid(row, request, evaluation, related, selections):
    bid_id = request["bid_id"]
    notice_doc = request["notice_document"]
    return {**row, "bid_id": bid_id, "preliminary": request["preliminary"],
            "evaluation_input_id": request["evaluation_input_id"], "evaluation": evaluation,
            "notice_status": notice_doc["status"] if notice_doc else "notice_not_identified",
            "notice_document": notice_doc, "company_profile_version": request["company_profile_version"],
            "user_selected": bid_id in selections,
            "all_attachments_downloaded": bool(related) and all(
                r["status"] in DOWNLOAD_SUCCESS and bool(r["local_path"]) for r in related),
            "attachment_inventory_source": "OpenAPI attachment URLs 1-10 and standard notice URL",
            "attachments": [{k: r[k] for k in ("file_name", "url", "role", "status", "local_path")} for r in related],
            "attachment_scope": "all_requested" if bid_id in selections else "notice_only"}


def _notice_records(run_dir, records):
    pages_path = run_dir / "processed/pages.jsonl"
    pages = read_jsonl(pages_path) if pages_path.exists() else []
    docs_path = run_dir / "processed/documents.jsonl"
    documents = read_jsonl(docs_path) if docs_path.exists() else []
    notice_keys = {(r["bid_no"], r["bid_order"], r["url"]) for r in records
                   if r["role"] == "notice" and str(r["selected"]).lower() == "true"}
    pages = [p for p in pages if (p["bid_no"], p["bid_order"], p["source_url"]) in notice_keys]
    documents = [d for d in documents if (d["bid_no"], d["bid_order"], d["source_url"]) in notice_keys]
    return pages, documents


def _publish(run_dir, items, latest, records, profile):
    """공고문 사전 분류·평가 입력·선택 상태를 저장한다. 점수는 계산하지 않는다."""
    pages, documents = _notice_records(run_dir, records)
    previous = read_json(run_dir / "bid_list.json") if (run_dir / "bid_list.json").exists() else {"items": []}
    old_by_id = {r["bid_id"]: r for r in previous["items"]}
    profile_version = hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    selected_path = run_dir / "user_selections.json"
    selections = read_json(selected_path) if selected_path.exists() else {}
    stamp_value = read_json(run_dir / "candidates.json")["request"].get("collected_at", stamp())
    bids, candidates, evaluations = [], [], []
    for item in items:
        active = is_active_notice(item, latest)
        row = collector.notice_row(item, [], stamp_value)
        related = [r for r in records if r["bid_no"] == row["bid_no"] and r["bid_order"] == row["bid_order"]]
        row["downloaded_files"] = sum(r["status"] in DOWNLOAD_SUCCESS and bool(r["local_path"]) for r in related)
        row["failed_files"] = sum(r["status"] == "failed" for r in related)
        candidates.append({**row, "selected": active,
                           "selection_reason": "공고문만 준비; 전체 첨부는 사용자 선택 대기" if active else "이전 차수 또는 취소·철회"})
        if not active:
            continue
        bid_id = identity(item)
        own_pages = [p for p in pages if p["bid_no"] == row["bid_no"] and p["bid_order"] == row["bid_order"]]
        own_docs = [d for d in documents if d["bid_no"] == row["bid_no"] and d["bid_order"] == row["bid_order"]]
        request = _evaluation_request(row, profile, profile_version, own_pages, own_docs)
        evaluation = _stored_evaluation(old_by_id.get(bid_id, {}), request)
        if own_pages and any(p["text"].strip() for p in own_pages):
            evaluations.append(request)
        bids.append(_public_bid(row, request, evaluation, related, selections))
    collector.write_csv(run_dir / "bids.csv", collector.BID_FIELDS, [{k: r[k] for k in collector.BID_FIELDS} for r in bids])
    collector.write_csv(run_dir / "candidates.csv", collector.CANDIDATE_FIELDS, candidates)
    write_jsonl(run_dir / "evaluation_inputs.jsonl", evaluations)
    result = {"schema_version": SCHEMA_VERSION, "updated_at": stamp(), "company_profile_version": profile_version,
              "items": bids, "recommended_bid_ids": [r["bid_id"] for r in bids if r["preliminary"]["status"] == "candidate"]}
    write_json(run_dir / "bid_list.json", result)
    write_json(run_dir / "workflow.json", {"stage": "awaiting_user_selection",
               "bids": len(bids), "notice_ready": sum(bool(r["notice_document"]) and r["notice_status"] in TEXT_READY for r in bids),
               "candidate_bids": len(result["recommended_bid_ids"]), "user_selected": len(selections),
               "full_download_policy": "explicit_user_selection_only", "evaluation_implemented": False,
               "selection_requires_evaluation": False, "scoring_stage": "after_user_selection_optional"})
    return result


def prepare_discovery(run_dir, profile=None, search_only=False, rhwp=None):
    profile = validate_profile({} if profile is None else profile)
    with locked(run_dir) as run_dir:
        saved = read_json(run_dir / "candidates.json")
        items = saved["items"]
        previous = _attachment_cache(run_dir) if (run_dir / "attachments.csv").exists() else {}
        records, latest = _manifest(run_dir, items, previous, "notice")
        # 예전 전체 다운로드 캐시가 있어도 초기 평가에는 공고문만 전달한다.
        write_json(run_dir / "company_profile.json", profile)
        _save_records(run_dir, records)
        collector.write_csv(run_dir / "bids.csv", collector.BID_FIELDS, [
            collector.notice_row(item, saved["request"].get("queries", []), saved["request"].get("collected_at", stamp()))
            for item in items if is_active_notice(item, latest)])
        if not search_only:
            for record in records:
                if record["selected"] and record["role"] == "notice":
                    key = (record["bid_no"], record["bid_order"], record["url"])
                    _download_record(run_dir, record, previous.get(key, {}))
                    _save_records(run_dir, records)
            _prepare_notices(run_dir, records, rhwp)
        result = _publish(run_dir, items, latest, records, profile)
        return result


def _select_bid(run_dir, bid_id):
    listing = read_json(run_dir / "bid_list.json")
    target = next((r for r in listing["items"] if r["bid_id"] == bid_id), None)
    if target is None:
        raise ValueError("이 탐색 결과에 없는 공고번호·차수입니다.")
    items = read_json(run_dir / "candidates.json")["items"]
    previous = _attachment_cache(run_dir)
    records, latest = _manifest(run_dir, items, previous, "all", chosen=bid_id)
    selected_path = run_dir / "user_selections.json"
    selections = read_json(selected_path) if selected_path.exists() else {}
    selections[bid_id] = {"selected_at": stamp(), "evaluation_input_id": target["evaluation_input_id"],
                          "evaluation_status": target["evaluation"]["status"]}
    write_json(selected_path, selections)
    for record in records:
        if f"{record['bid_no']}_{record['bid_order']}" == bid_id:
            key = (record["bid_no"], record["bid_order"], record["url"])
            _download_record(run_dir, record, previous.get(key, {}))
            _save_records(run_dir, records)
    profile = read_json(run_dir / "company_profile.json")
    result = _publish(run_dir, items, latest, records, profile)
    return next(r for r in result["items"] if r["bid_id"] == bid_id)


def select_bids(run_dir, bid_ids):
    """1~2건을 모두 검증한 뒤 명시 선택한 공고만 원본 그대로 받는다."""
    if (not isinstance(bid_ids, list) or not 1 <= len(bid_ids) <= 2
            or any(not isinstance(v, str) for v in bid_ids) or len(set(bid_ids)) != len(bid_ids)):
        raise ValueError("중복 없는 공고 1~2개를 선택하세요.")
    with locked(run_dir) as run_dir:
        listing = read_json(run_dir / "bid_list.json")
        available = {b["bid_id"] for b in listing["items"]}
        if not set(bid_ids) <= available:
            raise ValueError("이 탐색 결과에 없는 공고번호·차수입니다.")
        return [_select_bid(run_dir, bid_id) for bid_id in bid_ids]


def select_bid(run_dir, bid_id):
    """CLI 단건 선택 호환. 점수로 자동 선택하지 않는다."""
    return select_bids(run_dir, [bid_id])[0]


def record_evaluation(run_dir, bid_id, result):
    """외부 평가 결과만 저장한다. 평가 알고리즘은 구현하지 않는다."""
    with locked(run_dir) as run_dir:
        path = run_dir / "bid_list.json"
        listing = read_json(path)
        bid = next((r for r in listing["items"] if r["bid_id"] == bid_id), None)
        if bid is None:
            raise ValueError("탐색 결과에 없는 공고입니다.")
        if bid["evaluation_input_id"] != result.get("evaluation_input_id"):
            raise ValueError("기업 프로필 또는 공고문 버전이 바뀐 평가 결과입니다.")
        if not bid["notice_document"] or bid["notice_status"] not in TEXT_READY:
            raise ValueError("평가 가능한 공고문이 없습니다.")
        score, maximum = result.get("score"), result.get("max_score")
        if (isinstance(score, bool) or isinstance(maximum, bool) or not isinstance(score, (int, float))
                or not isinstance(maximum, (int, float)) or not math.isfinite(score) or not math.isfinite(maximum)
                or maximum <= 0 or not 0 <= score <= maximum or not result.get("evaluator_version")):
            raise ValueError("외부 평가의 점수·만점·평가 버전을 확인하세요.")
        bid["evaluation"] = {"status": "completed", "score": score, "max_score": maximum,
                             "result": result, "recorded_at": stamp()}
        write_json(path, listing)
        return bid["evaluation"]
