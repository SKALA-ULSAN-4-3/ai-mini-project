"""나라장터 HTTP 통신·첨부 목록·공고 행 변환. 단계 제어는 bid_workflow가 맡는다."""
from datetime import timedelta
import json
import re
import time as clock
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ET

from .common import BID_FIELDS, CANDIDATE_FIELDS, FILE_FIELDS, write_csv

API_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
MAX_FILE_BYTES = 50 * 1024 * 1024


class CollectionError(Exception):
    pass


def parse_response(raw):
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        try:
            xml = ET.fromstring(raw)
            code = xml.findtext(".//returnReasonCode") or xml.findtext(".//resultCode")
            raise CollectionError(f"공공데이터 API 오류 코드 {code or '알 수 없음'}: 활용승인·인증키·호출 조건을 확인하세요.")
        except ET.ParseError:
            raise CollectionError("API가 JSON 대신 안내/오류 페이지를 반환했습니다.") from None
    response = payload.get("response", payload)
    header = response.get("header", {})
    if str(header.get("resultCode", "")) not in ("00", "0"):
        # 원본 오류 문구에는 인증키가 포함될 수 있으므로 코드만 표시한다.
        raise CollectionError(f"공공데이터 API 오류 코드 {header.get('resultCode', '없음')}: 활용승인·조회 조건을 확인하세요.")
    body = response.get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise CollectionError("API 공고 목록의 형식이 예상과 다릅니다.")
    return items, int(body.get("totalCount") or 0)


def fetch_page(key, start, end, keyword, page):
    params = {"serviceKey": unquote(key), "type": "json", "inqryDiv": "1",
              "inqryBgnDt": start.strftime("%Y%m%d") + "0000",
              "inqryEndDt": end.strftime("%Y%m%d") + "2359",
              "bidNtceNm": keyword, "pageNo": page, "numOfRows": 100}
    req = Request(API_URL + "?" + urlencode(params), headers={"User-Agent": "BidCollector/1.0"})
    try:
        with build_opener().open(req, timeout=30) as response:
            return parse_response(response.read(10 * 1024 * 1024))
    except HTTPError as exc:
        raise CollectionError(f"API HTTP {exc.code}: 인증키·활용승인·호출량을 확인하세요.") from None
    except (URLError, TimeoutError, OSError):
        raise CollectionError("API 연결 실패: 네트워크와 공공데이터포털 상태를 확인하세요.") from None


def attachments(item):
    seen = set()
    for i in range(1, 11):
        url = str(item.get(f"ntceSpecDocUrl{i}") or "").strip()
        if url and url not in seen:
            seen.add(url)
            yield str(item.get(f"ntceSpecFileNm{i}") or f"attachment_{i}"), url
    # 표준 공고문이 별도 URL로 제공되는 경우 함께 확보한다.
    url = str(item.get("stdNtceDocUrl") or "").strip()
    if url and url not in seen:
        yield "standard_notice", url


def safe_name(name):
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", name).strip(" .")
    return name[:160] or "attachment"


def allowed_download(url):
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme in ("http", "https") and not parsed.username and not parsed.password
            and any(host == domain or host.endswith("." + domain)
                    for domain in ("g2b.go.kr", "pps.go.kr")))


class OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_download(newurl):
            raise CollectionError("공식 도메인 외부로 이동하는 첨부 URL입니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_file(url, target):
    if not allowed_download(url):
        raise CollectionError("지원하지 않는 첨부 URL입니다. 공고 원문에서 확인하세요.")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        req = Request(url, headers={"User-Agent": "BidCollector/1.0"})
        with build_opener(OfficialRedirect()).open(req, timeout=40) as response:
            content_type = response.headers.get_content_type()
            if content_type in ("text/html", "application/json"):
                raise CollectionError("파일 대신 안내/오류 페이지가 반환됐습니다.")
            total = 0
            with partial.open("wb") as stream:
                while block := response.read(65536):
                    if total == 0 and re.search(br"<(?:!doctype\s+html|html)\b", block[:512], re.I):
                        raise CollectionError("파일 대신 HTML 안내 페이지가 반환됐습니다.")
                    total += len(block)
                    if total > MAX_FILE_BYTES:
                        raise CollectionError("첨부파일이 50MB 제한을 초과했습니다.")
                    stream.write(block)
        if not total:
            raise CollectionError("빈 첨부파일입니다.")
        partial.replace(target)
    except HTTPError as exc:
        raise CollectionError(f"첨부 다운로드 HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise CollectionError("첨부 다운로드 연결/저장 실패") from None
    finally:
        partial.unlink(missing_ok=True)


def search_candidates(key, start_date, end_date, queries, limit):
    """검색어와 공고일 기간으로 API 후보 목록을 수집한다."""
    found = {}
    truncated = False
    start = start_date
    while start <= end_date and len(found) < limit:
        end = min(start + timedelta(days=6), end_date)
        for query in queries:
            for page in range(1, 21):
                print(f"후보 수집: {start}~{end}, 요청 검색어 {query}, {page}페이지", flush=True)
                items, total = fetch_page(key, start, end, query, page)
                for item in items:
                    identity = (str(item.get("bidNtceNo") or ""), str(item.get("bidNtceOrd") or "000"))
                    if identity[0] and identity not in found:
                        found[identity] = item
                        if len(found) >= limit:
                            break
                if len(found) >= limit or not items or page * 100 >= total:
                    break
                if page == 20:
                    truncated = True
                clock.sleep(0.25)
            if len(found) >= limit:
                break
            clock.sleep(0.25)
        start = end + timedelta(days=1)
    return list(found.values()), truncated


def notice_row(item, words, collected_at):
    return dict(bid_no=str(item["bidNtceNo"]), bid_order=str(item.get("bidNtceOrd") or "000"),
                title=item.get("bidNtceNm", ""), agency=item.get("dminsttNm") or item.get("ntceInsttNm", ""),
                published_at=item.get("bidNtceDt", ""), deadline=item.get("bidClseDt", ""),
                estimated_price=item.get("presmptPrce", ""), allocated_budget=item.get("asignBdgtAmt", ""),
                detail_url=item.get("bidNtceDtlUrl") or item.get("bidNtceUrl", ""),
                search_keywords="|".join(words), collected_at=collected_at, downloaded_files=0, failed_files=0)
