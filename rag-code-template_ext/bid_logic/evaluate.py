"""실제 API 호출 없는 합성 fixture 평가. python -m bid_logic.evaluate"""

import argparse
import json
from pathlib import Path
from time import perf_counter

from . import build_checklist, calculate_scores, load_bids_csv, recommend_bids

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def load_cases():
    return json.loads((FIXTURES / "synthetic_cases.json").read_text(encoding="utf-8"))


def scoring_table(template):
    """가상 문서 추출 결과 구성. 정답 점수는 별도 JSON에 수기로 고정되어 있다."""
    scope = {"bid_no": template["bid_no"], "revision": template["revision"]}
    source = {**scope, "filename": "SYNTHETIC-RFP.txt", "page": 1,
              "collected_at": "2026-10-23", "dataset_kind": "synthetic"}
    common = {**scope, "kind": "quantitative", "max": 10,
              "basis": template["basis"], "sources": [source]}
    metric = {"field": "track_records", "aggregate": template["metric"], "unit": "KRW",
              "from": "2024-01-01", "to": "2026-10-23", "categories": ["SW"]}
    return {**scope, "items": [
        {**common, "id": "performance", "item": "수행 실적", "metric": metric,
         "rule": {"type": "bands", "bands": template["bands"]}},
        {**common, "id": "credit", "item": "신용등급", "metric": {"field": "credit_rating"},
         "rule": {"type": "category", "values": template["ratings"]}},
        {**scope, "id": "technical", "item": "기술 제안", "kind": "qualitative", "max": 70,
         "sources": [source]},
        {**scope, "id": "price", "item": "가격", "kind": "price", "max": 10, "sources": [source]},
    ]}


def extracted_checklist():
    scope = {"bid_no": "SYN-01", "revision": "00"}
    source = {**scope, "filename": "SYNTHETIC-RFP.txt", "page": 2, "dataset_kind": "synthetic"}
    common = {**scope, "sources": [source], "due": "2026-10-23T18:00:00+09:00"}
    return {**scope, "documents": [
        {**common, "id": "registration", "doc": "사업자 등록증"},
        {**common, "id": "performance", "doc": "실적증명서"}],
        "schedule": [{**common, "id": "question", "event": "질의 마감"}]}


def run_evaluation():
    cases = load_cases()
    bids = load_bids_csv(FIXTURES / "bids.synthetic.csv")
    profiles = {p["id"]: p for p in cases["profiles"]}
    tables = {t["bid_no"]: scoring_table(t) for t in cases["scoring_templates"]}
    recommendation = []
    for profile_id, profile in profiles.items():
        hits = [{"bid_no": bid_no, "revision": "00", "distance": distance}
                for bid_no, distance in cases["distances"][profile_id].items()]
        result = recommend_bids(bids, profile, cases["from"], cases["to"], now=cases["now"], hits=hits)
        actual = [b["bid_no"] for b in result["bids"]]
        gold = set(cases["recommendation_gold_draft"][profile_id])
        matched = len(set(actual) & gold)
        recommendation.append({"profile_id": profile_id, "actual": actual,
                               "matched": matched, "returned": len(actual),
                               "precision_at_5": matched / 5,
                               "precision_returned": matched / len(actual) if actual else 0,
                               "gold_recall": matched / len(gold) if gold else None})
    evaluations, matched, latency = [], 0, []
    for gold in cases["score_gold_draft"]:
        started = perf_counter()
        response = calculate_scores(tables[gold["bid_no"]], profiles[gold["profile_id"]],
                                    gold["bid_no"], "00")
        latency.append((perf_counter() - started) * 1000)
        actual = [row["expected"] for row in response["items"][:2]]
        count = sum(row["status"] == "calculated" and row["expected"] == expected
                    for row, expected in zip(response["items"][:2], gold["expected"]))
        matched += count
        evaluations.append({**gold, "actual": actual, "matched_items": count,
                            "human_verified": False})
    checklist = build_checklist(extracted_checklist(), profiles["seoul_web"], "SYN-01", "00",
                                now=cases["now"])
    # 원문에 해당하는 고정 fixture와 비교. 실제 PDF 추출 정확도가 아니다.
    from .checklist import document_key
    doc_gold = {document_key(x) for x in cases["checklist_gold_draft"]["documents"]}
    doc_actual = {document_key(x["doc"]) for x in checklist["documents"]}
    schedule_gold = set(cases["checklist_gold_draft"]["schedule"])
    schedule_actual = {x["event"] for x in checklist["schedule"]}
    return {"dataset_kind": "synthetic", "human_verified": False,
            "recommendation": recommendation,
            "score": {"cases": len(evaluations), "quantitative_items": len(evaluations) * 2,
                      "matched_items": matched, "accuracy": matched / (len(evaluations) * 2),
                      "mean_logic_latency_ms": sum(latency) / len(latency), "details": evaluations},
            "checklist": {"missing_docs": sorted(doc_gold - doc_actual),
                          "extra_docs": sorted(doc_actual - doc_gold),
                          "missing_events": sorted(schedule_gold - schedule_actual),
                          "extra_events": sorted(schedule_actual - schedule_gold)},
            "cost_scope": "합성 거리·구조화 입력. 외부 LLM/임베딩 호출 없음. 전체 RAG 비용은 미측정.",
            "x2": {"status": "pending_core_e2e", "comparison": None}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="합성 fixture 검증: 실제 공고 평가 아님")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_evaluation()
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["score"]["accuracy"] != 1 or any(report["checklist"].values()) or any(
            r["gold_recall"] != 1 or r["precision_returned"] != 1 for r in report["recommendation"]):
        raise SystemExit(1)
