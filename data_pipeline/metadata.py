"""원문에 날짜·시간이 함께 명시된 제출/마감 일시만 추출한다."""
from datetime import datetime
import re


def extract_deadlines(pages):
    """등록 마감과 제안서 제출 마감을 구분하고 기간은 종료 일시를 쓴다."""
    labels=[("bid",r"(?:전자)?입찰서(?:제출|접수)?(?:마감일시|제출기간|제출마감일시)"),
            ("proposal",r"제안서(?:및가격입찰서)?(?:제출(?:기간|기한)?|마감)(?:파일|제본)?"),
            ("registration",r"입찰(?:참가신청|참가자격등록마감일시|등록마감)")]
    date_time=r"(20\d{2})[.년/-](\d{1,2})[.월/-](\d{1,2})[.일]?(?:\([가-힣]\))?[~～]?(\d{1,2}):(\d{2})"
    results=[]
    for page in pages:
        text=re.sub(r"\s+","",page["text"])
        for kind,pattern in labels+[("proposal",r"제출기간")]:
            for label in re.finditer(pattern,text):
                if label.group()=="제출기간" and "제안서제출" not in text[max(0,label.start()-300):label.start()]:
                    continue
                rest=text[label.end():label.end()+180]
                found=re.match(r"[:：]?(?:파일|제본)?"+date_time,rest)
                if not found:continue
                second=re.match(r"[~～부터까지]{1,4}"+date_time,rest[found.end():])
                chosen=second if second else found
                groups=chosen.groups()
                try:value=datetime(*(int(g) for g in groups)).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:continue
                end=label.end()+found.end()+(second.end() if second else 0)
                row=dict(kind=kind,deadline=value,text=text[label.start():end],file_name=page["file_name"],page=page["page"],source_url=page["source_url"])
                if not any(r["kind"]==kind and r["deadline"]==value for r in results):results.append(row)
    return results


def extract_deadline(pages):
    structured=extract_deadlines(pages)
    for kind in ("bid","proposal","registration"):
        values=[r for r in structured if r["kind"]==kind]
        if values:
            row=min(values,key=lambda r:r["deadline"])
            return row["deadline"],row
    patterns = [r"(?:입찰서.{0,12}마감일시|제안서.{0,12}제출기간|제안서.{0,12}제출기한|가격입찰서제출|제안서및가격입찰서제출)",
                r"(?:입찰등록.{0,8}마감|입찰참가신청.{0,8}마감)"]
    date_pattern = r"(20\d{2})[.년/-](\d{1,2})[.월/-](\d{1,2})[.일]?(?:\([월화수목금토일]\))?"
    for pattern in patterns:
        for page in pages:
            compact = re.sub(r"\s+", "", page["text"])
            for label in re.finditer(pattern, compact):
                rest = compact[label.end():label.end()+100]
                found = re.match(r"[:：]?(?:[~～])?" + date_pattern + r".{0,4}?(\d{1,2}):(\d{2})(?:[~～](\d{1,2}):(\d{2}))?", rest)
                if found:
                    year, month, day, hour, minute, end_hour, end_minute = found.groups()
                    try:
                        deadline = datetime(int(year), int(month), int(day), int(end_hour or hour), int(end_minute or minute))
                    except ValueError:
                        continue
                    return deadline.strftime("%Y-%m-%d %H:%M:%S"), {
                        "text": compact[label.start():label.end()+found.end()],
                        "file_name": page["file_name"], "page": page["page"], "source_url": page["source_url"]}
    return "", None


# 원문 지역 조건의 기록 전용. 회사 정보와 비교하거나 참가 가능 여부를 판정하지 않는다.
REGIONS = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
           "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도",
           "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도", "경상남도", "제주특별자치도")
REGION_ALIASES={"서울":"서울특별시","부산":"부산광역시","경남":"경상남도","경북":"경상북도",
                "경기":"경기도","충남":"충청남도","충북":"충청북도","제주":"제주특별자치도"}

def compact(text):
    return re.sub(r"\s+", "", text)



def evidence(page, quote):
    return {k: page.get(k, "") for k in ("bid_no", "bid_order", "file_name", "page", "source_url")} | {"quote": quote}


def region_requirement(pages):
    results = []
    for p in pages:
        text = compact(p["text"])
        next_page = next((q for q in pages if q["document_id"]==p["document_id"] and q["page"]==p["page"]+1), None)
        searchable = text + (compact(next_page["text"])[:300] if next_page else "")
        # 수요기관/납품 장소/연락처 주소는 지역 참가조건으로 쓰지 않는다.
        for match in re.finditer(r"(?:주된영업소(?:재지)?|본점(?:의)?소재지|본사(?:의)?소재지|지역제한)", text):
            left = max(0, match.start()-140)
            right = min(len(searchable), match.end()+220)
            quote = searchable[left:right]
            if re.search(r"지역제한[:：]?(?:없음|없습니다|해당없음|미적용)", quote):
                results.append({"status": "explicit_none", "regions": [], "source": evidence(p, quote)})
                continue
            tail = searchable[match.end():right]
            regions = [r for r in REGIONS if r in tail]
            bracket=re.match(r"[:：]?[([]([^])]{1,60})[)\]]",tail) if match.group()=="지역제한" else None
            if bracket:
                regions=list(dict.fromkeys(REGION_ALIASES.get(token,token) for token in re.split(r"[,·ㆍ/]|및|또는",bracket[1]) if token in REGION_ALIASES or token in REGIONS))
            if regions and re.search(r"소재|두고|이어야|있는|인업체|지역제한", quote):
                # 하나의 지역명만 발견해도 시·군 제한/여러 지역의 AND·OR는 검토한다.
                results.append({"status": "restricted", "regions": regions, "source": evidence(p, quote),
                                "sources": [evidence(next_page,compact(next_page["text"])[:300])] if next_page and right>len(text) else [],
                                "complex": bool(re.search(r"공동수급|구성원", tail) or any(re.search(re.escape(r)+r"[가-힣]{1,8}[시군구]",tail) for r in regions))})
    if not results:
        return {"status": "not_stated", "regions": [], "source": None,
                "description": "검사한 공고문에서 명시적 지역 참가조건을 찾지 못함. 제한 없음으로 판정하지 않음"}
    # 긍정·부정 문구가 충돌하면 한쪽을 임의로 선택하지 않는다.
    signatures = {(r["status"], tuple(r["regions"])) for r in results}
    if len(signatures) != 1:
        return {"status": "ambiguous", "regions": sorted({region for r in results for region in r['regions']}),
                "sources": [s for r in results for s in [r["source"]]+r.get("sources",[])]}
    return results[0]
