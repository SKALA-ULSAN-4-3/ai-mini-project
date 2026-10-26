"""검색어·기간으로 공고 목록 수집 → 최신 등록 공고의 첨부 다운로드.

Python 표준 라이브러리만 사용한다. 참가자격 판정·변환·RAG는 수행하지 않는다.
"""
import argparse
import csv
from datetime import date, datetime, timedelta
from email.message import Message
import json
import os
from pathlib import Path
import re
import sys
import time as clock
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_env import load_env

API_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServcPPSSrch"
KST = ZoneInfo("Asia/Seoul")
MAX_FILE_BYTES = 50 * 1024 * 1024
BID_FIELDS = ["bid_no", "bid_order", "title", "agency", "published_at", "deadline",
              "estimated_price", "allocated_budget", "detail_url", "search_keywords",
              "collected_at", "downloaded_files", "failed_files"]
CANDIDATE_FIELDS = BID_FIELDS + ["selected", "selection_reason"]
FILE_FIELDS = ["bid_no", "bid_order", "file_name", "url", "selected", "status", "local_path", "error"]


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
        seen.add(url)
        yield "standard_notice", url
    # 제안요청정보(e발주)는 일반 파일첨부의 ntceSpecDocUrl1~10과 별도 제공된다.
    for attachment in item.get("eorder_attachments", []):
        if (attachment.get("bid_no"), attachment.get("bid_order")) != (
                str(item["bidNtceNo"]), str(item.get("bidNtceOrd") or "000")):
            continue
        url = str(attachment.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            yield attachment["file_name"], url


def lookup_eorder_attachments(key, bid_no, bid_order):
    """공식 e발주 첨부 API에서 동일 공고·차수의 제안요청서·협약문서 등을 조회한다."""
    if not key:
        raise CollectionError("제안요청정보 첨부 조회에 필요한 API 키가 없습니다.")
    url = API_URL.rsplit("/", 1)[0] + "/getBidPblancListInfoEorderAtchFileInfo"
    found = []
    seen = set()
    for page in range(1, 21):
        params = {"serviceKey": unquote(key), "type": "json", "inqryDiv": "2",
                  "bidNtceNo": bid_no, "bidNtceOrd": bid_order, "pageNo": page, "numOfRows": 100}
        request = Request(url + "?" + urlencode(params), headers={"User-Agent": "BidCollector/1.0"})
        try:
            with build_opener().open(request, timeout=20) as response:
                items, total = parse_response(response.read(10 * 1024 * 1024))
        except HTTPError as exc:
            raise CollectionError(f"제안요청정보 첨부 조회 HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise CollectionError("제안요청정보 첨부 조회 연결 실패") from None
        for item in items:
            if str(item.get("bidNtceNo") or "") != str(bid_no):
                continue
            if not item.get("bidNtceOrd"):
                raise CollectionError("제안요청정보 첨부의 공고 차수를 확인할 수 없습니다.")
            if str(item["bidNtceOrd"]) != str(bid_order):
                continue
            file_url = str(item.get("eorderAtchFileUrl") or "").strip()
            if not file_url or file_url in seen:
                continue
            if not allowed_download(file_url):
                raise CollectionError("제안요청정보 첨부가 공식 다운로드 주소가 아닙니다.")
            name = str(item.get("eorderAtchFileNm") or "").strip()
            if not name:
                name = attachment_header_name(file_url)
            seen.add(file_url)
            found.append({"bid_no": str(bid_no), "bid_order": str(bid_order),
                          "file_name": name, "url": file_url,
                          "document_type": str(item.get("eorderDocDivNm") or ""), "source": "eorder"})
        if not items or page * 100 >= total:
            return found
    raise CollectionError("제안요청정보 첨부 조회 한도를 넘었습니다. 전체 목록 확인이 필요합니다.")


def attachment_header_name(url):
    """API 파일명 누락만 다운로드 헤더로 보완한다. 파일 본문은 읽거나 저장하지 않는다."""
    if not allowed_download(url):
        raise CollectionError("제안요청정보 첨부가 공식 다운로드 주소가 아닙니다.")
    request = Request(url, headers={"User-Agent": "BidCollector/1.0", "Range": "bytes=0-0"})
    try:
        # 공식 다운로드 서버는 HEAD를 403으로 거부하므로 GET의 헤더만 읽고 닫는다.
        with build_opener(OfficialRedirect()).open(request, timeout=20) as response:
            if response.headers.get_content_type() in ("text/html", "application/json"):
                raise CollectionError("제안요청정보 첨부 대신 안내/오류 페이지가 반환됐습니다.")
            header = Message()
            header["Content-Disposition"] = response.headers.get("Content-Disposition", "")
            name = unquote(header.get_filename() or "").strip()
    except HTTPError as exc:
        raise CollectionError(f"제안요청정보 첨부 파일명 조회 HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise CollectionError("제안요청정보 첨부 파일명 조회 연결 실패") from None
    if (not name or name in (".", "..") or re.search(r'[\x00-\x1f/\\]', name)):
        raise CollectionError("제안요청정보 첨부의 파일명을 확인할 수 없습니다.")
    return name


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


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def deadline_in_period(item, start, end):
    """API 입찰마감일의 서울 날짜를 비교한다. 미확인 날짜는 게시일로 대체하지 않는다."""
    raw = str(item.get("bidClseDt") or "").strip()
    try:
        deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if deadline.tzinfo is not None:
            deadline = deadline.astimezone(KST)
        return start <= deadline.date() <= end
    except ValueError:
        return False


def search_candidates(key, start_date, end_date, queries, limit, *, deadline_period=None, candidate_transform=None):
    """검색어와 공고일 기간으로 API 후보 목록을 수집한다."""
    found = {}
    truncated = False
    windows = []
    start = start_date
    while start <= end_date:
        end = min(start + timedelta(days=6), end_date)
        windows.append((start, end))
        start = end + timedelta(days=1)
    if deadline_period is not None:
        windows.reverse()  # 실시간 마감일 검색은 최근 게시된 공고부터 탐색한다.
    for start, end in windows:
        if len(found) >= limit:
            break
        for query in queries:
            for page in range(1, 21):
                print(f"후보 수집: {start}~{end}, 요청 검색어 {query}, {page}페이지", flush=True)
                items, total = fetch_page(key, start, end, query, page)
                for item in items:
                    if candidate_transform is not None:
                        item = candidate_transform(item)
                        if item is None:
                            continue
                    if deadline_period is not None and not deadline_in_period(item, *deadline_period):
                        continue
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
    return list(found.values()), truncated


def lookup_notice(key, bid_no):
    """선택한 용역 공고번호 하나만 재조회한다. 목록 키워드 검색은 수행하지 않는다."""
    if not key:
        raise CollectionError("공고 차수 재확인에 필요한 API 키가 없습니다.")
    url = API_URL.replace("getBidPblancListInfoServcPPSSrch", "getBidPblancListInfoServc")
    found = []
    for page in range(1, 21):
        params = {"serviceKey": unquote(key), "type": "json", "inqryDiv": "2",
                  "bidNtceNo": bid_no, "pageNo": page, "numOfRows": 100}
        request = Request(url + "?" + urlencode(params), headers={"User-Agent": "BidCollector/1.0"})
        try:
            with build_opener().open(request, timeout=30) as response:
                items, total = parse_response(response.read(10 * 1024 * 1024))
        except HTTPError as exc:
            raise CollectionError(f"공고 차수 확인 HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise CollectionError("공고 차수 확인 연결 실패") from None
        found.extend(item for item in items if str(item.get("bidNtceNo")) == bid_no)
        if not items or page * 100 >= total:
            break
    else:
        raise CollectionError("공고 차수 조회 한도를 넘어 최신 차수를 확인하지 못했습니다.")
    if not found:
        raise CollectionError("선택 공고의 현재 차수를 확인하지 못했습니다.")
    if any(not re.fullmatch(r"\d{3}", str(item.get("bidNtceOrd") or "000")) for item in found):
        raise CollectionError("공고 차수 형식이 예상과 다릅니다.")
    latest = max(found, key=lambda item: int(item.get("bidNtceOrd") or "000"))
    if any(word in str(latest.get("ntceKindNm", "")) for word in ("취소", "철회")):
        raise CollectionError("선택 공고가 취소·철회되었습니다.")
    return latest


def notice_row(item, words, collected_at):
    return dict(bid_no=str(item["bidNtceNo"]), bid_order=str(item.get("bidNtceOrd") or "000"),
                title=item.get("bidNtceNm", ""), agency=item.get("dminsttNm") or item.get("ntceInsttNm", ""),
                published_at=item.get("bidNtceDt", ""), deadline=item.get("bidClseDt", ""),
                estimated_price=item.get("presmptPrce", ""), allocated_budget=item.get("asignBdgtAmt", ""),
                detail_url=item.get("bidNtceDtlUrl") or item.get("bidNtceUrl", ""),
                search_keywords="|".join(words), collected_at=collected_at, downloaded_files=0, failed_files=0)


def collect(args):
    if args.resume:
        run_dir = args.resume.resolve()
        saved = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
        items, request = saved["items"], saved["request"]
        print(f"기존 후보로 선별·다운로드: {run_dir}", flush=True)
    else:
        load_env()
        key = os.getenv("DATA_GO_KR_SERVICE_KEY", "").strip()
        if not key:
            raise CollectionError("루트 .env에 DATA_GO_KR_SERVICE_KEY를 설정하세요.")
        if args.start > args.end or args.limit < 1:
            raise CollectionError("조회 기간과 후보 수집 개수를 확인하세요.")
        queries = list(dict.fromkeys(q.strip() for q in args.query))
        if not all(queries):
            raise CollectionError("요청 검색어는 비워 둘 수 없습니다.")
        items, truncated = search_candidates(key, args.start, args.end, queries, args.limit)
        request = dict(start=str(args.start), end=str(args.end), queries=queries, candidate_limit=args.limit,
                       collected_at=datetime.now(KST).isoformat(), page_limit_reached=truncated)
        run_dir = args.output.resolve() / datetime.now(KST).strftime("%Y%m%d_%H%M%S_%f")
        run_dir.mkdir(parents=True)
        (run_dir / "candidates.json").write_text(
            json.dumps(dict(request=request, items=items), ensure_ascii=False, indent=2), encoding="utf-8")

    previous = {}
    if (run_dir / "attachments.csv").exists():
        with (run_dir / "attachments.csv").open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                previous[(row["bid_no"], row["bid_order"], row["url"])] = row
    latest = {}
    for item in items:
        no = str(item["bidNtceNo"])
        if no not in latest or int(item.get("bidNtceOrd") or 0) > int(latest[no].get("bidNtceOrd") or 0):
            latest[no] = item
    candidates, files, targets = [], [], {}
    for item in items:
        active = latest[str(item["bidNtceNo"])] is item and not any(w in str(item.get("ntceKindNm", "")) for w in ("취소", "철회"))
        words = request.get("queries", []) if active else []
        reason = "검색 요청에 따른 수집 대상" if active else "이전 차수 또는 취소·철회 공고"
        row = notice_row(item, words, request["collected_at"])
        row.update(selected=bool(words), selection_reason=reason)
        candidates.append(row)
        urls = list(attachments(item))
        if not urls:
            urls = [("", "")]
        for i, (filename, url) in enumerate(urls, 1):
            target = run_dir / "raw" / safe_name(row["bid_no"] + "_" + row["bid_order"]) / f"{i:02}_{safe_name(filename)}"
            targets[(row["bid_no"], row["bid_order"], url)] = target
            old = previous.get((row["bid_no"], row["bid_order"], url), {})
            cached = old.get("status") in ("downloaded", "existing") and old.get("local_path") == str(target) and target.is_file() and target.stat().st_size > 0
            status = "not_selected" if not words else ("listed" if url else "missing_url")
            if words and cached:
                status = "existing"
            files.append(dict(bid_no=row["bid_no"], bid_order=row["bid_order"], file_name=filename,
                              url=url, selected=bool(words), status=status,
                              local_path=str(target) if words and cached else "",
                              error="API 첨부 URL 없음: 원문 확인 필요" if words and not url else ""))

    def save_progress():
        for row in candidates:
            related = [f for f in files if (f["bid_no"], f["bid_order"]) == (row["bid_no"], row["bid_order"])]
            row["downloaded_files"] = sum(f["status"] in ("downloaded", "existing") for f in related)
            row["failed_files"] = sum(f["status"] in ("failed", "missing_url") for f in related)
        write_csv(run_dir / "candidates.csv", CANDIDATE_FIELDS, candidates)
        write_csv(run_dir / "bids.csv", BID_FIELDS,
                  [{k: row[k] for k in BID_FIELDS} for row in candidates if row["selected"]])
        write_csv(run_dir / "attachments.csv", FILE_FIELDS, files)
        summary = dict(candidates=len(candidates), selected=sum(r["selected"] for r in candidates),
                       excluded=sum(not r["selected"] for r in candidates),
                       downloaded=sum(f["status"] == "downloaded" for f in files),
                       existing=sum(f["status"] == "existing" for f in files),
                       pending=sum(f["status"] == "listed" for f in files),
                       failed=sum(f["status"] in ("failed", "missing_url") for f in files),
                       request=request, search_only=args.search_only,
                       selection="검색 요청과 수집 목록 내 최신 차수·취소 여부에 따른 자료 수집")
        (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    # 모든 후보·링크와 선별 사유를 저장한 후에 다운로드를 시작한다.
    summary = save_progress()
    print(f"후보 {summary['candidates']}건 → 수집 대상 {summary['selected']}건 → 제외 {summary['excluded']}건", flush=True)
    if not args.search_only:
        for row in files:
            if row["status"] != "listed":
                continue
            target = targets[(row["bid_no"], row["bid_order"], row["url"])]
            try:
                download_file(row["url"], target)
                row.update(status="downloaded", local_path=str(target))
                print(f"저장 완료: {target.name}", flush=True)
            except CollectionError as exc:
                row.update(status="failed", error=str(exc))
                print(f"다운로드 실패: {row['file_name']} ({exc})", flush=True)
            summary = save_progress()
    print(f"파일 신규 저장 {summary['downloaded']}개 / 기존 {summary['existing']}개 / 실패 {summary['failed']}개")
    print(f"수집 경로: {run_dir}")
    if request["page_limit_reached"]:
        print("페이지 제한에 도달했습니다. 조회 기간을 좁혀 다시 실행하세요.")
    return 2 if summary["failed"] else 0


def main():
    today = datetime.now(KST).date()
    parser = argparse.ArgumentParser(description="나라장터 용역 공고 후보 검색·첨부 저장")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=today - timedelta(days=6))
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=today)
    parser.add_argument("--query", action="append", help="사용자 요청 검색어. 여러 번 지정하면 OR 검색 (기본: 개발)")
    parser.add_argument("--limit", type=int, default=50, help="기업 선별 전 후보 수집 개수")
    parser.add_argument("--resume", type=Path, help="기존 실행 폴더의 후보를 재사용해 같은 폴더에 다운로드")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "collected")
    parser.add_argument("--search-only", action="store_true", help="링크와 목록만 확인하고 다운로드 생략")
    args = parser.parse_args()
    args.query = args.query or ["개발"]
    try:
        return collect(args)
    except (CollectionError, ValueError, OSError) as exc:
        # 인증키나 요청 URL이 포함된 네트워크 예외를 그대로 출력하지 않는다.
        if isinstance(exc, CollectionError):
            print(f"오류: {exc}", file=sys.stderr)
        else:
            print("오류: 입력값, 저장 경로를 확인하세요.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
