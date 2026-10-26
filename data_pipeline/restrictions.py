"""공식 참가가능지역·면허제한 상세 조회. 빈 목록·조회 실패·제한 없음을 구분한다."""
import re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request

from . import collect_bids as collector

OPERATIONS = {
    "region": "getBidPblancListInfoPrtcptPsblRgn",
    "industry": "getBidPblancListInfoLicenseLimit",
}


def lookup_rows(key, bid_no, bid_order, kind):
    if not key:
        raise collector.CollectionError("제한 상세 조회에 필요한 API 키가 없습니다.")
    url = collector.API_URL.rsplit("/", 1)[0] + "/" + OPERATIONS[kind]
    found = []
    for page in range(1, 21):
        params = {"serviceKey": unquote(key), "type": "json", "inqryDiv": "2",
                  "bidNtceNo": bid_no, "bidNtceOrd": bid_order, "pageNo": page, "numOfRows": 100}
        request = Request(url + "?" + urlencode(params), headers={"User-Agent": "BidCollector/1.0"})
        try:
            with collector.build_opener().open(request, timeout=20) as response:
                rows, total = collector.parse_response(response.read(10 * 1024 * 1024))
        except HTTPError as exc:
            raise collector.CollectionError(f"제한 상세 조회 HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise collector.CollectionError("제한 상세 조회 연결 실패") from None
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


def lookup_restrictions(item, key):
    bid_no, order = str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000")
    flag = str(item.get("indstrytyLmtYn") or "").strip().upper()
    result = {}
    for kind in OPERATIONS:
        name = "region_restriction" if kind == "region" else "industry_restriction"
        if kind == "industry" and flag == "N":
            result[name] = {**industry_details([], flag), "source": "indstrytyLmtYn=N"}
            continue
        try:
            rows = lookup_rows(key, bid_no, order, kind)
            result[name] = region_details(rows) if kind == "region" else industry_details(rows, flag)
        except collector.CollectionError as exc:
            result[name] = {"status": "unavailable", "lookup_status": "unavailable",
                            "source": OPERATIONS[kind], "error": str(exc)}
    return result
