"""공식 참가가능지역·면허제한 상세 조회. 빈 목록·조회 실패·제한 없음을 구분한다."""
from datetime import datetime, timezone
import hashlib
import logging
import re
import socket
import ssl
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request

from . import collect_bids as collector

OPERATIONS = {
    "region": "getBidPblancListInfoPrtcptPsblRgn",
    "industry": "getBidPblancListInfoLicenseLimit",
}
logger = logging.getLogger(__name__)
_slots = threading.BoundedSemaphore(2)
_gate = threading.Lock()
_next_request = 0.0
_blocked = {}


class RestrictionLookupError(collector.CollectionError):
    def __init__(self, code, message, *, retryable=False, http_status=None):
        super().__init__(message)
        self.code, self.retryable, self.http_status = code, retryable, http_status
        self.attempts = 0


def _failure(exc):
    if isinstance(exc, HTTPError):
        return RestrictionLookupError(f"http_{exc.code}", f"제한 상세 조회 HTTP {exc.code}",
                                      retryable=exc.code in (408, 429, 500, 502, 503, 504),
                                      http_status=exc.code)
    if isinstance(exc, (ValueError, TypeError, AttributeError)):
        return RestrictionLookupError("invalid_response", "제한 상세 응답 형식 확인 필요")
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return RestrictionLookupError("timeout", "제한 상세 조회 시간 초과", retryable=True)
    if isinstance(reason, socket.gaierror):
        return RestrictionLookupError("dns", "제한 상세 조회 DNS 확인 실패", retryable=True)
    if isinstance(reason, ssl.SSLError):
        return RestrictionLookupError("tls", "제한 상세 조회 TLS 연결 실패")
    if isinstance(exc, collector.CollectionError):
        match = re.search(r"API 오류 코드 ([A-Za-z0-9_-]+)", str(exc))
        code = match.group(1) if match else None
        return RestrictionLookupError(f"api_{code}" if code else "invalid_response",
                                      f"제한 상세 API 오류 코드 {code}" if code else "제한 상세 응답 형식 확인 필요",
                                      retryable=code in ("01", "02", "04", "05", "22"))
    return RestrictionLookupError("connection", "제한 상세 조회 연결 실패", retryable=True)


def _request_page(request, key, bid_no, bid_order, kind, deadline):
    global _next_request
    key_id = hashlib.sha256(unquote(key).encode()).hexdigest()
    for attempt in range(1, 3):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not _slots.acquire(timeout=max(0, remaining)):
            raise RestrictionLookupError("budget_exceeded", "제한 상세 조회 시간 예산 소진 — 재조회 필요", retryable=True)
        try:
            with _gate:
                blocked = _blocked.get(key_id)
                if blocked and blocked[0] > time.monotonic():
                    raise RestrictionLookupError(blocked[1], "제한 상세 API 인증·호출량 오류로 추가 요청을 잠시 중단했습니다.")
                if blocked:
                    _blocked.pop(key_id, None)
                wait = max(0, _next_request - time.monotonic())
                _next_request = time.monotonic() + wait + 0.15
            if wait:
                time.sleep(min(wait, max(0, deadline - time.monotonic())))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RestrictionLookupError("budget_exceeded", "제한 상세 조회 시간 예산 소진 — 재조회 필요", retryable=True)
            try:
                with collector.build_opener().open(request, timeout=min(20, remaining)) as response:
                    return collector.parse_response(response.read(10 * 1024 * 1024))
            except (HTTPError, URLError, TimeoutError, OSError, collector.CollectionError,
                    ValueError, TypeError, AttributeError) as exc:
                error = _failure(exc)
                error.attempts = attempt
                logger.warning("restriction_lookup bid=%s revision=%s kind=%s code=%s attempt=%s",
                               bid_no, bid_order, kind, error.code, attempt)
                if error.code in ("http_401", "http_403", "api_20", "api_21", "api_30", "api_31", "api_32"):
                    with _gate:
                        _blocked[key_id] = (time.monotonic() + 60, error.code)
                if attempt == 2 and error.code in ("http_429", "api_22"):
                    with _gate:
                        _blocked[key_id] = (time.monotonic() + 5, error.code)
                if not error.retryable or attempt == 2:
                    raise error from None
        finally:
            _slots.release()
        time.sleep(min(0.5 * attempt, max(0, deadline - time.monotonic())))


