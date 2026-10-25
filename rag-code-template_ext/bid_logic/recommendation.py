"""C2: 명백한 불일치만 제외하고 공고별 임베딩 거리로 정렬한다."""

import csv
from datetime import datetime
from pathlib import Path

from .common import SEOUL, RequestError, calendar_date, identity, number, region, seoul_time
from .notice_metadata import apply_notice_metadata, expired_deadline_reason

# []는 명시적으로 제한 없음, None은 미확인. 배열 원소는 OR, 필드 사이는 AND.
RESTRICTIONS = {
    "regions": ("region",),
    "industries": ("industry",),
    "licenses": ("licenses",),
    "company_sizes": ("company_size",),
    "certs": ("certs",),
}


def load_bids_csv(path):
    """CSV의 제한 필드는 JSON 배열 또는 null. 모호한 자연어 조건은 null로 전달.

    날짜는 빈 칸(미확인)이거나 정해진 형식이어야 한다. 형식이 다르면 공고가 조용히
    빠지지 않도록 적재 단계에서 실패시킨다.
    """
    import json
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        label = "/".join(identity(row))
        for field, parse, expected in (("published_at", calendar_date, "YYYY-MM-DD"),
                                       ("deadline", seoul_time, "YYYY-MM-DDTHH:MM(+09:00)")):
            raw = (row.get(field) or "").strip()
            if raw:
                try:
                    parse(raw)
                except ValueError:
                    raise ValueError(f"{label} {field}: {expected} 형식이 필요합니다: {raw!r}") from None
            row[field] = raw or None
        for field in RESTRICTIONS:
            raw = row.get(field)
            value = json.loads(raw) if raw and raw.strip() else None
            if value is not None and (not isinstance(value, list) or
                                      any(not isinstance(v, str) or not v.strip() for v in value)):
                raise ValueError(f"{field}: JSON 문자열 배열 또는 null이 필요합니다.")
            if value is not None and field == "regions":
                value = [region(v) for v in value]
            row[field] = value
        budget = number(row["budget"]) if row.get("budget") else None
        if budget is not None and budget < 0:
            raise ValueError("budget: 공고 금액은 음수일 수 없습니다.")
        row["budget"] = str(budget) if budget is not None else None
    return [apply_notice_metadata(row) for row in rows]


def profile_query(profile):
    keywords = profile.get("keywords") or []
    parts = [keywords] if isinstance(keywords, str) else list(keywords)
    for record in profile.get("track_records") or []:
        if record.get("summary"):
            parts.append(record["summary"])
    return " ".join(parts).strip()


def faiss_hits(vectorstore, query, allowed_keys):
    """기존 FAISS L2 거리 어댑터. 전체 청크를 읽어 필터 후보의 검색 누락을 막는다.

    생성형 LLM 호출 없음. query 임베딩 호출은 발생할 수 있다.
    20개 공고용이며, 대규모 데이터에서는 후보별 검색으로 교체한다.
    """
    if not query or not allowed_keys:
        return []
    if vectorstore is None:
        raise RuntimeError("공고 벡터 저장소가 준비되지 않았습니다.")
    count = int(vectorstore.index.ntotal)
    if count == 0:
        return []
    results = []
    for doc, distance in vectorstore.similarity_search_with_score(query, k=count):
        try:
            key = identity(doc.metadata)
        except ValueError:
            # 파일명뿐인 기존 인덱스. 요청 오류가 아니라 적재 데이터 문제다.
            raise RuntimeError("벡터 인덱스 청크에 bid_no·revision 메타데이터가 없습니다. "
                               "공고 PDF를 메타데이터와 함께 다시 적재해야 합니다.") from None
        if key in allowed_keys:
            results.append({"bid_no": key[0], "revision": key[1], "distance": float(distance)})
    return results


def _as_list(value):
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return [value.strip()]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise RequestError("프로필 조건 값은 문자열 또는 문자열 배열이어야 합니다.")
    return [v.strip() for v in value if v.strip()]


def _profile_conditions(profile):
    """프로필 제한 값을 한 번만 검증한다. 잘못된 값은 요청 오류(422)."""
    conditions = {}
    for profile_field, in RESTRICTIONS.values():
        owned = _as_list(profile.get(profile_field))
        if owned is not None and profile_field == "region":
            try:
                owned = [region(v) for v in owned]
            except ValueError as error:
                raise RequestError(f"프로필 region: {error}") from None
        conditions[profile_field] = owned
    return conditions


