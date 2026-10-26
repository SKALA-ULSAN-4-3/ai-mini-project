"""실측과 원문 기반 초안을 사람이 검토할 수 있는 저장소 보고서로 정리한다."""
import csv
import json
from pathlib import Path
import statistics

from .prepare_real import ROOT, write_json
from .recommendation import load_bids_csv, recommend_bids


def review(dataset,assets):
    def read(name):return json.loads((dataset/name).read_text())
    report=read("draft-report.json");gold=read("gold.json");profiles=read("profiles.json")
    bids=load_bids_csv(dataset/"bids.csv");titles={r["bid_no"]:r["title"] for r in bids}
    tables=read("scoring_tables.json");checklists=read("checklists.json")
    x2=read("x2-measurements.json");cases=x2["cases"]
    expected={r["profile_id"]:{i["bid_no"] for i in r["relevant"]} for r in gold["recommendations"]}
    list_metrics=[]
    for r in read("list-rankings.json"):
        actual=[b["bid_no"] for b in r["result"]["bids"]]
        list_metrics.append({"profile_id":r["profile_id"],"precision_at_5":len(set(actual)&expected[r["profile_id"]])/5,
                             "returned":actual})
    measured={"status":"preliminary_pending_human_review","human_verified":False,
        "list_stage":list_metrics,"body_stage":report["metrics"]["recommendations"],
        "fixed_score_matches":sum(s["matched"] for s in report["metrics"]["scores"]),
        "score_items":len(report["metrics"]["scores"]),
        "quantitative_matches":sum(s["matched"] for s in report["metrics"]["scores"] if s["kind"]=="quantitative"),
        "quantitative_items":sum(s["kind"]=="quantitative" for s in report["metrics"]["scores"]),
        "x2_cases":len(cases),"x2_complete":sum(c["agent"]["status"]=="complete" for c in cases),
        "x2_item_matches":sum(sum(c["agent_matches"].values()) for c in cases),
        "fixed_latency_median_ms":statistics.median(c["fixed"]["latency_ms"] for c in cases),
        "agent_latency_median_ms":statistics.median(c["agent"]["latency_ms"] for c in cases),
        "agent_cost_total_usd":sum(c["agent_cost_usd"] for c in cases),
        "agent_cost_mean_usd":sum(c["agent_cost_usd"] for c in cases)/len(cases),
        "input_tokens":sum(c["agent"]["token_usage"]["input_tokens"] for c in cases),
        "output_tokens":sum(c["agent"]["token_usage"]["output_tokens"] for c in cases)}
    rubric_path=dataset/"recommendation-review.json"
    if rubric_path.exists():
        measured["recommendation_rubric_id"]=read("recommendation-review.json")["rubric"]["id"]
        measured["recommendation_label_change_only"]=True
    raw_models={p.stem:json.loads(p.read_text()) for p in (assets/"model-extractions").glob("*.json")}
    sources={b["id"]:b for b in json.loads((assets/"evidence.json").read_text())}
    audits=[]
    # 원문을 직접 대조해 확정한 최소 확인 항목. 이름·묶음 차이는 검토 사항이지 자동 오답이 아니다.
    for no,terms in {"R26BK01706837":["정량적제안서"],"R26BK01751013":["정성적제안서","발표자료"]}.items():
        text="".join(d["doc"].replace(" ","") for d in raw_models[no]["payload"]["documents"])
        audits.extend({"bid_no":no,"kind":"missing_document_anchor","anchor":term,
                       "source_page":7 if no=="R26BK01706837" else 8,
                       "note":"원문 제출서류 목록에는 있으나 독립 모델 추출 명칭 목록에는 없음"}
                      for term in terms if term not in text)
    ewha=raw_models["R26BK01706954"]["payload"]
    audits.append({"bid_no":"R26BK01706954","kind":"different_deadlines",
        "documents_due":"2026-09-11T11:00:00+09:00","price_due":"2026-09-14T11:00:00+09:00",
        "null_due_documents":sum(d.get("due") is None for d in ewha["documents"]),
        "note":"공고문 p.1. 서류 마감과 가격입찰 마감을 구분. 추출기는 서류 due를 비워 반환"})
    for no,r in raw_models.items():
        for event in r["payload"]["schedule"]:
            due=event.get("due")
            if due and no=="R26BK01706837" and "평가회" in event["event"]:
                cited=sources[event["doc_no"]]
                audits.append({"bid_no":no,"kind":"schedule_citation_review","event":event["event"],"due":due,
                    "cited_page":cited["source"].get("page"),"correct_page":10,
                    "note":"예정 일시는 원문 p.10에 있음. 모델은 다른 페이지를 인용했으므로 출처 보정 필요"})
    write_json(dataset/"checklist-audit.json",{"human_verified":False,"scope":"independent JSON extraction experiment, not live RAG server",
        "findings":audits,"raw_counts":[{"bid_no":no,"items":len(r["payload"]["items"]),
        "documents":len(r["payload"]["documents"]),"schedule":len(r["payload"]["schedule"])} for no,r in raw_models.items()]})
    write_json(dataset/"measurement-summary.json",measured)
    lines=["# 실제 공고 평가·X2 실측 (2026-10-23)","",
      "**AI가 원문을 읽어 작성한 정답 초안과의 잠정 비교다. 사람 검토 완료·운영 E2E 완료를 뜻하지 않는다.**", "",
      "## 평가 조건", "",
      "- 실제 고정 공고 20건, 가상 프로필 3개, 채점·체크리스트 공고 5건 × 3프로필.",
      "- 재생 시각: 2026-10-07 16:00 KST. 검색 기간: 2026-08-01~2026-10-07. 현재 유효 입찰 추천 아님.",
      "- 실제 text-embedding-3-small로 공고문 289청크·프로필 질의 3개·공고명 20개 임베딩(190,284토큰).",
      "- 본문 순위는 실제 벡터의 제곱 L2 완전탐색. FAISS 실행을 했다는 뜻은 아님.",
      "- 지역·업종 등의 미확인 자격은 null. 제주대의 제주 지역제한만 공고문 p.2~3에서 확인해 반영.",
      "- 원문은 data/evaluation-source-20261023/raw에 보존. PDF 253페이지를 macOS PDFKit으로 추출.",
      "- HWPX 3건의 표는 XML 위치를 인용. 실제 PDF 쪽수는 미확정이며 임의 쪽수를 넣지 않음.","",
      "## 추천 일치율", "", "| 가상 프로필 | ② 공고명 순위 P@5 | 기존 본문 순위 P@5 |", "| --- | ---: | ---: |"]
    for a,b in zip(list_metrics,report["metrics"]["recommendations"]):
        lines.append(f"| {a['profile_id']} | {a['precision_at_5']:.0%} | {b['precision_at_5']:.0%} |")
    counts="/".join(str(len(g["relevant"])) for g in gold["recommendations"])
    lines += ["", f"분모는 항상 5. 정답 초안의 관련 공고 수는 프로필 순서대로 {counts}건이고, 마감 경과·미확인 조건이 있어",
              "이 수치를 서비스 전체 정확도로 일반화하거나 임계값을 통과했다고 말하지 않는다.", "",
              "추천 정답 기준과 60개 판정: [RECOMMENDATION_REVIEW.md](RECOMMENDATION_REVIEW.md). 해당 파일이 있는 경우 최신 수치는 정답 기준 재검토 결과이며, 추천 코드·입력·벡터는 변경하지 않았다. 알고리즘 개선 실적으로 해석하지 않는다.", "",
              "## 점수·체크리스트 코드", "",
              f"- 원문 표에서 별도로 검산한 정량 항목 {measured['quantitative_matches']}/{measured['quantitative_items']} 일치.",
              f"- 정성·가격 포함 전체 항목 {measured['fixed_score_matches']}/{measured['score_items']} 일치.",
              "- 농지 공고는 기술평가표 100점 원점수를 최종 90점으로 환산한다. 여기서는 항목 원점수만 비교하고 총점은 산출하지 않음.",
              "- 제주대 수행실적은 Axis 기반 대학 정보화 인정 실적이라는 가상 프로필 가정 아래 합산. 실제 증빙의 인정 여부는 사람 확인.",
              "- 정리한 서류·일정 입력을 체크리스트 코드로 변환한 15조합의 명칭·보유·기한·출처 대조는 일치.",
              "  이는 정형 입력 변환의 검증이다. RAG 서류 추출이 원문과 전부 일치한다는 의미가 아니다.","",
              "## 독립 서류 추출 원문 대조", "",
              "원문을 별도 GPT-4o JSON 추출에 넣어 검산 초안과 대조했다. 기존 RAG 서버 엔드포인트를 호출한 결과는 아니다.",
              "발견 사항은 checklist-audit.json에 보존했다. 명칭 묶음·조건부 서류·RFP 부속 증빙은 추가 검토 대상이다.", ""]
    for finding in audits:lines.append(f"- {finding['bid_no']}: {finding.get('anchor',finding.get('event',finding['kind']))} — {finding['note']}")
    lines += ["", "## X2 실측", "", "동일한 캐시된 정형 채점표·프로필에서 시작해 코드 실행과 실제 모델 도구 실행을 비교했다.",
      "공통 문서 추출·임베딩·인증·화면 비용은 양쪽에서 제외했다. 요청당 1회 측정이며 통계적 벤치마크는 아니다.", "",
      "| 항목 | 고정 코드 | X2 |", "| --- | ---: | ---: |",
      f"| 정답 초안과 항목 일치 | {measured['fixed_score_matches']}/{measured['score_items']} | {measured['x2_item_matches']}/{measured['score_items']} |",
      f"| 실행 시간 중앙값 | {measured['fixed_latency_median_ms']:.3f} ms | {measured['agent_latency_median_ms']/1000:.3f}초 |",
      f"| 15요청 합계 모델 비용 | $0 | ${measured['agent_cost_total_usd']:.6f} |",
      f"| 요청당 평균 모델 비용 | $0 | ${measured['agent_cost_mean_usd']:.6f} |", "",
      f"- 실제 모델: gpt-4o-2024-08-06. 완료 {measured['x2_complete']}/{measured['x2_cases']}조합.",
      f"- API 사용량: 입력 {measured['input_tokens']:,}, 출력 {measured['output_tokens']:,}토큰. 캐시 입력은 API 실측값으로 할인 반영.",
      "- 단가: 100만 토큰당 입력 $2.50, 캐시 입력 $1.25, 출력 $10.00.",
      "  [공식 모델 가격](https://developers.openai.com/api/docs/models/gpt-4o), 확인일 2026-10-23.",
      "- 이 사례에서는 X2가 정확도를 올리지 않았고 도구 실행 비용·시간이 추가됐다. 더 넓은 사례에 대한 일반화는 하지 않는다.", "",
      "## 아직 완료로 표시하지 않은 것", "",
      "1. 정답의 사람 검토: gold.json의 review는 전부 pending. AI가 사람 이름·검토일을 만들지 않았다.",
      "2. HWPX 3건의 PDF 쪽수 대조와 RFP 전체 제출 증빙·조건부 서류 대조.",
      "3. 실제 JWT·1~9단계·선택/승인·화면 E2E. X2는 선행 실측이며 핵심 E2E 이후 운영 검증이 필요.",
      "4. 3번 체크리스트 공급 경계에 원문 보정 함수를 연결했다. 실제 추출 캐시의 발견 문제 5/5를 재생 검증했으며, 운영 RAG·전체 원문 대조는 별도다.", "",
      "정답 검토용 상세 항목: [REVIEW.md](REVIEW.md). 재실행 방법: [README.md](../../bid_logic/README.md)."]
    (dataset/"REPORT.md").write_text("\n".join(lines)+"\n")
    detail=["# 원문 정답 초안 검토", "", "사람 검토 상태는 pending으로 보존한다. AI 최종 원문 대조 결과는 [FINAL_SOURCE_REVIEW.md](FINAL_SOURCE_REVIEW.md)를 참조한다.","",
            "AI 원문 재대조·수정 기록은 [SOURCE_REVIEW.md](SOURCE_REVIEW.md)를 참조한다. 추천 기준·60개 판정은 [RECOMMENDATION_REVIEW.md](RECOMMENDATION_REVIEW.md)에 기록하며 P@5는 AI 판정 기준의 잠정값이다.","",
            "## 추천 정답 초안", ""]
    for g in gold["recommendations"]:
        detail.append(f"- {g['profile_id']}: "+" / ".join(titles[x["bid_no"]] for x in g["relevant"]))
    detail += ["", "## 점수 손계산 초안", "", "| 공고 | 프로필 | 계산 항목 | 원문 기준 검산 |", "| --- | --- | --- | --- |"]
    item_names={(t["bid_no"],i["id"]):i["item"] for t in tables for i in t["items"]}
    for g in gold["scores"]:
        for i in g["items"]:
            if i["status"]=="calculated":detail.append(f"| {g['bid_no']} | {g['profile_id']} | {item_names[(g['bid_no'],i['id'])]} | {i['basis']} |")
    for table,checklist in zip(tables,checklists):
        no=table["bid_no"]
        detail += ["",f"## {no} — {titles[no]}","", "| 항목 | 종류 | 배점 | 출처 |", "| --- | --- | ---: | --- |"]
        def cite(refs):return "; ".join(f"{s['filename']} p.{s['page']}" if s.get("page") else f"{s['filename']} {s.get('locator')}" for s in refs)
        detail.extend(f"| {i['item']} | {i['kind']} | {i['max']} | {cite(i['sources'])} |" for i in table["items"])
        detail += ["","| 서류 | 기한 | 출처 |", "| --- | --- | --- |"]
        detail.extend(f"| {d['doc']} | {d['due'] or '미확인/별도 지정'} | {cite(d['sources'])} |" for d in checklist["documents"])
        detail += ["", "| 일정 | 일시 | 비고 |", "| --- | --- | --- |"]
        detail.extend(f"| {s['event']} | {s['due'] or '미확정'} | {'; '.join(s.get('notes',[]))} |" for s in checklist["schedule"])
    (dataset/"REVIEW.md").write_text("\n".join(detail)+"\n")
    print("Wrote REPORT.md, REVIEW.md, measurement-summary.json, checklist-audit.json")


if __name__=="__main__":review(Path("evaluation/real"),ROOT/"data/evaluation-source-20261023")