def lookup_rows(key, bid_no, bid_order, kind, deadline=None):
    if not key:
        raise collector.CollectionError("제한 상세 조회에 필요한 API 키가 없습니다.")
    url = collector.API_URL.rsplit("/", 1)[0] + "/" + OPERATIONS[kind]
    found = []
    deadline = min(deadline or float("inf"), time.monotonic() + 45)
    for page in range(1, 21):
        params = {"serviceKey": unquote(key), "type": "json", "inqryDiv": "2",
                  "bidNtceNo": bid_no, "bidNtceOrd": bid_order, "pageNo": page, "numOfRows": 100}
        request = Request(url + "?" + urlencode(params), headers={"User-Agent": "BidCollector/1.0"})
        rows, total = _request_page(request, key, bid_no, bid_order, kind, deadline)
        for row in rows:
            if str(row.get("bidNtceNo") or "") != bid_no:
                continue
            if not row.get("bidNtceOrd"):
                raise collector.CollectionError("제한 상세의 공고 차수를 확인할 수 없습니다.")
            if str(row["bidNtceOrd"]) == bid_order:
                found.append(row)
        if not rows or page * 100 >= total:
            return found
    raise collector.CollectionError("제한 상세 조회 한도를 넘어 전체 조건을 확인하지 못했습니다.")


def _license(value):
    value = str(value or "").strip()
    name, sep, code = value.rpartition("/")
    if sep and re.fullmatch(r"\d{4}", code.strip()):
        return {"name": name.strip(), "code": code.strip()}
    return {"name": value, "code": None}


def region_details(rows):
    values = list(dict.fromkeys(str(r.get("prtcptPsblRgnNm") or "").strip() for r in rows))
    values = [v for v in values if v]
    national = {"전국", "지역제한없음", "지역 제한 없음", "제한없음", "제한 없음"}
    status = ("none" if values and all(v in national for v in values) else
              "limited" if values and not any(v in national for v in values) else
              "not_listed" if not rows else "unknown")
    return {"status": status, "lookup_status": "complete", "values": values,
            "source": OPERATIONS["region"]}


def industry_details(rows, flag):
    requirements = []
    seen = set()
    for row in rows:
        raw = str(row.get("lcnsLmtNm") or "").strip()
        if not raw:
            continue
        identity = (str(row.get("lmtGrpNo") or ""), str(row.get("lmtSno") or ""), raw)
        if identity in seen:
            continue
        seen.add(identity)
        allowed_raw = str(row.get("permsnIndstrytyList") or "").strip()
        allowed = re.findall(r"\[([^\[\]]+)\]", allowed_raw)
        if allowed_raw and not allowed:
            allowed = [allowed_raw]
        requirements.append({**_license(raw), "group_no": identity[0], "sequence": identity[1],
                             "alternatives": [_license(v) for v in allowed],
                             "specialties": str(row.get("indstrytyMfrcFldList") or "").strip()})
    requirements.sort(key=lambda r: (r["group_no"].zfill(8), r["sequence"].zfill(8)))
    return {"status": "limited" if requirements else "none" if flag == "N" else
                      "unknown" if flag == "Y" or rows else "not_listed",
            "lookup_status": "complete", "requirements": requirements,
            "source": OPERATIONS["industry"]}


def lookup_restrictions(item, key, existing=None, deadline=None):
    bid_no, order = str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000")
    flag = str(item.get("indstrytyLmtYn") or "").strip().upper()
    result = {}
    for kind in OPERATIONS:
        name = "region_restriction" if kind == "region" else "industry_restriction"
        previous = (existing or {}).get(name)
        if isinstance(previous, dict) and previous.get("lookup_status") == "complete":
            result[name] = previous
            continue
        if kind == "industry" and flag == "N":
            result[name] = {**industry_details([], flag), "source": "indstrytyLmtYn=N"}
            continue
        try:
            rows = (lookup_rows(key, bid_no, order, kind) if deadline is None else
                    lookup_rows(key, bid_no, order, kind, deadline=deadline))
            result[name] = region_details(rows) if kind == "region" else industry_details(rows, flag)
        except collector.CollectionError as exc:
            result[name] = {"status": "unavailable", "lookup_status": "unavailable",
                            "source": OPERATIONS[kind], "error": str(exc),
                            "error_code": getattr(exc, "code", "lookup_failed"),
                            "http_status": getattr(exc, "http_status", None),
                            "retryable": getattr(exc, "retryable", False),
                            "attempts": getattr(exc, "attempts", 0)}
        result[name]["checked_at"] = datetime.now(timezone.utc).isoformat()
    return result
