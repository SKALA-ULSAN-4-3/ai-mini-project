"""② 목록 기반 추리기: 공고문 적재 전, 1번 /search-bids 목록 정보만으로 거른다.

② 시점에는 아직 공고문이 없으므로 본문 거리를 쓰는 `recommend_bids`를 쓸 수 없다.
마감·금액·지역만 제외 규칙으로 쓰고, 공고명과 프로필 키워드의 유사도로 순위를 매긴다.
공고문이 적재된 ③' 시점에는 `recheck_after_ingest`가 기존 `recommend_bids`를 다시 돌린다.

외부 패키지를 import하지 않는다. 공고명 임베딩은 호출자가 주입한다
(1번 저장소와 같은 모델·정규화를 쓰려면 `knowledge_bridge.PipelineEmbeddings`).
"""

import re
import unicodedata
from datetime import datetime

from .common import SEOUL, REGION_NAMES, RequestError, calendar_date, identity, number, region, seoul_time
from .recommendation import _profile_conditions, profile_query, recommend_bids

# 1번 검색 응답은 정규화 이름과 나라장터 API 원문 이름이 섞여 올 수 있어 둘 다 받는다.
ALIASES = {
    "bid_no": ("bid_no", "bidNtceNo"),
    "revision": ("revision", "bid_order", "bidNtceOrd"),
    "title": ("title", "bidNtceNm"),
    "agency": ("agency", "dminsttNm", "ntceInsttNm"),
    "published_at": ("published_at", "bidNtceDt"),
    "deadline": ("deadline", "bidClseDt"),
}
# 배정예산을 먼저 본다 (1번 knowledge_bridge._budget과 같은 우선순위).
BUDGET_FIELDS = ("asignBdgtAmt", "allocated_budget", "presmptPrce", "estimated_price", "budget")
# 지역의무 공동계약 지역명에만 실제 지역 이름이 온다.
REGION_FIELDS = ("jntcontrctDutyRgnNm1", "jntcontrctDutyRgnNm2", "jntcontrctDutyRgnNm3")
# 지역 제한이 있다는 신호지만 어느 지역인지는 알려 주지 않는 필드.
REGION_BASIS_FIELD = "rgnLmtBidLocplcJdgmBssNm"
INDUSTRY_LIMIT_FIELD = "indstrytyLmtYn"
# API 원문에는 담당자 성명·연락처도 있다. 화면 목록에는 공고 정보만 내보낸다.
PUBLIC_LIST_FIELDS = {key for keys in ALIASES.values() for key in keys} | set(BUDGET_FIELDS) | set(
    REGION_FIELDS) | {REGION_BASIS_FIELD, INDUSTRY_LIMIT_FIELD, "regions", "attachments",
                     "cmmnSpldmdMethdNm", "cntrctCnclsMthdNm", "detail_url", "url",
                     "bidNtceDtlUrl", "bidNtceUrl", "filename", "file_names"}


def _pick(row, name):
    for key in ALIASES[name]:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, str):
            return str(value).strip()
    return None


def _text(value):
    return unicodedata.normalize("NFKC", value or "").casefold()


def _deadline(row):
    """`2026-10-15 18:00`·ISO 모두 받는다. 시각이 없으면 미확인(임의 시각을 만들지 않는다)."""
    raw = _pick(row, "deadline")
    if not raw:
        return None
    match = re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})[ T](\d{1,2}):(\d{2})"
                         r"((?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:\d{2})?", raw)
    if not match:
        return None
    try:
        return seoul_time(f"{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}"
                          f"T{int(match[4]):02d}:{match[5]}{match[6]}{match[7] or ''}")
    except ValueError:
        return None


def _budget(row):
    """쉼표·공백·원 표기만 떼고 숫자로 읽는다. 자유 텍스트에서 숫자를 긁어내지 않는다."""
    for field in BUDGET_FIELDS:
        raw = row.get(field)
        cleaned = re.sub(r"[,\s원]", "", str(raw if raw is not None else ""))
        if not cleaned:
            continue
        if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
            continue  # 읽을 수 없는 금액은 미확인으로 둔다
        value = number(cleaned)
        if value < 0:
            raise ValueError(f"{field}: 공고 금액은 음수일 수 없습니다.")
        return value
    return None


def _regions(row):
    """확정된 지역 이름만 돌려준다. (지역 목록, 제한 신호만 있고 지역 미상 여부)."""
    explicit = row.get("regions")
    if isinstance(explicit, list):
        return [region(v) for v in explicit], False
    names = []
    for field in REGION_FIELDS:
        raw = row.get(field)
        for part in re.split(r"\s*[/,]\s*", str(raw or "")):
            part = part.strip()
            if part in REGION_NAMES:
                names.append(region(part))
    hinted = bool(str(row.get(REGION_BASIS_FIELD) or "").strip())
    return list(dict.fromkeys(names)), (hinted and not names)


def _bigrams(text):
    squeezed = re.sub(r"\s+", "", text)
    return {squeezed[i:i + 2] for i in range(len(squeezed) - 1)} or ({squeezed} if squeezed else set())


