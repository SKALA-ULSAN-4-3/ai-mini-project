"""확정 흐름의 검색 스냅샷 → 공고문 준비 → 선택 첨부 준비와 진행률."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import importlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import tempfile
import subprocess
import sys
import time
import unicodedata
import uuid

from . import collect_bids as collector
from . import restrictions
from . import convert_documents as converter
from . import bid_progress
from . import cache_api
from .common import (ROOT, BID_FIELDS, FILE_FIELDS, DOWNLOAD_SUCCESS, TEXT_READY,
                     HWP_SUFFIXES, directory_lock, read_json, write_json,
                     read_jsonl, write_jsonl, read_csv, write_csv, stamp)
from .knowledge import KnowledgeStore
from .privacy import official_names
from .persistence import BackendStore, identity

CACHE_SECONDS = 300
ACTIVE_JOBS = set()
PREPARE_VERSION = hashlib.sha256(b"".join(
    (Path(__file__).parent / name).read_bytes()
    for name in ("prepare_documents.py", "privacy.py", "convert_documents.py"))).hexdigest()
RESTRICTION_FIELDS = (
    "indstrytyLmtYn", "rgnLmtBidLocplcJdgmBssNm", "jntcontrctDutyRgnNm1",
    "jntcontrctDutyRgnNm2", "jntcontrctDutyRgnNm3", "cmmnSpldmdMethdNm",
    "cntrctCnclsMthdNm", "presmptPrce", "asignBdgtAmt", "bidClseDt", "opengDt",
)
ATTACHMENT_FIELDS = FILE_FIELDS + ["role", "storage_name", "source", "document_type"]


def _enrich_restrictions(item, key):
    """공고·차수별 공개 제한 정보를 잠시 재사용한다. 실패 결과는 캐시하지 않는다."""
    bid_no, order = str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000")
    folder = root_dir() / "restriction-cache"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (collector.safe_name(f"{bid_no}_{order}") + ".json")
    details = None
    if path.is_file():
        try:
            cached = read_json(path)
            if (cached.get("bid_no"), cached.get("bid_order"), cached.get("industry_flag")) == (
                    bid_no, order, item.get("indstrytyLmtYn")) and time.time() - cached["created_epoch"] < CACHE_SECONDS:
                details = cached["details"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    if details is None:
        details = restrictions.lookup_restrictions(item, key)
        if all(d.get("lookup_status") == "complete" for d in details.values()):
            write_json(path, {"bid_no": bid_no, "bid_order": order,
                              "industry_flag": item.get("indstrytyLmtYn"),
                              "created_epoch": time.time(), "details": details})
    return {**item, **details}


def _enrich_candidate(item, key):
    # 검색에서는 자격 제한과 공고문 목록만 확인한다. e발주 전체 첨부는 사용자 선택 후 조회한다.
    return _enrich_restrictions(item, key)


def _enrich_eorder(item, key):
    enriched = dict(item)
    # 이전 결과가 남아 있어도 최신 조회가 실패하면 오래된 첨부를 준비 완료 근거로 쓰지 않는다.
    enriched["eorder_attachments"] = []
    try:
        enriched["eorder_attachments"] = collector.lookup_eorder_attachments(
            key, str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000"))
        enriched["eorder_lookup_status"] = "complete"
        enriched.pop("eorder_lookup_error", None)
    except collector.CollectionError as exc:
        enriched["eorder_lookup_status"] = "unavailable"
        enriched["eorder_lookup_error"] = str(exc)
    return enriched


def _attachment_source(item, url):
    for attachment in item.get("eorder_attachments", []):
        if attachment["url"] == url and (attachment.get("bid_no"), attachment.get("bid_order")) == (
                str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000")):
            return {"source": "eorder", "document_type": attachment.get("document_type", "")}
    return {"source": "notice", "document_type": ""}


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


class PrepareTimeout(RuntimeError):
    pass


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


def _public_search(saved, cached, now=None):
    items = []
    latest = latest_notices(saved["items"])
    for item in saved["items"]:
        if not is_active_notice(item, latest):
            continue
        if saved["request"].get("date_basis") == "deadline" and not collector.deadline_in_period(
                item, date.fromisoformat(saved["request"].get("deadline_from", saved["request"]["from"])),
                date.fromisoformat(saved["request"]["to"])):
            continue
        row = collector.notice_row(item, saved["request"]["queries"], saved["collected_at"])
        # 허용 목록으로만 응답한다. API 담당자 성명·연락처를 그대로 반환하지 않는다.
        row.update({field: item.get(field) for field in RESTRICTION_FIELDS})
        row["bid_progress"] = {"lookup_status": "not_checked", "state": "not_checked",
                                "label": "선택 후 개찰·재입찰 상태를 확인합니다."}
        row.update({field: item[field] for field in ("region_restriction", "industry_restriction") if field in item})
        row["attachments"] = [{"file_name": name, "url": url,
                               **_attachment_source(item, url),
                               "kinds": sorted(classify_attachment(name)) if name != "standard_notice" else ["notice"]}
                              for name, url in collector.attachments(item)]
        row["rfp_listed"] = any("rfp" in a["kinds"] and "cancel" not in a["kinds"]
                                for a in row["attachments"])
        row["attachment_lookup_status"] = item.get("eorder_lookup_status", "not_checked")
        row["notice_only"] = row["attachment_lookup_status"] == "complete" and bool(row["attachments"]) and all(
            a["kinds"] == ["notice"] for a in row["attachments"])
        row["warnings"] = (["해당 공고는 공고문만 있다. 제공된 첨부 목록 기준이며 공고 상세 확인이 필요합니다."]
                           if row["notice_only"] else [])
        if row["attachment_lookup_status"] == "unavailable" and not row["rfp_listed"]:
            row["warnings"].append("제안요청정보의 첨부 목록을 확인하지 못했습니다. 공고문만 있다고 단정할 수 없습니다.")
        items.append(row)
    return {"search_id": saved["search_id"], "items": items, "cached": cached,
            "progress_excluded": saved.get("progress_excluded", []),
            "deadline_unknown": saved.get("deadline_unknown", []),
            "cancelled_withdrawn": saved.get("cancelled_withdrawn", []),
            "search_coverage": saved.get("search_coverage"),
            "publication_from": saved["request"].get("publication_from"),
            "publication_to": saved["request"].get("publication_to"),
            "deadline_from": saved["request"].get("deadline_from", saved["request"].get("from")),
            "deadline_to": saved["request"].get("to"),
            "date_basis": saved["request"].get("date_basis", "published_at"),
            "collected_at": saved["collected_at"], "cache_seconds": CACHE_SECONDS,
            "page_limit_reached": saved["page_limit_reached"]}


def _restore_cached_search(payload, request, current_time):
    """DB 캐시의 원본 공고와 첨부 메타데이터로 새 로컬 search_id를 만든다."""
    snapshot = payload.get("snapshot") if isinstance(payload, dict) else None
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("items"), list):
        return None
    cached_request = snapshot.get("request")
    if not isinstance(cached_request, dict):
        return None
    for key in ("from", "to", "queries", "limit", "date_basis", "deadline_from",
                "publication_from", "publication_to", "discovery_strategy",
                "restriction_sources", "attachment_sources"):
        if cached_request.get(key) != request.get(key):
            return None
    saved = dict(snapshot)
    saved["search_id"] = uuid.uuid4().hex
    saved["cached_recommendation"] = payload.get("recommendation")
    saved["cache_saved"] = True
    saved["cache_auth_failed"] = False
    saved["cache_source"] = "database"
    root = root_dir()
    folder = root / saved["search_id"]
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "search.json", saved)
    response = _public_search(saved, True, current_time)
    response["cache_source"] = "database"
    return response


def search_bids(start, end, queries, limit, key, authorization=None):
    queries = list(dict.fromkeys(q.strip() for q in queries))
    if start > end or not queries or not all(queries):
        raise ValueError("검색 기간과 검색어를 확인하세요.")
    current_time = datetime.now(collector.KST)
    discovery_start = start
    discovery_end = current_time.date()
    deadline_start = current_time.date()
    if start > discovery_end:
        raise ValueError("게시 시작일은 오늘 이전 또는 오늘이어야 합니다.")
    if end < deadline_start:
        raise ValueError("마감 종료일은 오늘 이후 또는 오늘이어야 합니다.")
    request = {"from": str(start), "to": str(end), "queries": queries, "limit": limit,
               "date_basis": "deadline", "discovery_strategy": "publication-start-deadline-end-no-progress-v2",
               "deadline_from": str(deadline_start),
               "publication_from": str(discovery_start), "publication_to": str(discovery_end),
               "restriction_sources": "region-license-v2",
               "attachment_sources": "notice+eorder-standard-name-v2"}
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    remote_cache = cache_api.lookup_search(start, end, queries, limit, authorization)
    if remote_cache.get("cached"):
        restored = _restore_cached_search(remote_cache.get("result"), request, current_time)
        if restored is not None:
            restored["cache_sync"] = {"status": "reused"}
            return restored
    with directory_lock(root_dir(), ".search.lock") as root:
        cache = root / f"cache-{digest}.json"
        if cache.exists():
            cached = read_json(cache)
            if time.time() - cached["created_epoch"] < CACHE_SECONDS:
                local_snapshot = _snapshot(cached["search_id"])
                local = _public_search(local_snapshot, True, current_time)
                local["cache_sync"] = {"status": remote_cache.get("status", "miss"),
                                        "auth_failed": bool(remote_cache.get("auth_failed"))}
                if remote_cache.get("auth_failed"):
                    local_snapshot["cache_auth_failed"] = True
                    write_json(root / cached["search_id"] / "search.json", local_snapshot)
                return local
        if not key:
            raise RuntimeError("DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.")
        deadline_unknown, cancelled_withdrawn = {}, {}

        def current_candidate(item):
            identity = (str(item.get("bidNtceNo") or ""), str(item.get("bidNtceOrd") or "000"))
            if not identity[0]:
                return None
            if any(w in str(item.get("ntceKindNm") or "") for w in ("취소", "철회")):
                cancelled_withdrawn[identity] = {"bid_no": identity[0], "bid_order": identity[1],
                                                 "reason": str(item.get("ntceKindNm") or "취소·철회")}
                return None
            return item

        def record_excluded(item, reason):
            identity = (str(item.get("bidNtceNo") or ""), str(item.get("bidNtceOrd") or "000"))
            if reason == "deadline_unknown" and identity[0]:
                deadline_unknown[identity] = {"bid_no": identity[0], "bid_order": identity[1],
                                              "title": str(item.get("bidNtceNm") or ""),
                                              "reason": "공고 API에 마감일이 없어 기간 포함 여부를 확인할 수 없습니다."}

        items, truncated, coverage = collector.search_deadline_candidates(
            key, discovery_start, discovery_end, deadline_start, end, queries, limit,
            candidate_transform=current_candidate, excluded_callback=record_excluded)
        cancelled_orders = {}
        for row in cancelled_withdrawn.values():
            cancelled_orders[row["bid_no"]] = max(int(row["bid_order"]), cancelled_orders.get(row["bid_no"], -1))
        items = [row for row in items if int(str(row.get("bidNtceOrd") or "000"))
                 > cancelled_orders.get(str(row.get("bidNtceNo") or ""), -1)]
        latest = latest_notices(items)
        # 상세 제한을 조회하고, 일반 첨부에 RFP가 없으면 e발주 목록도 보완한다.
        positions = [i for i, item in enumerate(items) if is_active_notice(item, latest)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            enriched = executor.map(lambda i: _enrich_candidate(items[i], key), positions)
            for i, item in zip(positions, enriched):
                items[i] = item
        search_id = uuid.uuid4().hex
        folder = root / search_id
        folder.mkdir()
        saved = {"search_id": search_id, "request": request, "items": items,
                 "progress_excluded": [], "deadline_unknown": list(deadline_unknown.values()),
                 "cancelled_withdrawn": list(cancelled_withdrawn.values()),
                 "search_coverage": coverage,
                 "collected_at": stamp(), "page_limit_reached": truncated}
        saved["cache_auth_failed"] = bool(remote_cache.get("auth_failed"))
        # 판별 함수 연결 오류가 나면 사용할 수 없는 결과를 캐시에 등록하지 않는다.
        response = _public_search(saved, False, current_time)
        response["cache_sync"] = {"status": remote_cache.get("status", "miss"),
                                  "error": remote_cache.get("error"),
                                  "auth_failed": bool(remote_cache.get("auth_failed"))}
        write_json(folder / "search.json", saved)
        latest = latest_notices(items)
        details_complete = all(
            all(item.get(field, {}).get("lookup_status") == "complete"
                for field in ("region_restriction", "industry_restriction"))
            for item in items if is_active_notice(item, latest))
        if details_complete:
            write_json(cache, {"created_epoch": time.time(), "search_id": search_id})
        return response


def select_items(search_id, bids, *, check_deadline=True):
    saved = _snapshot(search_id)
    latest = latest_notices(saved["items"])
    if not check_deadline:
        by_number = {}
        for item in saved["items"]:
            if is_active_notice(item, latest):
                by_number[str(item["bidNtceNo"])] = item
        keys = [(b["bid_no"], b["bid_order"]) for b in bids]
        if not 1 <= len(keys) <= 20 or len(set(keys)) != len(keys):
            raise ValueError("중복 없는 공고 1~20건을 지정하세요.")
        if any(no not in by_number for no, _ in keys):
            raise ValueError("이 검색 결과에 없는 공고번호입니다.")
        return [{**by_number[no], "bidNtceOrd": order} for no, order in keys]
    available = {}
    request = saved.get("request", {})
    for item in saved["items"]:
        if not is_active_notice(item, latest):
            continue
        if check_deadline and request.get("date_basis") == "deadline":
            if not collector.deadline_in_period(
                    item, date.fromisoformat(request.get("deadline_from", request["from"])),
                    date.fromisoformat(request["to"])):
                continue
        available[(str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000"))] = item
    keys = [(b["bid_no"], b["bid_order"]) for b in bids]
    if not 1 <= len(keys) <= 20 or len(set(keys)) != len(keys):
        raise ValueError("중복 없는 공고 1~20건을 지정하세요.")
    if not set(keys) <= available.keys():
        raise ValueError("이 검색 결과에 없는 공고번호·차수입니다.")
    return [available[key] for key in keys]


def create_job(search_id, bids, mode):
    select_items(search_id, bids, check_deadline=mode != "db_retry")
    identity = sorted((b["bid_no"], b["bid_order"]) for b in bids)
    with directory_lock(root_dir(), ".jobs.lock"):
        folder = root_dir() / "jobs"
        folder.mkdir(parents=True, exist_ok=True)
        for path in folder.glob("*.json"):
            old = read_json(path)
            if (old.get("job_id") in ACTIVE_JOBS
                    and old.get("mode") == mode
                    and old.get("status") in {"queued", "running"}
                    and sorted((b["bid_no"], b["bid_order"]) for b in old["bids"]) == identity):
                return {**old, "reused": True}
        job_id = uuid.uuid4().hex
        job = {"job_id": job_id, "search_id": search_id, "mode": mode,
               "status": "queued", "done": 0, "total": len(bids), "created_at": stamp(),
               "bids": [{**bid, "status": "queued", "error": None} for bid in bids]}
        write_json(folder / f"{job_id}.json", job)
        ACTIVE_JOBS.add(job_id)
        return job


def get_job(job_id):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise SearchNotFound("작업이 없습니다.")
    path = root_dir() / "jobs" / f"{job_id}.json"
    if not path.is_file():
        raise SearchNotFound("작업이 없습니다.")
    job = read_json(path)
    for bid in job.get("bids", []):
        if bid.get("status") != "converting":
            continue
        manifest = root_dir() / "documents" / collector.safe_name(
            f"{bid['bid_no']}_{bid['bid_order']}") / "conversions.jsonl"
        if manifest.is_file():
            bid["conversion_progress"] = [{"file_name": Path(row["original_path"]).name,
                "status": row.get("status"), "attempt": row.get("attempt"),
                "max_attempts": row.get("max_attempts"), "timeout_seconds": row.get("timeout_seconds")}
                for row in read_jsonl(manifest)]
    return job


def _notice_url(item):
    options = []
    for position, (name, url) in enumerate(collector.attachments(item)):
        standard = url == str(item.get("stdNtceDocUrl") or "").strip()
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
               **_attachment_source(item, url),
               "file_name": name, "url": url, "selected": full or is_notice,
               "status": "listed" if full or is_notice else "deferred", "local_path": "", "error": "",
               "role": "notice" if is_notice else "supporting",
               "storage_name": f"{position:02}_{'표준입찰공고서' if name == 'standard_notice' else collector.safe_name(name)}"}
        old = previous.get(url, {})
        if old.get("status") in DOWNLOAD_SUCCESS:
            row.update({k: old.get(k, "") for k in ("status", "local_path", "error")})
        rows.append(row)
    return rows


def _run_prepare_worker(folder, convert_hwp, timeout, env):
    """변환뿐 아니라 PDF 검증·텍스트 추출까지 별도 프로세스에서 시간 제한한다."""
    command = [sys.executable, "-m", "data_pipeline.prepare_documents", "--run-dir", str(folder)]
    if convert_hwp:
        command.append("--convert-hwp")
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True, env=env)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # soffice 자식 프로세스도 종료해 변환 프로필·파일 잠금이 남지 않게 한다.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
        raise PrepareTimeout(f"문서 변환·텍스트 추출이 {timeout}초를 초과해 중단했습니다. 원본은 보존되며 재시도 시 성공 파일을 재사용합니다.") from None
    if process.returncode not in (0, 2):
        raise RuntimeError("문서 변환·텍스트 추출 프로세스가 실패했습니다. 변환 도구 설정과 문서 형식을 확인하세요.")


def _prepare_with_timeout(folder, convert_hwp, timeout=None):
    if not convert_hwp:
        return _run_prepare_worker(folder, False, timeout or 120, None)
    if timeout is None:
        per_file, attempts, overall_limit = converter.conversion_policy()
        originals = {converter.sha256(Path(row["local_path"])) for row in read_csv(folder / "attachments.csv")
                     if str(row.get("selected")).lower() == "true" and row.get("local_path")
                     and Path(row["local_path"]).suffix.lower() in HWP_SUFFIXES
                     and Path(row["local_path"]).is_file()}
        per_file_budget = sum(converter.attempt_timeout(per_file, attempt)
                              for attempt in range(1, attempts + 1))
        timeout = min(overall_limit, max(180, len(originals) * per_file_budget + 180))
    # 변환 프로필만 격리한다. 확장 파일은 재설치·재다운로드하지 않는다.
    with tempfile.TemporaryDirectory(prefix="bid-office-") as temp:
        profile = Path(temp) / "profile"
        if converter.PROFILE.is_dir():
            shutil.copytree(converter.PROFILE, profile,
                            ignore=shutil.ignore_patterns(".lock", "*.lock", "lock"))
        else:
            raise RuntimeError("한글 변환 프로필이 없습니다. 변환 도구 설정을 확인하세요.")
        env = {**os.environ, "BID_CONVERTER_PROFILE": str(profile)}
        try:
            return _run_prepare_worker(folder, True, timeout, env)
        except PrepareTimeout:
            # 성공한 변환 기록과 원본은 남겨 PDF 텍스트 추출만 이어간다.
            # 실패·미변환 파일은 documents.jsonl에 남아 부분 실패로 안내된다.
            return _run_prepare_worker(folder, False, 120, None)


def _prepare_selected(folder, rows, full=False, backend=None):
    """공고문·제안요청서·협약문서를 변환한다. 신청서·ZIP 등 원본은 그대로 보존한다."""
    def stem(row):
        return unicodedata.normalize("NFC", Path(row["file_name"]).stem).casefold()

    pdfs = {stem(row) for row in rows if row["status"] in DOWNLOAD_SUCCESS
            and Path(row["local_path"]).suffix.lower() == ".pdf"}
    scoped = []
    for row in rows:
        kinds = {"notice"} if row.get("role") == "notice" else classify_attachment(row["file_name"])
        selected = (row["selected"] and "cancel" not in kinds
                    and ((full and Path(row["local_path"]).suffix.lower() in {".hwp", ".hwpx", ".pdf"})
                         or bool(kinds & {"notice", "rfp", "agreement"})))
        if Path(row["file_name"]).suffix.lower() in HWP_SUFFIXES and stem(row) in pdfs:
            selected = False  # 원본은 보존하고 같은 이름의 PDF만 내부 적재에 쓴다.
        prepared = {**row, "selected": selected}
        if row["file_name"] == "standard_notice" and row["local_path"]:
            # API에 이름이 없는 표준공고서도 RAG의 공통 판별 함수가 인식할 수 있게 한다.
            prepared["file_name"] = Path(row["local_path"]).name
        scoped.append(prepared)
    selected = [row for row in scoped if row["selected"] and row["status"] in DOWNLOAD_SUCCESS]
    config = converter.TOOLS / "converter.json"
    inputs = {"version": PREPARE_VERSION,
              "files": [(row["url"], row["file_name"], converter.sha256(Path(row["local_path"]))) for row in selected],
              "bids": [{k: v for k, v in bid.items() if k not in (
                  "collected_at", "downloaded_files", "failed_files")} for bid in read_csv(folder / "bids.csv")],
              "names": [official_names(item) for item in read_json(folder / "candidates.json").get("items", [])],
              "converter": converter.sha256(config) if config.is_file() else None}
    fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    cache_file = folder / "prepared-cache.json"
    try:
        cached = read_json(cache_file)
        if (cached["fingerprint"] == fingerprint and cached["outputs"]
                and all((folder / name).is_file() and converter.sha256(folder / name) == digest
                        for name, digest in cached["outputs"].items())):
            return
    except (OSError, ValueError, KeyError, TypeError):
        pass
    cache_file.unlink(missing_ok=True)
    if backend and backend.configured and backend.restore_prepared(folder, fingerprint, selected):
        return
    write_csv(folder / "attachments.csv", ATTACHMENT_FIELDS, scoped)
    try:
        if any(row["selected"] and row["status"] in DOWNLOAD_SUCCESS
               and Path(row["local_path"]).suffix.lower() in HWP_SUFFIXES for row in scoped):
            conversion_file = folder / "conversions.jsonl"
            cached = {row["original_path"]: row for row in read_jsonl(conversion_file)} if conversion_file.exists() else {}
            _prepare_with_timeout(folder, True)
            cached.update({row["original_path"]: row for row in read_jsonl(conversion_file)})
            write_jsonl(conversion_file, cached.values())
        else:
            _prepare_with_timeout(folder, False)
        documents = read_jsonl(folder / "processed/documents.jsonl")
        if documents and all(doc["status"] in TEXT_READY for doc in documents):
            outputs = {name: converter.sha256(folder / name) for name in (
                "processed/pages.jsonl", "processed/chunks.jsonl", "processed/documents.jsonl")}
            conversion_file = folder / "conversions.jsonl"
            if conversion_file.is_file():
                for record in read_jsonl(conversion_file):
                    if (record.get("status") in ("converted", "existing")
                            and record.get("original_path") in {str(Path(row["local_path"]).resolve()) for row in selected}):
                        path = Path(record["pdf_path"]).resolve()
                        if path.is_relative_to(folder.resolve()):
                            outputs[str(path.relative_to(folder.resolve()))] = converter.sha256(path)
            write_json(cache_file, {"fingerprint": fingerprint, "outputs": outputs})
    finally:
        write_csv(folder / "attachments.csv", ATTACHMENT_FIELDS, rows)


def _document_readiness(item, rows, indexed_records, documents=()):
    """다운로드와 실제 RFP 청크 적재를 구분한다. 파일명·URL만으로 준비 완료를 추정하지 않는다."""
    files = []
    for row in rows:
        kinds = ({"notice"} if row.get("role") == "notice"
                 else classify_attachment(row["file_name"]))
        records = [r for r in indexed_records if r["source_url"] == row["url"]]
        document = next((d for d in documents if d["source_url"] == row["url"]), {})
        rfp_ready = "cancel" not in kinds and any(
            "rfp" in classify_attachment(r["file_name"]) for r in records)
        files.append({"file_name": row["file_name"], "url": row["url"],
                      "source": row.get("source", "notice"), "document_type": row.get("document_type", ""),
                      "status": row["status"], "kinds": sorted(kinds),
                      "preparation_status": document.get("status", "not_processed"),
                      "preparation_error": document.get("error", ""),
                      "indexed_chunks": len(records), "rfp_ready": rfp_ready})
    selected = [r for r in rows if r["selected"]]
    download_complete = bool(selected) and all(
        r["status"] in DOWNLOAD_SUCCESS and bool(r["local_path"])
        and Path(r["local_path"]).is_file() and Path(r["local_path"]).stat().st_size > 0
        for r in selected)
    rfp_files = [f for f in files if "rfp" in f["kinds"] and "cancel" not in f["kinds"]]
    rfp_ready = any(f["rfp_ready"] for f in rfp_files)
    lookup_status = item.get("eorder_lookup_status", "not_checked")
    rfp_status = ("ready" if rfp_ready else "lookup_failed" if not rfp_files and lookup_status == "unavailable"
                  else "not_checked" if not rfp_files and lookup_status == "not_checked"
                  else "not_listed" if not rfp_files
                  else "download_failed" if any(f["status"] == "failed" for f in rfp_files)
                  else "not_requested" if all(f["status"] == "deferred" for f in rfp_files)
                  else "not_indexed")
    return {"download_complete": download_complete, "rfp_ready": rfp_ready,
            "attachment_lookup_status": lookup_status,
            "rfp_status": rfp_status, "rfp_files": rfp_files, "files": files,
            "detail_url": item.get("bidNtceDtlUrl") or item.get("bidNtceUrl", "")}


def _source_identity(item, row):
    return identity(row["bid_no"], row["bid_order"], row["url"], row["file_name"],
                    item.get("chgDt") or item.get("bidNtceDt") or "")


def _converted_files(backend, folder, rows, item, restore=False):
    config_path = converter.TOOLS / "converter.json"
    if not backend.configured or not config_path.is_file():
        return
    config = read_json(config_path)
    path = folder / "conversions.jsonl"
    records = {r["original_path"]: r for r in read_jsonl(path)} if path.is_file() else {}
    for row in rows:
        if str(row.get("selected")).lower() != "true" or row["status"] not in DOWNLOAD_SUCCESS:
            continue
        original = Path(row["local_path"]).resolve()
        if original.suffix.lower() not in HWP_SUFFIXES:
            continue
        digest = converter.sha256(original)
        key = identity(_source_identity(item, row), digest, PREPARE_VERSION, config)
        record = records.get(str(original), {})
        pdf = Path(record.get("pdf_path") or "__missing__")
        valid = (record.get("original_sha256") == digest and pdf.is_file()
                 and record.get("status") in ("converted", "existing")
                 and all(record.get(k) == config.get(k) for k in config)
                 and record.get("pdf_sha256") == converter.sha256(pdf))
        if restore and not valid:
            source_id = hashlib.sha256((str(original) + digest).encode()).hexdigest()[:16]
            pdf = folder / "converted" / source_id / (original.stem + ".pdf")
            if backend.restore('converted', key, pdf):
                records[str(original)] = {"bid_no": row["bid_no"], "bid_order": row["bid_order"],
                    "original_path": str(original), "original_sha256": digest,
                    "pdf_path": str(pdf), "pdf_sha256": converter.sha256(pdf), "status": "existing",
                    "requires_layout_review": True, **config}
        elif not restore and valid:
            backend.put('converted', key, Path(row["file_name"]).stem + '.pdf', pdf.read_bytes(), row["url"])
    if restore and records:
        write_jsonl(path, records.values())


def _rfp_fingerprint(item, rows):
    inputs = []
    for row in rows:
        if str(row.get("selected")).lower() != "true" or row.get("status") not in DOWNLOAD_SUCCESS:
            continue
        path = Path(row.get("local_path") or "__missing__")
        if not path.is_file():
            return None
        inputs.append((row.get("url"), row.get("file_name"), converter.sha256(path)))
    if not inputs:
        return None
    config_path = converter.TOOLS / "converter.json"
    config = read_json(config_path) if config_path.is_file() else {}
    return hashlib.sha256(json.dumps([PREPARE_VERSION, item.get("bidNtceOrd"),
                                     sorted(inputs), config], sort_keys=True).encode()).hexdigest()


def _restore_rfp_cache(fingerprint, rows, folder, cached):
    if not cached.get("cached"):
        return False, cached
    state = cached.get("result")
    if not isinstance(state, dict) or state.get("schema") != 1 or state.get("fingerprint") != fingerprint:
        return False, {"status": "miss", "cached": False}
    originals = {row["url"]: row["local_path"] for row in rows
                 if row.get("url") and row.get("local_path") and Path(row["local_path"]).is_file()}
    paths = dict(originals)
    conversions = folder / "conversions.jsonl"
    if conversions.is_file():
        for record in read_jsonl(conversions):
            pdf = Path(record.get("pdf_path") or "__missing__")
            if (record.get("status") in ("converted", "existing") and pdf.is_file()
                    and record.get("pdf_sha256") == converter.sha256(pdf)):
                for row in rows:
                    if row.get("local_path") == record.get("original_path"):
                        paths[row["url"]] = str(pdf)
    for row in rows:
        if (str(row.get("selected")).lower() == "true" and row.get("status") in DOWNLOAD_SUCCESS
                and Path(row["local_path"]).suffix.lower() in HWP_SUFFIXES
                and (paths.get(row["url"]) == row["local_path"]
                     or not Path(paths.get(row["url"], "")).is_file())):
            return False, {"status": "miss", "cached": False}
    documents = state.get("documents")
    chunks = state.get("chunks")
    if not isinstance(documents, list) or not documents or not isinstance(chunks, list):
        return False, {"status": "miss", "cached": False}
    for records in (documents, chunks, state.get("pages", []), state.get("needs_attention", [])):
        if not isinstance(records, list):
            return False, {"status": "miss", "cached": False}
        for record in records:
            url = record.get("source_url")
            if url not in paths:
                return False, {"status": "miss", "cached": False}
            record["local_path"] = paths[url]
            record["original_local_path"] = originals[url]
    output = folder / "processed"
    output.mkdir(exist_ok=True)
    for name in ("pages", "chunks", "documents", "needs_attention"):
        write_jsonl(output / f"{name}.jsonl", state.get(name, []))
    return True, {"status": "reused", "cached": True}


def _save_rfp_cache(bid_no, revision, fingerprint, folder):
    state = {"schema": 1, "fingerprint": fingerprint}
    for name in ("pages", "chunks", "documents", "needs_attention"):
        path = folder / "processed" / f"{name}.jsonl"
        state[name] = read_jsonl(path) if path.is_file() else []
    if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > 5 * 1024 * 1024:
        return {"status": "skipped", "reason": "문서 캐시 크기 제한 초과"}
    return cache_api.save_rfp(bid_no, revision, state)


def _process_bid(item, full, store, progress):
    with BackendStore(item["bidNtceNo"], item.get("bidNtceOrd") or "000") as backend:
        result = _process_bid_local(item, full, store, progress, backend)
        result["preparation_status"] = "ready" if result.get("indexed_chunks", 0) else "failed"
        result["db_sync"] = backend.report
        if backend.errors:
            result["db_sync"]["message"] = "공고문 준비 결과는 유지했습니다. DB 인증·연결 설정을 확인한 뒤 DB 저장만 다시 시도하세요."
        return result


def _retry_db_save(item):
    """기존 로컬 원본·변환본·전처리 결과만 Java 저장소에 다시 적재한다."""
    bid_no, order = str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000")
    folder = root_dir() / "documents" / collector.safe_name(f"{bid_no}_{order}")
    manifest = folder / "attachments.csv"
    if not manifest.is_file():
        return {"status": "failed", "preparation_status": "unknown", "indexed_chunks": 0,
                "db_sync": {"status": "failed", "errors": ["로컬 첨부 목록을 찾을 수 없습니다."], "files": []}}
    rows = read_csv(manifest)
    with BackendStore(bid_no, order) as backend:
        for row in rows:
            if str(row.get("selected")).lower() != "true" or row.get("status") not in DOWNLOAD_SUCCESS:
                continue
            path = Path(row.get("local_path") or "__missing__")
            if path.is_file() and path.stat().st_size:
                backend.put("original", _source_identity(item, row), row["file_name"],
                            path.read_bytes(), row["url"])
            else:
                backend.errors.append("DB 재시도용 로컬 원본이 없습니다. 전체 첨부 준비를 다시 실행하세요.")
                backend.files.append({"file_name": row["file_name"], "kind": "original", "status": "failed"})
        _converted_files(backend, folder, rows, item)
        backend.save_prepared(folder)
        documents_path = folder / "processed" / "documents.jsonl"
        documents = read_jsonl(documents_path) if documents_path.is_file() else []
        chunks_path = folder / "processed" / "chunks.jsonl"
        chunks = read_jsonl(chunks_path) if chunks_path.is_file() else []
        ready = bool(chunks) and any(doc.get("status") in TEXT_READY for doc in documents)
        rfp_cache = {"status": "not_needed", "cached": False}
        has_rfp = any(str(row.get("selected")).lower() == "true"
                       and "rfp" in classify_attachment(row.get("file_name", ""))
                       for row in rows)
        fingerprint = _rfp_fingerprint(item, rows) if ready and has_rfp else None
        if fingerprint and not backend.auth_failed:
            existing = cache_api.lookup_rfp(bid_no, order)
            if existing.get("cached") and isinstance(existing.get("result"), dict) \
                    and existing["result"].get("fingerprint") == fingerprint:
                rfp_cache = {"status": "reused", "cached": True}
            elif existing.get("auth_failed"):
                rfp_cache = existing
            else:
                rfp_cache = _save_rfp_cache(bid_no, order, fingerprint, folder)
        elif backend.auth_failed:
            rfp_cache = {"status": "failed", "auth_failed": True,
                         "error": "DB 인증 실패가 확인되어 제안요청서 캐시 재시도를 생략했습니다."}
        report = backend.report
    return {"status": "completed" if report["status"] in ("saved", "not_needed") else "partial_failed",
            "preparation_status": "ready" if ready else "failed", "indexed_chunks": len(chunks),
            "db_sync": report, "rfp_cache": rfp_cache,
            "error": None if ready else "로컬 전처리 결과가 없어 DB만 재시도할 수 없습니다. 전체 첨부 준비가 필요합니다."}


def _process_bid_local(item, full, store, progress, backend):
    item = collector.resolve_standard_notice(item)
    bid_no = str(item["bidNtceNo"])
    order = str(item.get("bidNtceOrd") or "000")
    folder = root_dir() / "documents" / collector.safe_name(f"{bid_no}_{order}")
    progress("waiting_document")
    with directory_lock(folder, ".document.lock", timeout=180):
        progress("downloading")
        notice_url = _notice_url(item)
        if not full and notice_url is None:
            raise ValueError("공고문 첨부를 식별하지 못했습니다. 다른 첨부로 대체하지 않습니다.")
        manifest = folder / "attachments.csv"
        previous = {r["url"]: r for r in read_csv(manifest)} if manifest.exists() else {}
        rows = _attachment_rows(item, notice_url, full, previous)
        if not rows:
            raise ValueError("API가 제공한 첨부가 없습니다.")
        has_rfp = full and any(str(row.get("selected")).lower() == "true"
                               and "rfp" in classify_attachment(row.get("file_name", ""))
                               for row in rows)
        cache_state = cache_api.lookup_rfp(bid_no, order) if has_rfp else {
            "status": "not_requested", "cached": False}
        if cache_state.get("auth_failed"):
            # 같은 내부 키로 이어지는 문서 API 호출을 반복하지 않는다.
            backend._error("DB 제안요청서 캐시 인증 실패", 401)
        for row in rows:
            if row["selected"]:
                old = previous.get(row["url"], {})
                target = folder / "raw" / collector.safe_name(f"{bid_no}_{order}") / row["storage_name"]
                if not (old.get("status") in DOWNLOAD_SUCCESS and Path(old.get("local_path") or "__missing__").is_file()):
                    progress("restoring_database")
                    if backend.restore('original', _source_identity(item, row), target,
                                       legacy_name=row["file_name"], source_url=row["url"]):
                        old = {**row, "status": "existing", "local_path": str(target)}
                progress("downloading")
                _download_record(folder, row, old)
                write_csv(manifest, ATTACHMENT_FIELDS, rows)
                if row["status"] in DOWNLOAD_SUCCESS:
                    progress("saving_database")
                    backend.put('original', _source_identity(item, row), row["file_name"],
                                Path(row["local_path"]).read_bytes(), row["url"])
        write_json(folder / "candidates.json", {"items": [item]})
        published = previous and (folder / "bids.csv").exists()
        collected_at = read_csv(folder / "bids.csv")[0]["collected_at"] if published else stamp()
        write_csv(folder / "bids.csv", BID_FIELDS, [collector.notice_row(item, [], collected_at)])
        progress("restoring_database")
        _converted_files(backend, folder, rows, item, restore=True)
        fingerprint = _rfp_fingerprint(item, rows) if full else None
        restored = False
        if full and fingerprint:
            if backend.auth_failed and not cache_state.get("cached") and not cache_state.get("auth_failed"):
                cache_state = {"status": "failed", "cached": False, "auth_failed": True,
                               "error": "DB 문서 인증 실패가 확인되어 제안요청서 캐시 조회를 생략했습니다."}
            else:
                restored, cache_state = _restore_rfp_cache(fingerprint, rows, folder, cache_state)
        if not restored:
            progress("converting")
            try:
                _prepare_selected(folder, rows, full=full, backend=backend)
            except Exception as exc:
                # 변환 실패여도 이미 끝난 다운로드와 RFP 미적재 사실을 함께 전달한다.
                message = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
                return {"status": "failed", "error": "문서 준비 실패: " + message,
                        "indexed_chunks": 0, "rfp_cache": cache_state,
                        **_document_readiness(item, rows, [])}
        progress("saving_database")
        _converted_files(backend, folder, rows, item)
        backend.save_prepared(folder)
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
        failures += [f"{d['original_file_name']} ({d['status']}"
                     + (f": {d['error']}" if d.get("error") else "") + ")"
                     for d in documents if d["status"] not in TEXT_READY]
        if not records:
            failures.append("적재 가능한 공고문/제안요청서 텍스트가 없습니다.")
        readiness = _document_readiness(item, rows, records, documents)
        if full and fingerprint and not restored and readiness["rfp_ready"] and not cache_state.get("auth_failed"):
            cache_state = _save_rfp_cache(bid_no, order, fingerprint, folder)
        if full and readiness["attachment_lookup_status"] == "unavailable":
            failures.append(item.get("eorder_lookup_error") or "제안요청정보 첨부 조회 실패")
        if full and not readiness["rfp_ready"]:
            failures.append("파일첨부·제안요청정보에 식별 가능한 제안요청서류가 없습니다. 공고 상세 첨부를 확인하세요."
                            if readiness["rfp_status"] == "not_listed" else
                            "제안요청정보 첨부 목록을 확인하지 못했습니다. 조회 상태를 확인한 뒤 다시 시도하세요."
                            if readiness["rfp_status"] in {"lookup_failed", "not_checked"} else
                            "제안요청서류가 아직 변환·텍스트 적재되지 않았습니다.")
        return {"status": "partial_failed" if failures and records else "failed" if failures else "completed",
                "error": "확인 필요: " + ", ".join(dict.fromkeys(failures)) if failures else None,
                **readiness, "indexed_chunks": len(records), "rfp_cache": cache_state}


def run_job(job_id, key=None):
    job = get_job(job_id)
    path = root_dir() / "jobs" / f"{job_id}.json"
    job["status"] = "running"
    write_json(path, job)
    try:
        items = select_items(job["search_id"], job["bids"], check_deadline=job["mode"] != "db_retry")
        store = None if job["mode"] == "db_retry" else KnowledgeStore("pdf")
        for position, item in enumerate(items):
            bid = job["bids"][position]

            def progress(status):
                bid["status"] = status
                write_json(path, job)

            try:
                if job["mode"] == "db_retry":
                    bid.update(status="saving_database", preparation_status="ready")
                    write_json(path, job)
                    bid.update(_retry_db_save(item))
                    job["done"] += 1
                    write_json(path, job)
                    continue
                if job["mode"] == "documents" or (job["mode"] == "notices" and key):
                    # 전체 검색을 재실행하지 않고 선택된 공고번호만 조회한다.
                    progress("checking_attachments")
                    current = collector.lookup_notice(key, bid["bid_no"])
                    latest_order = str(current.get("bidNtceOrd") or "000")
                    if int(latest_order) < int(bid["bid_order"]):
                        raise ValueError("저장된 공고보다 이전 차수가 반환돼 다운로드를 중단했습니다.")
                    bid["requested_bid_order"] = bid["bid_order"]
                    bid["revision_changed"] = latest_order != bid["bid_order"]
                    bid["bid_order"] = latest_order
                    # 같은 차수도 첨부 링크가 보완될 수 있으므로 재조회한 목록을 사용한다.
                    # 개찰·재입찰 조회는 검색 전체가 아니라 사용자가 선택한 공고에만 한다.
                    progress("checking_bid_progress")
                    progress_key = os.environ.get("DATA_GO_KR_SCSBID_SERVICE_KEY", "").strip()
                    try:
                        evidence = bid_progress.lookup_progress(progress_key, bid["bid_no"], latest_order)
                        checked = bid_progress.apply_progress({**current, "bid_progress": evidence})
                        state = checked["bid_progress"]
                        progress_status = "unknown" if state["state"] == "unknown" else "checked"
                        bid["progress_check"] = {"status": progress_status, "state": state["state"],
                                                  "label": state["label"], "reason": state.get("reason"),
                                                  "deadline": checked.get("bidClseDt")}
                        if evidence.get("lookup_status") == "complete" and state["state"] == "closed":
                            bid.update(status="failed", preparation_status="not_started",
                                       error="현재 접수 중인 입찰이 확인되지 않아 공고문 준비를 중단했습니다. "
                                             + (state.get("reason") or "개찰·재입찰 상태를 확인하세요."))
                            job["done"] += 1
                            write_json(path, job)
                            continue
                        if state["state"] == "unknown" and job["mode"] == "documents":
                            bid.update(status="failed", preparation_status="not_started",
                                       error="재입찰 진행 상태를 확정하지 못해 전체 첨부 다운로드를 중단했습니다. "
                                             "공식 공고의 현재 일정을 확인한 뒤 다시 시도하세요.")
                            job["done"] += 1
                            write_json(path, job)
                            continue
                        current = checked
                    except collector.CollectionError as exc:
                        # 조회 실패는 마감으로 단정하지 않는다. 전체 첨부 다운로드는 막고 확인 필요로 남긴다.
                        bid["progress_check"] = {"status": "unknown", "state": "unknown",
                                                  "label": "입찰 진행 상태 확인 필요", "reason": str(exc)}
                        if job["mode"] == "documents":
                            bid.update(status="failed", preparation_status="not_started",
                                       error="입찰 진행 상태를 확인하지 못해 전체 첨부 다운로드를 중단했습니다. "
                                             "API 키와 조회 상태를 확인한 뒤 다시 시도하세요.")
                            job["done"] += 1
                            write_json(path, job)
                            continue
                    if job["mode"] == "documents":
                        item = _enrich_eorder(current, key)
                    else:
                        # 같은 차수의 e발주 조회 결과는 유지하되 일반 첨부는 최신 응답을 쓴다.
                        extra = {field: item[field] for field in (
                            "eorder_attachments", "eorder_lookup_status", "eorder_lookup_error")
                            if field in item} if not bid["revision_changed"] else {}
                        item = {**current, **extra}
                    folder = root_dir() / job["search_id"]
                    write_json(folder / f"revision-{collector.safe_name(bid['bid_no'])}-{latest_order}.json", item)
                bid.update(_process_bid(item, job["mode"] == "documents", store, progress))
            except Exception as exc:
                # SDK/네트워크 예외 원문은 인증키나 연락처를 포함할 수 있다.
                message = str(exc) if isinstance(exc, (collector.CollectionError, ValueError, RuntimeError)) else type(exc).__name__
                bid.update(status="failed", error=message)
                if job["mode"] == "db_retry":
                    bid.setdefault("preparation_status", "ready")
                    bid["db_sync"] = {"status": "failed", "errors": ["DB 저장 재시도 중 로컬 결과 확인에 실패했습니다."],
                                      "files": [], "auth_failed": False}
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
    ACTIVE_JOBS.discard(job_id)
