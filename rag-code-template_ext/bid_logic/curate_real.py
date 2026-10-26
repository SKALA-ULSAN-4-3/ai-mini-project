"""원문을 읽고 작성한 독립 정답 초안. calculate_scores/체크리스트 출력에서 정답을 만들지 않는다.

AI 작성 초안이며 사람 검토는 pending이다. HWPX에는 실제 XML 위치를 쓰고 PDF 쪽수를 지어내지 않는다.
"""
from copy import deepcopy
import json
from pathlib import Path

from .prepare_real import ROOT, SCORE_BIDS, write_json

PENDING={"status":"pending","reviewer":None,"reviewed_at":None,"author":"AI source-reading draft"}


def curate(dataset, assets):
    if (dataset/"gold.json").exists():
        previous=json.loads((dataset/"gold.json").read_text())
        if any(row.get("review",{}).get("status")=="verified" for rows in previous.values() for row in rows):
            raise ValueError("사람이 검토 완료한 정답은 덮어쓰지 않습니다.")
        # 일부만 사람이 확인한 정답도 다시 만들면 확인 범위 기록이 사라진다.
        if any("human_scope" in row.get("review",{}) for rows in previous.values() for row in rows):
            raise ValueError("사람 확인 범위가 기록된 정답은 덮어쓰지 않습니다.")
    blocks=json.loads((assets/"evidence.json").read_text())
    profiles=json.loads((dataset/"profiles.json").read_text())
    def source(no, page=None, rfp=False, locator=None):
        matches=[b for b in blocks if b["source"]["bid_no"]==no and (
            b["source"].get("locator")==locator if locator else
            b["source"].get("page")==page and ("제안요청서" in b["source"]["filename"])==rfp)]
        if len(matches)!=1:raise ValueError(f"출처를 한 개로 특정할 수 없음: {no}/{page}/{locator}")
        return deepcopy(matches[0]["source"])
    table_specs={
      SCORE_BIDS[0]:[("경영상태",5),("사업수행능력",5),("사업이해도",5),("추진전략",5),("적용기술",5),
        ("표준프레임워크 적용",5),("개발방법론",5),("기능요구사항",5),("데이터요구사항",5),("보안요구사항",5),
        ("제약사항",5),("성능요구사항",5),("인터페이스요구사항",5),("품질요구사항",5),("테스트요구사항",5),
        ("관리방법론",5),("일정계획",5),("품질보증",2),("시험운영",2),("교육훈련",2),("하자보수",2),("기밀보안",2),("추가제안",5)],
      SCORE_BIDS[1]:[("경영상태",5),("사업이해도-배경과목표",10),("사업이해도-과업범위",10),
        ("DB 분석 스키마 설계 및 이관 방안",20),("이전 데이터 확인 인터페이스 개발",10),("클라우드 환경 구성",15),
        ("일정 보안 형상 문서 관리",10),("수행조직 및 업무분장",10)],
      SCORE_BIDS[2]:[("사업이해도",6),("추진전략",5),("추진체계",5),("사업추진방법론",4),("기능요구사항",6),
        ("성능요구사항",5),("인터페이스요구사항",5),("유지보수 용이성",4),("적용기술",5),("개발환경",5),
        ("보안요구사항",4),("제약사항",4),("일정관리",4),("품질관리",4),("기밀보안관리",4),
        ("위험 및 이슈 관리",4),("인수인계",4),("교육훈련",4),("기술지원",4),("하자보수계획",4)],
      SCORE_BIDS[3]:[("경영상태",5),("제안개요",5),("추진전략",5),("기능",18),("AI",15),("데이터",6),("보안",6),
        ("관리방법 및 일정계획",4),("사업수행조직",4),("품질보증",4),("교육훈련",4),("유지보수",4)],
      SCORE_BIDS[4]:[("경영상태",5),("용역사업 수행실적",5),("사업이해도",4),("추진전략",5),("프레임워크 적용",6),
        ("KRI 연계 기능구현",5),("교수공채 시스템 기능구현",5),("피트니스센터 출입관리 기능구현",5),("보안요구사항",4),
        ("데이터요구사항",3),("제약사항요구사항",3),("성능요구사항",7),("품질요구사항",7),("인터페이스요구사항",6),
        ("관리방법론",4),("일정계획",3),("개발환경",3),("장애대처",4),("품질관리",3),("유지관리",3)]}
    table_sources={SCORE_BIDS[0]:source(SCORE_BIDS[0],locator="Contents/section7.xml#element-2477"),
      SCORE_BIDS[1]:source(SCORE_BIDS[1],locator="Contents/section0.xml#element-4471"),
      SCORE_BIDS[2]:source(SCORE_BIDS[2],locator="Contents/section0.xml#element-14315"),
      SCORE_BIDS[3]:source(SCORE_BIDS[3],25,True), SCORE_BIDS[4]:source(SCORE_BIDS[4],35,True)}
    top=["AAA","AA+","AA0","AA-","A+","A0","A-","BBB+","BBB0"]
    middle=["BBB-","BB+","BB0","BB-"]
    lower=["B+","B0","B-"]
    tables=[]
    for no in SCORE_BIDS:
        items=[]
        for i,(name,maximum) in enumerate(table_specs[no]):
            kind="qualitative"
            refs=[deepcopy(table_sources[no])]
            metric=rule=None
            if name=="경영상태" and no in (SCORE_BIDS[0],SCORE_BIDS[1],SCORE_BIDS[4]):
                kind="quantitative"; metric={"field":"credit_rating"}
                if no==SCORE_BIDS[1]:
                    refs.append(source(no,locator="Contents/section0.xml#element-5745")); scores=(5,4.5,4)
                elif no==SCORE_BIDS[0]:
                    refs.append(source(no,locator="Contents/section7.xml#element-4190")); scores=(5,4.75,4.5)
                else:
                    refs.append(source(no,37,True)); scores=(5,4.75,4.5)
                rule={"type":"category","values":{**dict.fromkeys(top,scores[0]),**dict.fromkeys(middle,scores[1]),
                         **dict.fromkeys(lower,scores[2])}}
            elif no==SCORE_BIDS[4] and name=="용역사업 수행실적":
                kind="quantitative"; refs.append(source(no,37,True))
                metric={"field":"track_records","aggregate":"sum","unit":"KRW","from":"2023-10-07",
                        "to":"2026-10-07","categories":["Axis 대학 정보화"]}
                rule={"type":"bands","bands":[{"min":0,"max":30400000,"score":3.5},
                    {"min":30400000,"max":53200000,"score":4},
                    {"min":53200000,"max":76000000,"score":4.5},{"min":76000000,"score":5}]}
            if no==SCORE_BIDS[3] and i>=9:refs=[source(no,26,True)]
            if no==SCORE_BIDS[4] and i>=11:refs=[source(no,36,True)]
            items.append({"bid_no":no,"revision":"000" if no!=SCORE_BIDS[1] else "001",
                "id":f"item{i+1:02}","item":name,"kind":kind,"max":maximum,"basis":
                ("원문 신용평가등급표에 따른 항목 원점수" if metric and metric["field"]=="credit_rating" else
                 "입찰공고일 기준 최근 3년 Axis 프레임워크 대학 정보화사업 수행실적 합산 구간표" if metric else
                 "원문 기술성 평가표의 해당 항목. 구간/등급 산정표가 없는 정성 항목"),
                "metric":metric,"rule":rule,"sources":refs})
        revision=items[0]["revision"]
        items.append({"bid_no":no,"revision":revision,"id":"price","item":"입찰가격평가","kind":"price",
            "max":20 if no==SCORE_BIDS[3] else 10,"basis":"가격 항목은 담당자 판단. 원문 배점만 표시",
            "metric":None,"rule":None,"sources":[deepcopy(table_sources[no])]})
        tables.append({"bid_no":no,"revision":revision,"items":items,"curation":"AI source-reading draft",
            "notes":["농지 공고는 기술평가표 100점 원점수를 90점으로 환산. 이 파일은 항목 원점수만 비교하며 총점 미산출"] if no==SCORE_BIDS[0] else []})
    write_json(dataset/"scoring_tables.json",tables)
    # 서류 목록은 공고문에서 직접 읽었다. 숫자와 명칭의 정답을 함수 출력에서 복사하지 않는다.
    doc_specs={
      SCORE_BIDS[0]:(5,["정량제안서","정성제안서","발표자료(제안요약서)","경쟁입찰참가자격등록증","사업자등록증(원본대조필)",
        "법인 등기부등본","인감증명서","사용인감신고서","소프트웨어사업자신고확인서","중소기업·소상공인 확인서","직접생산확인증명서"]),
      SCORE_BIDS[1]:(8,["발표 자료(평가 참고자료)","경쟁입찰참가자격등록증","법인 등기사항증명서(개인사업자인 경우 사업자등록증)",
        "소프트웨어사업자 일반 현황 관리확인서","중소기업·소상공인 확인서","직접생산확인증명서","4대사회보험사업장가입자명부",
        "국세·지방세 완납증명서","인감증명서 또는 사용인감계","제안업체 현황 및 연혁","참여인력 편성표","참여인력 개인 이력서",
        "참여업체 유사용역 수행실적","청렴계약이행 서약서","보안 서약서","개인정보 수집·이용동의서"]),
      SCORE_BIDS[2]:(8,["정성적 제안서(증빙서류 포함)","발표자료","경쟁입찰참가자격등록증",
        "법인 등기사항증명서(개인사업자인 경우 사업자등록증)","법인인감증명서","소프트웨어사업자 일반 현황 관리확인서",
        "직접생산확인증명서","중·소기업·소상공인확인서 신청 증빙서류","특별법인을 확인할 수 있는 서류",
        "입찰업체 서약서","공동책임 확인서","퇴직자 영입현황 확인서 및 서약서"]),
      SCORE_BIDS[3]:(2,["주민등록등본","인감증명서","사용인감계","위임장","재직증명서","이행(입찰)보증보험증권",
        "지방세 완납증명서","국세 완납증명서","소프트웨어사업자 일반 현황 관리 확인서","중소기업확인서","직접생산확인증명서",
        "가격제안서","제안서","제안서 파일이 저장된 USB","청렴계약이행서약서"]),
      SCORE_BIDS[4]:(4,["정성적평가 제안서(증빙자료 포함)","정량적평가 제안서(증빙서류 포함)","기타서류","입찰참가자격 확인서류"])}
    deadlines={SCORE_BIDS[0]:"2026-08-21T10:00:00+09:00",SCORE_BIDS[1]:"2026-09-14T10:00:00+09:00",
        SCORE_BIDS[2]:"2026-10-14T10:00:00+09:00",SCORE_BIDS[3]:"2026-09-11T11:00:00+09:00",SCORE_BIDS[4]:"2026-10-19T10:00:00+09:00"}
    checklists=[]
    for table in tables:
        no,revision=table["bid_no"],table["revision"]
        page,names=doc_specs[no]
        docs=[{"id":f"doc{i+1:02}","bid_no":no,"revision":revision,"doc":name,"due":deadlines[no],
               "notes":["법인/개인/특별법인/신청 증빙 등 해당 조건은 원문 확인 필요"],"sources":[source(no,page)]}
              for i,name in enumerate(names)]
        if no==SCORE_BIDS[1]:
            for name in ("정량적 제안서(신용평가등급확인서, 증빙서류 포함)","정성적 제안서 원본","정성적 제안서 사본"):
                docs.append({"id":f"doc{len(docs)+1:02}","bid_no":no,"revision":revision,"doc":name,
                    "due":deadlines[no],"sources":[source(no,7)],"notes":[]})
            docs.append({"id":f"doc{len(docs)+1:02}","bid_no":no,"revision":revision,"doc":"가격입찰서",
                "due":deadlines[no],"sources":[source(no,7)],"notes":["전자입찰서로 제출"]})
        if no==SCORE_BIDS[3]:
            for name in ("입찰참가신청서","사업자등록증 사본","법인등기부등본"):
                docs.append({"id":f"doc{len(docs)+1:02}","bid_no":no,"revision":revision,"doc":name,
                    "due":deadlines[no],"sources":[source(no,1)],"notes":[]})
        if no==SCORE_BIDS[0]:
            for name,due,extra_page,condition in (("적격조합확인서","2026-08-20T18:00:00+09:00",3,"적격조합만"),
                    ("배정계획서","2026-08-20T18:00:00+09:00",3,"적격조합만"),
                    ("특별법인 중소기업 간주 확인서",None,3,"특별법인. 낙찰자 결정 전 별도 지정 시까지"),
                    ("공동수급협정서","2026-08-20T18:00:00+09:00",3,"공동수급 시"),
                    ("가격입찰서",deadlines[no],4,"전자입찰"),
                    ("청렴계약이행각서",None,1,"낙찰자 계약 체결 시 별도 제출; 입찰 시 제출 간주")):
                docs.append({"id":f"doc{len(docs)+1:02}","bid_no":no,"revision":revision,"doc":name,"due":due,
                    "sources":[source(no,extra_page)],"notes":[condition]})
        if no in (SCORE_BIDS[2],SCORE_BIDS[4]):
            docs.append({"id":f"doc{len(docs)+1:02}","bid_no":no,"revision":revision,"doc":"가격입찰서",
                "due":deadlines[no],"sources":[source(no,7 if no==SCORE_BIDS[2] else 4)],"notes":["전자입찰서로 제출"]})
        due_page={SCORE_BIDS[0]:4,SCORE_BIDS[1]:4,SCORE_BIDS[2]:3,SCORE_BIDS[3]:1,SCORE_BIDS[4]:4}[no]
        due_source=source(no,due_page)
        for doc in docs:
            if doc["due"]==deadlines[no] and due_source not in doc["sources"]:
                doc["sources"].append(deepcopy(due_source))
        schedule=[{"id":"proposal","bid_no":no,"revision":revision,"event":"제안서 제출 마감",
                   "due":deadlines[no],"sources":[deepcopy(due_source)],"notes":[]}]
        if no==SCORE_BIDS[3]:
            schedule.extend([{"id":"registration","bid_no":no,"revision":revision,"event":"입찰참가자격 등록 마감",
                "due":"2026-09-11T10:00:00+09:00","sources":[source(no,1)],"notes":[]},
                {"id":"price_submission","bid_no":no,"revision":revision,"event":"가격입찰서 제출 마감",
                "due":"2026-09-14T11:00:00+09:00","sources":[source(no,1)],"notes":[]}])
        if no==SCORE_BIDS[1]:
            schedule.append({"id":"evaluation","bid_no":no,"revision":revision,"event":"제안서 평가회",
                "due":"2026-09-16T14:00:00+09:00","sources":[source(no,10)],"notes":["예정. 일정 변경 가능"]})
        if no==SCORE_BIDS[4]:
            schedule.append({"id":"submission_start","bid_no":no,"revision":revision,"event":"제안서·가격 전자입찰서 제출 시작",
                "due":"2026-10-08T10:00:00+09:00","sources":[source(no,4)],"notes":[]})
        if no!=SCORE_BIDS[3]:
            schedule.append({"id":"opening","bid_no":no,"revision":revision,"event":"가격개찰",
                 "due":None,"sources":[source(no,4 if no in (SCORE_BIDS[0],SCORE_BIDS[4]) else 7)],
                 "notes":["제안서 평가 후. 확정 시각 없음"]})
        if no in (SCORE_BIDS[0],SCORE_BIDS[2]):
            schedule.append({"id":"joint","bid_no":no,"revision":revision,"event":"공동수급협정서 제출 마감",
                "due":"2026-08-20T18:00:00+09:00" if no==SCORE_BIDS[0] else "2026-10-13T18:00:00+09:00",
                "sources":[source(no,3 if no==SCORE_BIDS[0] else 6)],"notes":["공동수급 시에만 해당"]})
        checklists.append({"bid_no":no,"revision":revision,"documents":docs,"schedule":schedule,
                           "scope":"AI 정답 초안. 조건부 및 RFP 부속 증빙은 추가 검토 필요"})
    write_json(dataset/"checklists.json",checklists)
    gold={"recommendations":[],"scores":[],"checklists":[]}
    relevant={"seoul_web":["R26BK01753530"],"ulsan_data":["R26BK01751013","R26BK01753451","R26BK01754897"],
              "jeju_campus":["R26BK01753530","R26BK01757019","R26BK01760198"]}
    for profile in profiles:
        gold["recommendations"].append({"profile_id":profile["id"],"relevant":[{"bid_no":n,"revision":"000"} for n in relevant[profile["id"]]],
            "rationale":"20건 원문 사업명·과업과 가상 회사 관심분야를 독립 대조한 초안. 2026-10-07 시점 마감·금액 고려. 미확인 자격은 확정하지 않음.",
            "review":deepcopy(PENDING)})
    # 원문 표에서 별도로 읽은 수치. 코드 채점 결과나 rule 조회로 expected를 생성하지 않는다.
    credit_answers={SCORE_BIDS[0]:[5,4.75,4.5],SCORE_BIDS[1]:[5,4.5,4],SCORE_BIDS[4]:[5,4.75,4.5]}
    performance_answers=[5,4,3.5]  # 1억>=7600만; 4천만은3040~5320만; 2천만<3040만
    for table, checklist in zip(tables,checklists):
        no=table["bid_no"]
        for i,profile in enumerate(profiles):
            items=[]
            for item in table["items"]:
                value="담당자 판단";status="manual";basis="정성·가격 또는 산정 기준 미확정: 수치 예측하지 않음"
                if item["item"]=="경영상태" and no in credit_answers:
                    value=credit_answers[no][i];status="calculated";basis=f"원문 등급표 독립 검산: {profile['credit_rating']} → {value}점. 유효한 확인서 가정"
                elif no==SCORE_BIDS[4] and item["item"]=="용역사업 수행실적":
                    value=performance_answers[i];status="calculated";basis=f"원문 금액 구간 손계산: {profile['track_records'][0]['amount']}원 → {value}점. Axis 인정 실적 가정"
                items.append({"id":item["id"],"expected":value,"status":status,"basis":basis,"sources":deepcopy(item["sources"])})
            gold["scores"].append({"bid_no":no,"revision":table["revision"],"profile_id":profile["id"],"items":items,"review":deepcopy(PENDING)})
            docs=[]
            for d in checklist["documents"]:
                # 보유 여부의 독립 정답: 명칭을 정확히 보유한 것만 true. 유사 이름은 추정하지 않음.
                owned=d["doc"] in profile["owned_docs"] or (
                    profile["id"]=="seoul_web" and d["doc"]=="소프트웨어사업자신고확인서")
                docs.append({"doc":d["doc"],"owned":owned,"due":d["due"],"sources":deepcopy(d["sources"])})
            gold["checklists"].append({"bid_no":no,"revision":table["revision"],"profile_id":profile["id"],
                "documents":docs,"schedule":[{k:deepcopy(s[k]) for k in ("event","due","sources")} for s in checklist["schedule"]],
                "review":deepcopy(PENDING)})
    write_json(dataset/"gold.json",gold)
    # 별도로 원문 대조해 보완한 증빙·조건·인용도 재생성 시 유지한다.
    from .source_review import review_sources
    review_sources(dataset, assets)
    print("Prepared AI reference draft: 3 recommendations, 15 score cases, 15 checklist cases; human review pending")


if __name__=="__main__":
    curate(Path("evaluation/real"),ROOT/"data/evaluation-source-20261023")
