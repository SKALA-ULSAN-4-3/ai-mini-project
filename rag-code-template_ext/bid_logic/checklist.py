"""C5: 보유 여부와 제출 완료를 구분하고, 원문 일정만 사용한다."""

import re
import unicodedata
from datetime import datetime

from .common import SEOUL, RequestError, check_scope, deadline_info, require_sources, seoul_time


def document_key(name):
    # Unicode 호환 문자와 공백만 정규화. 괄호·연도·'사본' 등 의미 있는 표기는 보존.
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))


def build_checklist(extracted, profile, bid_no, revision, *, now=None, aliases=None):
    check_scope(extracted, bid_no, revision)
    now = seoul_time(now or datetime.now(SEOUL))
    # aliases는 사람이 확인한 별칭 -> 정식명 1단계 대응표.
    aliases = aliases or {}
    normalized_aliases = {document_key(k): document_key(v) for k, v in aliases.items()}

    def canonical(name):
        key = document_key(name)
        return normalized_aliases.get(key, key)

    owned_docs = profile.get("owned_docs")
    # 문자열 하나를 그대로 두면 글자 단위로 비교되어 모든 서류가 미보유로 나온다.
    if owned_docs is not None and (not isinstance(owned_docs, list) or
                                   any(not isinstance(name, str) for name in owned_docs)):
        raise RequestError("프로필 owned_docs는 문자열 배열이어야 합니다.")
    owned ={canonical(name) for name in owned_docs} if owned_docs is not None else None
    docs, schedules, seen = [], [], set()
    for collection, destination in (("documents", docs), ("schedule", schedules)):
        for item in extracted[collection]:
            check_scope(item, bid_no, revision)
            require_sources(item)
            key = collection, item["id"]
            if key in seen:
                raise ValueError("체크리스트 항목 id가 중복되었습니다.")
            seen.add(key)
            info = deadline_info(item.get("due"), now)
            result = {"id": item["id"], "sources": item["sources"],
                      "notes": item.get("notes", []), **info}
            if collection == "documents":
                result.update(doc=item["doc"], owned=(canonical(item["doc"]) in owned
                                                    if owned is not None else None),
                              submitted=False)
            else:
                result["event"] = item["event"]
            result["needs_review"] = info["status"] in ("unknown", "needs_review") or (
                collection == "documents" and owned is None)
            destination.append(result)
    return {"bid_no": bid_no, "revision": revision, "documents": docs, "schedule": schedules,
            "needs_review": any(x["needs_review"] for x in docs + schedules)}
