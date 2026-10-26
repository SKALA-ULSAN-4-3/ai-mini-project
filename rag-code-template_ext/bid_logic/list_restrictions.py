"""상세 제한 정보의 표시와 시·도 비교. 제한 조건과 회사 정보의 미확인을 구분한다."""
import re
import unicodedata

from .common import REGION_NAMES, region


def _province(value):
    value = re.sub(r"\s+", " ", value.strip())
    if value in REGION_NAMES:
        return region(value), False
    first = value.split(" ", 1)[0]
    return (region(first), True) if first in REGION_NAMES else (None, True)


def _normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def restriction_check(row, profile):
    displays, unknown, reasons = {}, [], []
    detail = row.get("region_restriction")
    if isinstance(detail, dict):
        detail = dict(detail)
        if row.get("metadata_sources") and isinstance(row.get("regions"), list):
            detail.update(values=row["regions"], status="limited" if row["regions"] else "none",
                          source="notice_metadata")
        status, values = detail.get("status"), detail.get("values", [])
        if status == "limited":
            detail["summary"] = "지역제한: " + ", ".join(values)
            provinces = [_province(v) for v in values]
            owned = profile.get("region")
            owned = [owned] if isinstance(owned, str) else owned
            owned = [region(v) for v in owned] if owned is not None else None
            if owned is None:
                detail["profile_match"] = "needs_profile"
                unknown.append("회사 소재지 미등록")
            elif provinces and all(p for p, _ in provinces) and not set(owned).intersection(p for p, _ in provinces):
                detail["profile_match"] = "mismatched"
                reasons.append("지역 제한 조건 불일치")
            elif any(p in (owned or []) and not district for p, district in provinces):
                detail["profile_match"] = "matched"
            else:
                detail["profile_match"] = "needs_detail"
                unknown.append("회사 상세소재지 확인 필요 (시군구 제한)" if all(p for p, _ in provinces)
                               else "지역명 표준화·회사 소재지 대조 확인 필요")
        elif status == "none":
            detail["summary"] = "지역제한: 없음"
        elif status == "not_listed" and not str(row.get("rgnLmtBidLocplcJdgmBssNm") or "").strip():
            detail["summary"] = "지역제한: API 등록 내역 없음 (공고문 확인)"
        elif status == "unavailable":
            detail["summary"] = "지역제한: 상세 조회 실패 (재시도 필요)"
            unknown.append("지역제한 상세 API 조회 실패")
        else:
            detail["summary"] = "지역제한: 상세 대상 지역 미등록 (공고문 확인)"
            unknown.append("참가가능지역 상세 정보 미등록")
        displays["region_restriction"] = detail

    detail = row.get("industry_restriction")
    if isinstance(detail, dict):
        detail = dict(detail)
        status, requirements = detail.get("status"), detail.get("requirements", [])
        if status == "limited" and requirements:
            labels = []
            for requirement in requirements:
                label = requirement["name"] + (f" ({requirement['code']})" if requirement.get("code") else "")
                alternatives = [a["name"] + (f" ({a['code']})" if a.get("code") else "")
                                for a in requirement.get("alternatives", [])]
                if alternatives:
                    label += " [대체 허용: " + ", ".join(alternatives) + "]"
                labels.append(label)
            detail["summary"] = "업종제한 있음 · 대상 업종: " + ", ".join(labels)
            # 단일 업종은 정식명·코드가 정확히 일치할 때만 보유 확인으로 표시한다.
            # 여러 제한 그룹·면허·주력분야를 단순 OR 배열로 바꾸어 참가자격을 판정하지 않는다.
            owned = profile.get("industry")
            owned = [owned] if isinstance(owned, str) else list(owned or [])
            licenses = profile.get("licenses")
            owned += [licenses] if isinstance(licenses, str) else list(licenses or [])
            if len(requirements) == 1 and not requirements[0].get("specialties"):
                allowed = [requirements[0], *requirements[0].get("alternatives", [])]
                matched = any((bool(a["name"].strip()) and _normalized(v) == _normalized(a["name"])) or
                              a.get("code") in re.findall(r"(?<!\d)\d{4}(?!\d)", v)
                              for v in owned for a in allowed)
                detail["profile_match"] = "matched" if matched else "needs_profile"
                if not matched:
                    detail["note"] = "회사 프로필의 보유 업종 정식명·코드 확인 필요"
            else:
                detail["profile_match"] = "manual_review"
                detail["note"] = "복수 업종·제한 그룹·주력분야의 충족 조건은 공고문 확인 필요"
        elif status == "none":
            detail["summary"] = "업종제한: 없음"
        elif status == "not_listed":
            detail["summary"] = "업종제한: API 등록 내역 없음 (공고문 확인)"
        elif status == "unavailable":
            detail["summary"] = "업종제한: 상세 조회 실패 (재시도 필요)"
            unknown.append("업종제한 상세 API 조회 실패")
        else:
            detail["summary"] = "업종제한 있음 · 대상 업종 상세 미등록 (공고문 확인)"
            unknown.append("대상 업종 상세 정보 미등록")
        displays["industry_restriction"] = detail
    return displays, unknown, reasons
