"""자료 대기·독립 정답·오류 탐지 검증. 실제 공고 검증 실적이 아니다."""

import copy
from pathlib import Path
import tempfile
import unittest

from bid_logic.evaluate import FIXTURES, extracted_checklist, load_cases, scoring_table
from bid_logic.recommendation import load_bids_csv
from bid_logic.validation import evaluate_dataset, initialize_dataset, load_dataset


def synthetic_dataset():
    cases = load_cases()
    table = scoring_table(cases["scoring_templates"][0])
    extracted = extracted_checklist()
    scope = {"bid_no": "SYN-01", "revision": "00", "profile_id": "seoul_web"}
    review = {"status": "verified", "reviewer": "synthetic-test-review", "reviewed_at": cases["now"]}
    # 정답을 계산 함수에서 생성하지 않고 고정된 독립 검산 예시를 사용한다.
    answers = [("performance", 10, "calculated"), ("credit", 10, "calculated"),
               ("technical", "담당자 판단", "manual"), ("price", "담당자 판단", "manual")]
    items = [{"id": identifier, "expected": expected, "status": status,
              "basis": "가상 원문 기준 독립 검산: 2건 10점, AA 10점, 정성·가격 수동",
              "sources": copy.deepcopy(table["items"][0]["sources"])} for identifier, expected, status in answers]
    docs = [{"doc": "사업자등록증", "owned": True}, {"doc": "실적증명서", "owned": False}]
    for row in docs:
        row.update(due="2026-10-23T18:00:00+09:00", sources=copy.deepcopy(extracted["documents"][0]["sources"]))
    schedule = [{"event": "질의 마감", "due": "2026-10-23T18:00:00+09:00",
                 "sources": copy.deepcopy(extracted["schedule"][0]["sources"])}]
    return {"manifest": {"schema_version": 1, "dataset_kind": "synthetic", "now": cases["now"],
                         "from": cases["from"], "to": cases["to"],
                         "targets": {"bids": 1, "profiles": 1, "score_bids": 1}},
            "bids": load_bids_csv(FIXTURES / "bids.synthetic.csv")[:1], "profiles": cases["profiles"][:1],
            "scoring_tables": [table], "checklists": [extracted],
            "hits": [{"profile_id": "seoul_web", "hits": [{**{k: scope[k] for k in ("bid_no", "revision")},
                                                            "distance": 0.1}]}],
            "gold": {"recommendations": [{"profile_id": "seoul_web", "review": review,
                                           "rationale": "서울 SW·금액·마감 조건 일치하는 가상 공고",
                                           "relevant": [{"bid_no": "SYN-01", "revision": "00"}]}],
                     "scores": [{**scope, "items": items, "review": review}],
                     "checklists": [{**scope, "documents": docs, "schedule": schedule, "review": review}]}}


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.data = synthetic_dataset()

    def test_empty_real_template_is_pending_without_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            initialize_dataset(folder)
            report = evaluate_dataset(load_dataset(folder))
            self.assertEqual(report["status"], "incomplete")
            self.assertIsNone(report["metrics"])
            self.assertFalse(report["human_verified"])
            self.assertTrue(report["issues"])

    def test_init_never_overwrites_existing_work(self):
        with tempfile.TemporaryDirectory() as folder:
            initialize_dataset(folder)
            path = Path(folder) / "profiles.json"
            path.write_text('[{"id": "keep"}]', encoding="utf-8")
            with self.assertRaises(ValueError):
                initialize_dataset(folder)
            self.assertIn("keep", path.read_text(encoding="utf-8"))

    def test_full_synthetic_inputs_evaluate_but_are_not_human_real_evidence(self):
        result = evaluate_dataset(self.data)
        self.assertEqual(result["status"], "evaluated")
        self.assertEqual(result["metrics"]["quantitative_item_accuracy"], 1)
        self.assertFalse(result["human_verified"])
        self.assertIsNone(result["x2_comparison"])

    def test_unreviewed_gold_not_accepted(self):
        self.data["gold"]["scores"][0]["review"] = {"status": "pending"}
        result = evaluate_dataset(self.data)
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["metrics"])

    def test_score_mismatch_detected_by_item_id(self):
        gold = self.data["gold"]["scores"][0]["items"]
        gold.reverse()
        next(row for row in gold if row["id"] == "credit")["expected"] = 9
        result = evaluate_dataset(self.data)
        self.assertEqual(result["metrics"]["quantitative_item_accuracy"], 0.5)

    def test_wrong_gold_source_rejected(self):
        self.data["gold"]["scores"][0]["items"][0]["sources"][0]["revision"] = "01"
        with self.assertRaises(ValueError):
            evaluate_dataset(self.data)

    def test_missing_and_extra_documents_counted(self):
        self.data["checklists"][0]["documents"][0]["doc"] = "다른 서류"
        result = evaluate_dataset(self.data)
        docs = result["metrics"]["checklists"][0]["documents"]
        self.assertEqual(docs, {"missing": 1, "extra": 1})

    def test_wrong_owned_or_due_does_not_pass(self):
        for key, value in (("owned", False), ("due", "2026-10-24T18:00:00+09:00")):
            data = copy.deepcopy(self.data)
            data["gold"]["checklists"][0]["documents"][0][key] = value
            result = evaluate_dataset(data)
            self.assertEqual(result["metrics"]["checklists"][0]["documents"]["missing"], 1)

    def test_duplicate_profiles_or_case_pairs_rejected(self):
        for collection in (self.data["profiles"], self.data["gold"]["scores"]):
            collection.append(copy.deepcopy(collection[0]))
            with self.assertRaises(ValueError):
                evaluate_dataset(self.data)
            collection.pop()

    def test_missing_item_gold_not_silently_dropped(self):
        self.data["gold"]["scores"][0]["items"].pop()
        with self.assertRaises(ValueError):
            evaluate_dataset(self.data)

    def test_invalid_real_scale_rejected(self):
        self.data["manifest"]["dataset_kind"] = "real"
        with self.assertRaises(ValueError):
            evaluate_dataset(self.data)

    def test_score_scope_and_distance_must_match_inputs(self):
        self.data["hits"][0]["hits"][0]["distance"] = "NaN"
        with self.assertRaises(ValueError):
            evaluate_dataset(self.data)


if __name__ == "__main__":
    unittest.main()
