"""체크리스트 추출의 누락·일시 출처 검사. 출처 없는 기한을 확정하지 않는다."""
from copy import deepcopy
import re
from .common import seoul_time

DATE_TIME = re.compile(r"(20\d{2})\s*[년./-]\s*(\d{1,2})\s*[월./-]\s*(\d{1,2})\s*일?\.?\s*(?:\([^)]*\))?\s*(\d{1,2})\s*:\s*(\d{2})")


def source_times(text):
    found = []
    for match in DATE_TIME.finditer(text):
        y,m,d,h,minute = map(int, match.groups())
        try:
            value = seoul_time(f"{y:04}-{m:02}-{d:02}T{h:02}:{minute:02}+09:00").isoformat()
        except ValueError:
            continue
        found.append((match.start(), value))
    return found


def compact(value):
    return re.sub(r"\s+", "", value or "")


def reconcile_required_docs(extraction, texts, refs, labels):
    result = deepcopy(extraction)
    warnings = []
    # 이 명시적 표현에 한해 서류 공통 마감을 복구. 가격입찰·참가등록 기한은 사용하지 않는다.
    deadline_candidates = []
    for n, text in texts.items():
        for heading in re.finditer(r"입찰\s*서류\s*제출\s*마감\s*(?:일시)?", text):
            tail = text[heading.end():heading.end()+100].split("\n")[0]
            times = source_times(tail)
            if len(times) == 1 and n in refs:
                deadline_candidates.append((n, times[0][1]))
    unique_deadlines = {due for _, due in deadline_candidates}
    names = compact(" ".join(d["doc_name"] for d in result["docs"]))
    # 실제 검증에서 누락된 제출물 종류. 명칭이 원문 제출 목록에 있을 때만 보완한다.
    for pattern in (r"정량적?\s*제안서", r"정성적?\s*제안서", r"발표\s*자료"):
        candidates = []
        for n, text in texts.items():
            for match in re.finditer(pattern, text):
                nearby = text[max(0, match.start()-180):match.end()+180]
                if re.search(r"제출|첨부|구비", nearby) and n in refs:
                    candidates.append((n, match.group()))
        if not candidates or any(compact(name) in names for _, name in candidates):
            continue
        n, name = candidates[0]
        result["docs"].append({"doc_name":name, "note":"원문 제출 목록에서 누락을 보완. 조건·수량·기한 확인 필요",
            "mandatory":False, "due":"", "due_iso":None, "source":labels.get(n, "unknown"),
            "source_refs":[refs[n]], "source_verified":True, "needs_review":True})
        warnings.append(f"제출물 누락 보완: {name}")
    for doc in result["docs"]:
        # 공통/가격입찰 마감을 모든 서류에 복사하지 않는다.
        if not doc.get("due_verified"):
            doc["due_iso"] = None
            doc["needs_review"] = True
            if len(unique_deadlines) == 1 and not any(term in compact(doc["doc_name"]) for term in (
                    "가격입찰서", "전자입찰서", "공동수급", "협정서")):
                n, due = deadline_candidates[0]
                doc.update(due_iso=due, due_verified=True)
                if refs[n] not in doc.get("source_refs", []):
                    doc.setdefault("source_refs", []).append(refs[n])
                doc["note"] = (doc.get("note", "") + "; 원문 '입찰서류 제출 마감' 적용. 개별 예외 확인 필요").strip("; ")
    for event in result.get("schedule", []):
        # 일정 이름만 포함된 페이지는 날짜의 근거로 충분하지 않다.
        due = event.get("due_iso")
        matches = [n for n,t in texts.items() if compact(event["event"]) in compact(t) and n in refs and (
                   (compact(event.get("when")) and compact(event["when"]) in compact(t)) or
                   (due and seoul_time(due).isoformat() in {value for _,value in source_times(t)}))]
        if matches:
            n = next((n for n in matches if refs[n] in event.get("source_refs", [])), matches[0])
            event.update(source=labels.get(n, "unknown"), source_refs=[refs[n]], source_verified=True)
        else:
            event.update(source_verified=False, needs_review=True, due_iso=None)
            warnings.append(f"일시 원문 대조 필요: {event['event']}")
    result["quality_warnings"] = warnings
    result["needs_review"] = bool(warnings) or any(d.get("needs_review") for d in result["docs"]) or any(
        not e.get("source_verified") for e in result.get("schedule", []))
    return result