def lexical_similarity(query, titles):
    """임베딩이 없을 때 쓰는 글자 2-gram Jaccard. 약한 신호이므로 순위 근거로만 쓴다.

    `시스템`이 `글림프시스템`에 걸리는 식의 오매칭을 막지 못한다.
    실제 운영에서는 공고명 임베딩을 주입해야 한다.
    """
    reference = _bigrams(_text(query))
    scores = []
    for title in titles:
        candidate = _bigrams(_text(title))
        union = reference | candidate
        scores.append(len(reference & candidate) / len(union) if union else 0.0)
    return scores


def shortlist_bids(rows, profile, *, now=None, limit=20, similarity=None, start=None, end=None):
    """1번 /search-bids 결과를 받아 상위 `limit`건을 고른다.

    제외 규칙은 마감 지남·희망 금액 범위 밖·지역 제한 불일치뿐이다.
    업종 제한(`indstrytyLmtYn = Y`)은 어떤 업종인지 목록에 없으므로 제외하지 않고 미확인으로 둔다.
    `similarity(query, titles)`는 **클수록 유사한** 점수 목록을 돌려주는 주입 함수다
    (`recommend_bids`의 L2 거리와 방향이 반대이므로 혼동하지 않는다).
    """
    now = seoul_time(now or datetime.now(SEOUL))
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
        raise RequestError("limit은 1~20 정수여야 합니다.")
    if (start is None) != (end is None):
        raise RequestError("공고 기간의 시작일과 종료일이 모두 필요합니다.")
    if start is not None:
        start, end = calendar_date(start), calendar_date(end)
        if start > end:
            raise RequestError("공고 기간이 뒤집혔습니다.")
    lower, upper = profile.get("budget_min"), profile.get("budget_max")
    try:
        lower = number(lower) if lower is not None else None
        upper = number(upper) if upper is not None else None
    except ValueError as error:
        raise RequestError(f"희망 금액: {error}") from None
    if (lower is not None and lower < 0) or (upper is not None and upper < 0):
        raise RequestError("희망 금액은 음수일 수 없습니다.")
    if lower is not None and upper is not None and lower > upper:
        raise RequestError("희망 금액 범위가 뒤집혔습니다.")
    owned_regions = _profile_conditions(profile)["region"]

    candidates, excluded, seen = [], [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("검색 결과 항목은 객체여야 합니다.")
        bid_no, revision = _pick(row, "bid_no"), _pick(row, "revision")
        if not bid_no or not revision:
            raise ValueError("검색 결과에 공고번호 또는 차수가 없습니다.")
        if (bid_no, revision) in seen:
            raise ValueError("동일 공고번호·차수가 검색 결과에 중복되었습니다.")
        seen.add((bid_no, revision))

        if start is not None:
            raw_date = _pick(row, "published_at") or ""
            try:
                # API 원문은 날짜 뒤에 시각을 포함한다. 날짜 부분을 서울 공고일로 사용한다.
                published = calendar_date(raw_date) if len(raw_date) == 10 else _deadline(
                    {"deadline": raw_date}).date()
            except (ValueError, TypeError, AttributeError):
                excluded.append({"bid_no": bid_no, "revision": revision,
                                 "status": "unknown", "reasons": ["공고일 미확인"]})
                continue
            if not start <= published <= end:
                excluded.append({"bid_no": bid_no, "revision": revision,
                                 "status": "excluded", "reasons": ["공고일이 선택 기간 밖입니다."]})
                continue

        reasons, unknown = [], []
        deadline = _deadline(row)
        if deadline is None:
            unknown.append("입찰마감 일시 미확인")
        elif deadline <= now:
            reasons.append("입찰이 마감되었습니다.")

        budget = _budget(row)
        if budget is None:
            unknown.append("금액 비교 정보 미확인")
        else:
            if lower is not None and budget < lower:
                reasons.append("희망 최소 금액 미만")
            if upper is not None and budget > upper:
                reasons.append("희망 최대 금액 초과")

        limited_regions, region_hinted = _regions(row)
        if region_hinted:
            # 제한이 있다는 것만 알고 어느 지역인지는 목록에 없다. 통과도 탈락도 아니다.
            unknown.append("지역 제한 대상 지역 미확인")
        elif limited_regions:
            if owned_regions is None:
                unknown.append("프로필 region 미확인")
            elif not set(owned_regions).intersection(limited_regions):
                reasons.append("지역 제한 조건 불일치")
        else:
            unknown.append("지역 제한 미확인")

        # 업종 제한은 목록에 업종 코드가 없어 맞는지 알 수 없다. 제외하지 않는다.
        if str(row.get(INDUSTRY_LIMIT_FIELD) or "").strip().upper() == "Y":
            unknown.append("업종 제한 있음, 대상 업종 미확인")
        else:
            unknown.append("업종 제한 미확인")

        entry = {**{key: value for key, value in row.items() if key in PUBLIC_LIST_FIELDS},
                 "bid_no": bid_no, "revision": revision,
                 "title": _pick(row, "title"), "agency": _pick(row, "agency"),
                 "published_at": _pick(row, "published_at"),
                 "deadline": deadline.isoformat() if deadline else None,
                 "budget": str(budget) if budget is not None else None,
                 "unknown": unknown}
        if reasons:
            excluded.append({"bid_no": bid_no, "revision": revision,
                             "status": "excluded", "reasons": reasons})
        else:
            candidates.append(entry)

    query = profile_query(profile)
    ranking_kind = "none"
    if candidates and query:
        titles = [bid["title"] or "" for bid in candidates]
        if similarity is not None:
            scores = similarity(query, titles)
            ranking_kind = "injected"
        else:
            scores = lexical_similarity(query, titles)
            ranking_kind = "lexical"
        if not isinstance(scores, (list, tuple)) or len(scores) != len(candidates):
            raise ValueError("유사도 함수는 후보 수와 같은 길이의 점수 목록을 돌려줘야 합니다.")
        for bid, score in zip(candidates, scores):
            value = number(score)  # 유한한 숫자만 받는다
            bid["score"] = float(value)
    else:
        if candidates and not query:
            # 키워드·실적 요약이 없으면 순위를 주장할 근거가 없다.
            for bid in candidates:
                bid["unknown"].append("프로필 키워드 미확인")
        for bid in candidates:
            bid["score"] = None

    for bid in candidates:
        bid["needs_review"] = True  # 목록 정보만으로는 참가자격을 확정할 수 없다.
        bid["reason"] = "목록 정보에서 제외 사유 없음" + (
            "; 공고명 유사도 순" if bid["score"] is not None else "; 유사도 미확인")
    # 유사도는 클수록 유사하므로 내림차순. 동점·미확인은 공고번호·차수 문자열 순.
    candidates.sort(key=lambda b: (b["score"] is None, -(b["score"] or 0), b["bid_no"], b["revision"]))
    return {"bids": candidates[:limit], "excluded": excluded,
            "candidate_count": len(candidates), "needs_review": True,
            "ranking_kind": ranking_kind, "stage": "list_only"}


def recheck_metadata(row):
    """새 검색의 목록 필드를 본문 재확인 입력으로 변환. 자격 미확인은 null 보존."""
    published = _pick(row, "published_at")
    deadline = _deadline(row)
    regions, hinted = _regions(row)
    return {"bid_no": _pick(row, "bid_no"), "revision": _pick(row, "revision"),
            "title": _pick(row, "title"), "published_at": published[:10] if published else None,
            "deadline": deadline.isoformat() if deadline else None, "budget": _budget(row),
            "regions": regions if (regions or isinstance(row.get("regions"), list)) and not hinted else None,
            **{field: row.get(field) for field in ("industries", "licenses", "company_sizes", "certs")}}


def recheck_after_ingest(shortlisted, bids, profile, start, end, **kwargs):
    """③' 공고문 적재 후 기존 `recommend_bids`(본문 기반)를 다시 돌려 부적격을 표시한다.

    ②에서 고른 공고마다 `recheck`를 붙여 돌려준다. 점수·체크리스트 계산은 하지 않는다.
    `kwargs`의 now·hits·search를 전달한다. limit은 대상 전체 평가를 위해 내부에서 정한다.
    """
    keys = [identity(row) for row in shortlisted]
    if len(keys) != len(set(keys)):
        raise RequestError("재확인 대상 공고·차수가 중복되었습니다.")
    # 전체 저장소의 다른 공고가 순위를 차지하거나 외부 limit이 평가를 자르면 안 된다.
    selected = set(keys)
    targets = [bid for bid in bids if identity(bid) in selected]
    kwargs["limit"] = max(len(targets), 1)
    result = recommend_bids(targets, profile, start, end, **kwargs)
    passed = {identity(b): b for b in result["bids"]}
    dropped = {(b["bid_no"], b["revision"]): b for b in result["excluded"]}

    reviewed = []
    for row in shortlisted:
        key = (row["bid_no"], row["revision"])
        if key in passed:
            recheck = {"status": "confirmed", "reasons": [],
                       "unknown": passed[key]["unknown"], "distance": passed[key]["distance"]}
        elif key in dropped:
            # 본문·CSV를 보고서야 드러난 부적격. 공고일 미확인은 unknown으로 구분된다.
            recheck = {"status": "disqualified" if dropped[key]["status"] == "excluded" else "unknown",
                       "reasons": dropped[key]["reasons"]}
        else:
            recheck = {"status": "not_evaluated", "reasons": ["적재된 공고 목록에 없습니다."]}
        reviewed.append({**row, "recheck": recheck, "needs_review": True})

    return {"bids": reviewed, "needs_review": True, "stage": "after_notice",
            "disqualified": [r["bid_no"] for r in reviewed if r["recheck"]["status"] == "disqualified"],
            "not_evaluated": [r["bid_no"] for r in reviewed if r["recheck"]["status"] == "not_evaluated"]}
