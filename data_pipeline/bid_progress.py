"""공고·차수별 개찰결과와 재입찰 회차를 확인한다. 첨부·평가 로직은 다루지 않는다."""
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request

from . import collect_bids as collector

API_ROOT = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
OPERATIONS = ("getOpengResultListInfoServc", "getOpengResultListInfoRebid")
FIELDS = ("bidNtceNo", "bidNtceOrd", "bidClsfcNo", "rbidNo", "bidClseDt",
          "opengDt", "progrsDivCdNm", "opengRsltDivNm")


class ProgressRateLimitError(collector.CollectionError):
    """공통 조회 한도에 걸리면 공고마다 실패 요청을 반복하지 않는다."""


def lookup_rows(key, bid_no, bid_order, operation):
    if not key:
        raise collector.CollectionError("DATA_GO_KR_SCSBID_SERVICE_KEY가 설정되지 않았습니다.")
    found = []
    for page in range(1, 21):
        params = {"serviceKey": unquote(key), "type": "json", "bidNtceNo": bid_no,
                  "pageNo": page, "numOfRows": 100}
        if operation == OPERATIONS[0]:
            params["inqryDiv"] = "4"  # 낙찰정보서비스의 공고번호 조회 구분
        else:
            params["bidNtceOrd"] = bid_order
        request = Request(API_ROOT + "/" + operation + "?" + urlencode(params),
                          headers={"User-Agent": "BidCollector/1.0"})
        try:
            with collector.build_opener().open(request, timeout=20) as response:
                rows, total = collector.parse_response(response.read(10 * 1024 * 1024))
        except HTTPError as exc:
            if exc.code == 429:
                raise ProgressRateLimitError(
                    "개찰·재입찰 API 요청 한도를 초과했습니다(HTTP 429). "
                    "공고가 없는 것이 아니라 진행 상태를 확인하지 못한 상태입니다. "
                    "잠시 후 다시 검색하고, 반복되면 공공데이터포털의 낙찰정보서비스 호출 한도를 확인하세요."
                ) from None
            raise collector.CollectionError(f"개찰·재입찰 조회 HTTP {exc.code}: 낙찰정보서비스 활용승인을 확인하세요.") from None
        except (URLError, TimeoutError, OSError):
            raise collector.CollectionError("개찰·재입찰 조회 연결 실패") from None
        for row in rows:
            if str(row.get("bidNtceNo") or "") != bid_no:
                continue
            order = str(row.get("bidNtceOrd") or "")
            if not order:
                raise collector.CollectionError("개찰결과의 공고 차수를 확인할 수 없습니다.")
            if order.zfill(3) == bid_order.zfill(3):
                # 업체 정보·사업자번호·담당자 연락처는 저장하지 않는다.
                found.append({field: row.get(field) for field in FIELDS})
        if not rows or page * 100 >= total:
            return found
    raise collector.CollectionError("개찰·재입찰 조회 한도를 넘어 전체 회차를 확인하지 못했습니다.")


def lookup_progress(key, bid_no, bid_order):
    return {"lookup_status": "complete", "source": API_ROOT,
            "opening_results": lookup_rows(key, bid_no, bid_order, OPERATIONS[0]),
            "rebids": lookup_rows(key, bid_no, bid_order, OPERATIONS[1])}


def parse_time(value):
    text = str(value or "").strip()
    if " " not in text and "T" not in text:
        return None  # 날짜만으로 마감 시각을 만들지 않는다.
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=collector.KST) if parsed.tzinfo is None else parsed.astimezone(collector.KST)
    except ValueError:
        return None


def _round(row):
    raw = str(row.get("rbidNo") or "")
    return int(raw) if raw.isdigit() else -1


def apply_progress(item, now=None):
    """저장된 근거로 현재 시각을 다시 판정한다. 개찰 예정일은 실제 개찰 완료와 구분한다."""
    now = now or datetime.now(collector.KST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=collector.KST)
    result = dict(item)
    evidence = dict(item.get("bid_progress") or {})
    original_due = item.get("original_bidClseDt", item.get("bidClseDt"))
    result["bidClseDt"] = original_due
    no, order = str(item.get("bidNtceNo") or ""), str(item.get("bidNtceOrd") or "000")

    def scoped(rows):
        return [r for r in rows if str(r.get("bidNtceNo") or "") == no
                and str(r.get("bidNtceOrd") or "")
                and str(r.get("bidNtceOrd") or "").zfill(3) == order.zfill(3)]

    openings = scoped(evidence.get("opening_results", []))
    rebids = scoped(evidence.get("rebids", []))
    opening_completed = any(r.get("progrsDivCdNm") in ("개찰완료", "유찰") for r in openings)
    latest = {}
    for row in rebids:
        classification = str(row.get("bidClsfcNo") or "")
        if _round(row) >= 0 and (classification not in latest or _round(row) > _round(latest[classification])):
            latest[classification] = row
    active = []
    resolved_rounds = []
    for classification, row in latest.items():
        due, opening = parse_time(row.get("bidClseDt")), parse_time(row.get("opengDt"))
        closed_round = any(str(r.get("bidClsfcNo") or "") == classification
                           and _round(r) >= _round(row)
                           and r.get("progrsDivCdNm") in ("개찰완료", "유찰") for r in openings)
        resolved_rounds.append(closed_round or bool(due and due <= now))
        if due and due > now and (opening is None or opening > now) and not closed_round:
            active.append(row)
    if active and evidence.get("lookup_status") == "complete":
        # 공고 단위 추천이므로 접수 중인 분류 중 가장 가까운 마감으로 안내한다.
        current = min(active, key=lambda r: parse_time(r["bidClseDt"]))
        result.update(original_bidClseDt=original_due, bidClseDt=current["bidClseDt"])
        evidence.update(state="rebidding", label="재입찰 접수 중", recommendable=True,
                        bidClsfcNo=current.get("bidClsfcNo"), rbidNo=current["rbidNo"],
                        current_deadline=current["bidClseDt"], opening_confirmed=bool(openings))
    elif evidence.get("lookup_status") == "unavailable":
        evidence.update(state="unavailable", label="입찰진행정보 확인 실패", recommendable=False)
    elif latest and (len(resolved_rounds) != len(latest) or not all(resolved_rounds)):
        evidence.update(state="unknown", label="재입찰 일정 확인 필요", recommendable=False,
                        reason="재입찰 회차의 진행·마감 일정을 확정할 수 없습니다.")
    else:
        due, opening = parse_time(original_due), parse_time(item.get("opengDt"))
        if opening and opening <= now and not due and not opening_completed and not latest:
            evidence.update(state="unknown", label="개찰 결과 확인 필요", recommendable=False,
                            opening_confirmed=False,
                            reason="개찰 예정 시각이 지났지만 완료 결과와 마감일을 확인하지 못했습니다.")
            result["bid_progress"] = evidence
            return result
        closed = opening_completed or bool(due and due <= now) or bool(latest and all(resolved_rounds))
        evidence.update(state="closed" if closed else "open", label="마감" if closed else "입찰 상태 확인됨",
                        recommendable=not closed, opening_confirmed=opening_completed)
        if closed:
            evidence["reason"] = ("개찰이 완료됐고 현재 접수 중인 재입찰이 없습니다." if opening_completed else
                                  "재입찰 회차가 마감돼 현재 접수 중인 재입찰이 없습니다."
                                  if latest and all(resolved_rounds) else "입찰마감일시가 지났습니다.")
    result["bid_progress"] = evidence
    return result