def recommend_bids(bids, profile, start, end, *, now=None, hits=None, search=None, limit=5):
    """search(query, allowed_keys)는 L2 거리 목록을 반환하는 주입 가능한 함수.

    후보별 최소 청크 거리(작을수록 유사) 사용. 동점은 공고번호·차수 문자열 순.
    거리 없는 후보는 마지막에 놓고 미확인으로 표시한다.
    """
    start, end = calendar_date(start), calendar_date(end)
    now = seoul_time(now or datetime.now(SEOUL))
    if start > end or limit < 1:
        raise RequestError("기간 또는 limit이 올바르지 않습니다.")
    lower, upper = profile.get("budget_min"), profile.get("budget_max")
    try:
        lower = number(lower) if lower is not None else None
        upper = number(upper) if upper is not None else None
    except ValueError as error:
        raise RequestError(f"희망 금액: {error}") from None
    if (lower is not None and lower < 0) or (upper is not None and upper < 0):
        raise RequestError("희망 금액은 음수일 수 없습니다.")
    if lower is not None and upper is not None and number(lower) > number(upper):
        raise RequestError("희망 금액 범위가 뒤집혔습니다.")
    conditions = _profile_conditions(profile)
    candidates, excluded, seen = [], [], set()
    for bid in bids:
        bid = apply_notice_metadata(bid)
        key = identity(bid)
        if key in seen:
            raise ValueError("동일 공고번호·차수의 메타데이터가 중복되었습니다.")
        seen.add(key)
        reasons, unknown = [], []
        try:
            if not start <= calendar_date(bid.get("published_at")) <= end:
                reasons.append("공고일이 선택 기간 밖입니다.")
        except (ValueError, TypeError):
            # 기간 포함 여부를 알 수 없으므로 결과에 섞지 않고 별도로 반환한다.
            excluded.append({"bid_no": key[0], "revision": key[1],
                             "status": "unknown", "reasons": ["공고일 미확인"]})
            continue
        try:
            if seoul_time(bid.get("deadline")) <= now:
                reasons.append(expired_deadline_reason(bid))
        except (ValueError, TypeError):
            unknown.append("입찰마감 일시 미확인")
        for field, (profile_field,) in RESTRICTIONS.items():
            restriction = bid.get(field)
            if restriction is None:
                unknown.append(f"{field} 제한 미확인")
                continue
            if not isinstance(restriction, list) or any(
                    not isinstance(v, str) or not v.strip() for v in restriction):
                raise ValueError(f"{field}는 비어 있지 않은 문자열 배열 또는 null이어야 합니다.")
            if not restriction:
                continue
            if field == "regions":
                restriction = [region(v) for v in restriction]
            owned = conditions[profile_field]
            if owned is None:
                unknown.append(f"프로필 {profile_field} 미확인")
            elif not set(owned).intersection(restriction):
                reasons.append(f"{field} 조건 불일치")
        try:
            budget = number(bid.get("budget"))
        except ValueError:
            # 금액을 읽을 수 없는 경우만 미확인이다. 음수 금액은 아래에서 거부한다.
            budget = None
            unknown.append("금액 비교 정보 미확인")
        if budget is not None:
            if budget < 0:
                raise ValueError("공고 금액이 음수입니다.")
            if lower is not None and budget < number(lower):
                reasons.append("희망 최소 금액 미만")
            if upper is not None and budget > number(upper):
                reasons.append("희망 최대 금액 초과")
        if reasons:
            excluded.append({"bid_no": key[0], "revision": key[1],
                             "status": "excluded", "reasons": reasons})
        else:
            candidates.append({**bid, "bid_no": key[0], "revision": key[1],
                               "unknown": unknown})
    if search is not None:
        if hits is not None:
            raise ValueError("hits와 search는 하나만 전달하세요.")
        hits = search(profile_query(profile), {identity(b) for b in candidates})
    distances = {}
    for hit in hits or []:
        key = identity(hit)
        distance = number(hit["distance"])
        if distance < 0:
            raise ValueError("L2 거리는 음수일 수 없습니다.")
        distances[key] = min(distances.get(key, distance), distance)
    for bid in candidates:
        distance = distances.get(identity(bid))
        if distance is None:
            bid["unknown"].append("임베딩 유사도 미확인")
        bid["distance"] = float(distance) if distance is not None else None
        bid["needs_review"] = True  # 추천은 참가자격 확정이 아니다.
        bid["reason"] = "명시된 규칙에서 불일치 없음" + (
            "; 공고별 최소 L2 거리 순" if distance is not None else "; 유사도 미확인")
    candidates.sort(key=lambda b: (b["distance"] is None, b["distance"] or 0, *identity(b)))
    return {"bids": candidates[:limit], "excluded": excluded,
            "candidate_count": len(candidates), "needs_review": True}
