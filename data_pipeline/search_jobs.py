"""확정 흐름의 검색 스냅샷 → 공고문 준비 → 선택 첨부 준비와 진행률."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
import uuid

from . import collect_bids as collector
from . import convert_documents as converter
from .common import (ROOT, BID_FIELDS, FILE_FIELDS, DOWNLOAD_SUCCESS, TEXT_READY,
                     HWP_SUFFIXES, directory_lock, read_json, write_json,
                     read_jsonl, write_jsonl, read_csv, write_csv, stamp)
from .knowledge import KnowledgeStore
from .prepare_documents import prepare

CACHE_SECONDS = 300
RESTRICTION_FIELDS = (
    "indstrytyLmtYn", "rgnLmtBidLocplcJdgmBssNm", "jntcontrctDutyRgnNm1",
    "jntcontrctDutyRgnNm2", "jntcontrctDutyRgnNm3", "cmmnSpldmdMethdNm",
    "cntrctCnclsMthdNm", "presmptPrce", "asignBdgtAmt", "bidClseDt",
)
ATTACHMENT_FIELDS = FILE_FIELDS + ["role", "storage_name"]


def latest_notices(items):
    latest = {}
    for item in sorted(items, key=lambda row: str(row.get("bidNtceOrd") or "000").zfill(8)):
        latest[str(item["bidNtceNo"])] = item
    return latest


def is_active_notice(item, latest):
    return latest[str(item["bidNtceNo"])] is item and not any(
        word in str(item.get("ntceKindNm", "")) for word in ("취소", "철회"))


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


class SearchNotFound(ValueError):
    pass


def root_dir():
    return Path(os.environ.get("BID_SEARCH_ROOT", str(ROOT / "data" / "searches"))).resolve()


def classify_attachment(filename):
    """RAG가 제공한 동일 함수를 호출한다. 별도 판별 규칙으로 대체하지 않는다."""
    rag_dir = str(ROOT / "rag-code-template_ext")
    if rag_dir not in sys.path:
        sys.path.insert(0, rag_dir)
    return importlib.import_module("knowledge_bridge").classify_attachment(filename)


def _snapshot(search_id):
    if not re.fullmatch(r"[a-f0-9]{32}", search_id):
        raise SearchNotFound("검색 결과가 없습니다.")
    path = root_dir() / search_id / "search.json"
    if not path.is_file():
        raise SearchNotFound("검색 결과가 없습니다.")
    return read_json(path)


def _public_search(saved, cached):
    items = []
    latest = latest_notices(saved["items"])
    for item in saved["items"]:
        if not is_active_notice(item, latest):
            continue
        row = collector.notice_row(item, saved["request"]["queries"], saved["collected_at"])
        # 허용 목록으로만 응답한다. API 담당자 성명·연락처를 그대로 반환하지 않는다.
        row.update({field: item.get(field) for field in RESTRICTION_FIELDS})
        row["attachments"] = [{"file_name": name, "url": url,
                               "kinds": sorted(classify_attachment(name)) if name != "standard_notice" else ["notice"]}
                              for name, url in collector.attachments(item)]
        items.append(row)
    return {"search_id": saved["search_id"], "items": items, "cached": cached,
            "collected_at": saved["collected_at"], "cache_seconds": CACHE_SECONDS,
            "page_limit_reached": saved["page_limit_reached"]}


def search_bids(start, end, queries, limit, key):
    queries = list(dict.fromkeys(q.strip() for q in queries))
    if start > end or not queries or not all(queries):
        raise ValueError("검색 기간과 검색어를 확인하세요.")
    request = {"from": str(start), "to": str(end), "queries": queries, "limit": limit}
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    with directory_lock(root_dir(), ".search.lock") as root:
        cache = root / f"cache-{digest}.json"
        if cache.exists():
            cached = read_json(cache)
            if time.time() - cached["created_epoch"] < CACHE_SECONDS:
                return _public_search(_snapshot(cached["search_id"]), True)
        if not key:
            raise RuntimeError("DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.")
        items, truncated = collector.search_candidates(key, start, end, queries, limit)
        search_id = uuid.uuid4().hex
        folder = root / search_id
        folder.mkdir()
        saved = {"search_id": search_id, "request": request, "items": items,
                 "collected_at": stamp(), "page_limit_reached": truncated}
        # 판별 함수 연결 오류가 나면 사용할 수 없는 결과를 캐시에 등록하지 않는다.
        response = _public_search(saved, False)
        write_json(folder / "search.json", saved)
        write_json(cache, {"created_epoch": time.time(), "search_id": search_id})
        return response


def select_items(search_id, bids):
    saved = _snapshot(search_id)
    latest = latest_notices(saved["items"])
    available = {(str(i["bidNtceNo"]), str(i.get("bidNtceOrd") or "000")): i
                 for i in saved["items"] if is_active_notice(i, latest)}
    keys = [(b["bid_no"], b["bid_order"]) for b in bids]
    if not 1 <= len(keys) <= 20 or len(set(keys)) != len(keys):
        raise ValueError("중복 없는 공고 1~20건을 지정하세요.")
    if not set(keys) <= available.keys():
        raise ValueError("이 검색 결과에 없는 공고번호·차수입니다.")
    return [available[key] for key in keys]


def create_job(search_id, bids, mode):
    select_items(search_id, bids)
    job_id = uuid.uuid4().hex
    folder = root_dir() / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    job = {"job_id": job_id, "search_id": search_id, "mode": mode,
           "status": "queued", "done": 0, "total": len(bids), "created_at": stamp(),
           "bids": [{**bid, "status": "queued", "error": None} for bid in bids]}
    write_json(folder / f"{job_id}.json", job)
    return job


def get_job(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise SearchNotFound("작업이 없습니다.")
    path = root_dir() / "jobs" / f"{job_id}.json"
    if not path.is_file():
        raise SearchNotFound("작업이 없습니다.")
    return read_json(path)


def _notice_url(item):
    options = []
    for position, (name, url) in enumerate(collector.attachments(item)):
        standard = name == "standard_notice"
        kinds = {"notice"} if standard else classify_attachment(name)
        suffix = Path(name).suffix.lower()
        if "notice" in kinds and "cancel" not in kinds and (standard or suffix in {".pdf", ".hwp", ".hwpx"}):
            options.append((0 if suffix == ".pdf" else 2 if standard else 1, position, url))
    return min(options)[2] if options else None


def _attachment_rows(item, notice_url, full, previous):
    rows = []
    for position, (name, url) in enumerate(collector.attachments(item), 1):
        is_notice = url == notice_url
        row = {"bid_no": str(item["bidNtceNo"]), "bid_order": str(item.get("bidNtceOrd") or "000"),
               "file_name": name, "url": url, "selected": full or is_notice,
               "status": "listed" if full or is_notice else "deferred", "local_path": "", "error": "",
               "role": "notice" if is_notice else "supporting",
               "storage_name": f"{position:02}_{'표준입찰공고서' if name == 'standard_notice' else collector.safe_name(name)}"}
        old = previous.get(url, {})
        if old.get("status") in DOWNLOAD_SUCCESS:
            row.update({k: old.get(k, "") for k in ("status", "local_path", "error")})
        rows.append(row)
    return rows


def _prepare_selected(folder, rows):
    """내부 적재용 공고문/RFP만 변환한다. 신청서·ZIP 등 원본은 그대로 보존한다."""
    def stem(row):
        return unicodedata.normalize("NFC", Path(row["file_name"]).stem).casefold()

    pdfs = {stem(row) for row in rows if row["status"] in DOWNLOAD_SUCCESS
            and Path(row["local_path"]).suffix.lower() == ".pdf"}
    scoped = []
    for row in rows:
        kinds = {"notice"} if row["file_name"] == "standard_notice" else classify_attachment(row["file_name"])
        selected = row["selected"] and bool(kinds & {"notice", "rfp"}) and "cancel" not in kinds
        if Path(row["file_name"]).suffix.lower() in HWP_SUFFIXES and stem(row) in pdfs:
            selected = False  # 원본은 보존하고 같은 이름의 PDF만 내부 적재에 쓴다.
        prepared = {**row, "selected": selected}
        if row["file_name"] == "standard_notice" and row["local_path"]:
            # API에 이름이 없는 표준공고서도 RAG의 공통 판별 함수가 인식할 수 있게 한다.
            prepared["file_name"] = Path(row["local_path"]).name
        scoped.append(prepared)
    write_csv(folder / "attachments.csv", ATTACHMENT_FIELDS, scoped)
    try:
        if any(row["selected"] and row["status"] in DOWNLOAD_SUCCESS
               and Path(row["local_path"]).suffix.lower() in HWP_SUFFIXES for row in scoped):
            conversion_file = folder / "conversions.jsonl"
            cached = {row["original_path"]: row for row in read_jsonl(conversion_file)} if conversion_file.exists() else {}
            with directory_lock(root_dir(), ".conversion.lock"):
                converter.convert_run(folder)
            cached.update({row["original_path"]: row for row in read_jsonl(conversion_file)})
            write_jsonl(conversion_file, cached.values())
        prepare(folder)
    finally:
        write_csv(folder / "attachments.csv", ATTACHMENT_FIELDS, rows)


def _process_bid(item, full, store, progress):
    bid_no = str(item["bidNtceNo"])
    order = str(item.get("bidNtceOrd") or "000")
    folder = root_dir() / "documents" / collector.safe_name(f"{bid_no}_{order}")
    with directory_lock(folder, ".document.lock"):
        progress("downloading")
        notice_url = _notice_url(item)
        if not full and notice_url is None:
            raise ValueError("공고문 첨부를 식별하지 못했습니다. 다른 첨부로 대체하지 않습니다.")
        manifest = folder / "attachments.csv"
        previous = {r["url"]: r for r in read_csv(manifest)} if manifest.exists() else {}
        rows = _attachment_rows(item, notice_url, full, previous)
        if not rows:
            raise ValueError("API가 제공한 첨부가 없습니다.")
        for row in rows:
            if row["selected"]:
                _download_record(folder, row, previous.get(row["url"], {}))
                write_csv(manifest, ATTACHMENT_FIELDS, rows)
        write_json(folder / "candidates.json", {"items": [item]})
        published = previous and (folder / "bids.csv").exists()
        collected_at = read_csv(folder / "bids.csv")[0]["collected_at"] if published else stamp()
        write_csv(folder / "bids.csv", BID_FIELDS, [collector.notice_row(item, [], collected_at)])
        progress("converting")
        _prepare_selected(folder, rows)
        documents = read_jsonl(folder / "processed/documents.jsonl")
        chunks = read_jsonl(folder / "processed/chunks.jsonl")
        ready = {(d["bid_no"], d["bid_order"], d["source_url"])
                 for d in documents if d["status"] in TEXT_READY}
        records = []
        for chunk in chunks:
            if (chunk["bid_no"], chunk["bid_order"], chunk["source_url"]) in ready:
                records.append({**chunk, "group_id": f"{bid_no}_{order}:{chunk['source_url']}"})
        if records:
            progress("indexing")
            store.upsert(records)  # 실시간 경로는 누적 적재만 허용한다.
        failures = [r["file_name"] for r in rows if r["selected"] and r["status"] == "failed"]
        failures += [d["original_file_name"] for d in documents if d["status"] not in TEXT_READY]
        if not records:
            failures.append("적재 가능한 공고문/제안요청서 텍스트가 없습니다.")
        files = [{"file_name": r["file_name"], "status": r["status"]} for r in rows]
        return {"status": "partial_failed" if failures and records else "failed" if failures else "completed",
                "error": "확인 필요: " + ", ".join(dict.fromkeys(failures)) if failures else None,
                "files": files, "indexed_chunks": len(records)}


def run_job(job_id, key=None):
    job = get_job(job_id)
    path = root_dir() / "jobs" / f"{job_id}.json"
    job["status"] = "running"
    write_json(path, job)
    try:
        items = select_items(job["search_id"], job["bids"])
        store = KnowledgeStore("pdf")
        for position, item in enumerate(items):
            bid = job["bids"][position]

            def progress(status):
                bid["status"] = status
                write_json(path, job)

            try:
                if job["mode"] == "documents":
                    # 전체 검색을 재실행하지 않고 선택된 공고번호만 조회한다.
                    current = collector.lookup_notice(key, bid["bid_no"])
                    latest_order = str(current.get("bidNtceOrd") or "000")
                    if int(latest_order) < int(bid["bid_order"]):
                        raise ValueError("저장된 공고보다 이전 차수가 반환돼 다운로드를 중단했습니다.")
                    bid["requested_bid_order"] = bid["bid_order"]
                    bid["revision_changed"] = latest_order != bid["bid_order"]
                    bid["bid_order"] = latest_order
                    if bid["revision_changed"]:
                        item = current
                        folder = root_dir() / job["search_id"]
                        write_json(folder / f"revision-{collector.safe_name(bid['bid_no'])}-{latest_order}.json", current)
                bid.update(_process_bid(item, job["mode"] == "documents", store, progress))
            except Exception as exc:
                # SDK/네트워크 예외 원문은 인증키나 연락처를 포함할 수 있다.
                message = str(exc) if isinstance(exc, (collector.CollectionError, ValueError, RuntimeError)) else type(exc).__name__
                bid.update(status="failed", error=message)
            job["done"] += 1
            write_json(path, job)
        statuses = [bid["status"] for bid in job["bids"]]
        job["status"] = ("completed" if all(status == "completed" for status in statuses)
                         else "failed" if all(status == "failed" for status in statuses)
                         else "partial_failed")
    except Exception as exc:
        job.update(status="failed", error=type(exc).__name__)
    job["finished_at"] = stamp()
    write_json(path, job)
