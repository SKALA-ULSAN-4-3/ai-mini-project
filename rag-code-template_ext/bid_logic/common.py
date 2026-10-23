"""공고 식별자, 출처, 서울 시각과 숫자 처리 계약."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")


def identity(row):
    """차수의 선행 0을 보존한다. 공고번호와 차수는 문자열로 전달한다."""
    if not isinstance(row, dict):
        raise ValueError("공고와 출처는 객체여야 합니다.")
    if not isinstance(row.get("bid_no"), str) or not row["bid_no"].strip():
        raise ValueError("bid_no는 비어 있지 않은 문자열이어야 합니다.")
    if not isinstance(row.get("revision"), str) or not row["revision"].strip():
        raise ValueError("revision은 비어 있지 않은 문자열이어야 합니다.")
    return row["bid_no"].strip(), row["revision"].strip()


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError("숫자 정보가 없습니다.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("유효한 숫자가 아닙니다.") from None
    if not result.is_finite():
        raise ValueError("유한한 숫자가 필요합니다.")
    return result


def seoul_time(value):
    """시간대 없는 ISO 일시는 서울 시각. 날짜만 있는 마감은 해석하지 않는다."""
    if isinstance(value, str):
        if len(value.strip()) <= 10:
            raise ValueError("마감에는 시각까지 필요합니다.")
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError("ISO 일시가 필요합니다.")
    return (value.replace(tzinfo=SEOUL) if value.tzinfo is None else value).astimezone(SEOUL)


def calendar_date(value):
    if isinstance(value, datetime):
        return seoul_time(value).date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def check_scope(row, bid_no, revision):
    if identity(row) != (bid_no, revision):
        raise ValueError("다른 공고번호 또는 차수의 데이터가 섞였습니다.")
    sources = row.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("sources는 배열이어야 합니다.")
    for source in sources:
        if identity(source) != (bid_no, revision):
            raise ValueError("출처의 공고번호 또는 차수가 일치하지 않습니다.")


def require_sources(row):
    sources = row.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("원문 출처가 없습니다.")
    # 확인되지 않은 쪽수나 수집일을 보충하지 않는다.
    return sources


def deadline_info(due, now):
    if not due:
        return {"due": None, "d_day": None, "remaining_seconds": None, "status": "unknown"}
    try:
        parsed = seoul_time(due)
    except (ValueError, TypeError):
        return {"due": due, "d_day": None, "remaining_seconds": None, "status": "needs_review"}
    seconds = (parsed - now).total_seconds()
    return {"due": parsed.isoformat(), "d_day": (parsed.date() - now.date()).days,
            "remaining_seconds": max(0, seconds),
            "status": "expired" if seconds <= 0 else "upcoming"}
