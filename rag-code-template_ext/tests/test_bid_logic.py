"""가상 원문 기준과 독립 정답으로 검증. API 키/DB/네트워크 불필요."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from bid_logic import build_checklist, calculate_scores, faiss_hits, load_bids_csv, recommend_bids
from bid_logic.evaluate import FIXTURES, extracted_checklist, load_cases, run_evaluation, scoring_table


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases()
        self.profile = copy.deepcopy(self.cases["profiles"][0])
        self.now = self.cases["now"]
        self.bids = load_bids_csv(FIXTURES / "bids.synthetic.csv")
        self.table = scoring_table(self.cases["scoring_templates"][0])

    def recommend(self, bids=None, **kwargs):
        return recommend_bids(bids if bids is not None else self.bids, self.profile,
                              "2026-10-01", "2026-10-31", now=self.now, **kwargs)

    def score(self):
        return calculate_scores(self.table, self.profile, "SYN-01", "00")

    def test_full_synthetic_evaluation(self):
        result = run_evaluation()
        self.assertEqual(result["score"]["cases"], 15)
        self.assertEqual(result["score"]["matched_items"], 30)
        self.assertFalse(result["human_verified"])
        self.assertTrue(all(not x for x in result["checklist"].values()))
        self.assertEqual([r["precision_at_5"] for r in result["recommendation"]], [0.6, 0.6, 0.4])

    def test_period_boundaries_and_deadline_equal_now(self):
        self.bids[1]["regions"] = []
        result = self.recommend()
        numbers = {b["bid_no"] for b in result["bids"]}
        self.assertIn("SYN-01", numbers)
        self.assertIn("SYN-02", numbers)
        self.assertNotIn("SYN-06", numbers)
        self.assertNotIn("SYN-07", numbers)

    def test_seoul_timezone(self):
        bid = self.bids[0]
        bid["deadline"] = "2026-10-23T01:00:00Z"
        self.assertEqual(len(self.recommend([bid])["bids"]), 0)

    def test_unknown_region_is_not_pass_or_rejection(self):
        bid = self.bids[0]
        bid["regions"] = None
        result = self.recommend([bid])["bids"][0]
        self.assertIn("regions 제한 미확인", result["unknown"])
        self.assertTrue(result["needs_review"])

    def test_missing_profile_distinct_from_empty(self):
        bid = self.bids[0]
        self.profile.pop("licenses")
        self.assertEqual(len(self.recommend([bid])["bids"]), 1)
        self.profile["licenses"] = []
        self.assertEqual(len(self.recommend([bid])["bids"]), 0)

    def test_explicit_unrestricted_ignores_missing_profile(self):
        self.profile.pop("licenses")
        result = self.recommend([self.bids[2]])["bids"][0]
        self.assertNotIn("프로필 licenses 미확인", result["unknown"])

    def test_mismatches_all_reported(self):
        bid = self.bids[0]
        bid.update(regions=["부산"], industries=["건설"], licenses=["건설"],
                   company_sizes=["대기업"], certs=["다른인증"], budget=900000000)
        reasons = self.recommend([bid])["excluded"][0]["reasons"]
        self.assertEqual(len(reasons), 6)

    def test_budget_boundaries(self):
        for budget in (100000000, 500000000):
            self.bids[0]["budget"] = budget
            self.assertEqual(len(self.recommend([self.bids[0]])["bids"]), 1)

    def test_missing_published_date_quarantined(self):
        self.bids[0]["published_at"] = None
        result = self.recommend([self.bids[0]])
        self.assertFalse(result["bids"])
        self.assertEqual(result["excluded"][0]["status"], "unknown")

    def test_invalid_period_budget_and_duplicate(self):
        with self.assertRaises(ValueError):
            recommend_bids([], {}, "2026-11-01", "2026-10-01")
        self.profile.update(budget_min=3, budget_max=2)
        with self.assertRaises(ValueError):
            self.recommend()
        self.profile.update(budget_min=0, budget_max=1000000000)
        with self.assertRaises(ValueError):
            self.recommend([self.bids[0], self.bids[0]])

    def test_chunk_aggregation_revision_and_tie(self):
        bid = self.bids[0]
        newer = {**bid, "revision": "01"}
        hits = [{"bid_no": "SYN-01", "revision": "00", "distance": 0.9},
                {"bid_no": "SYN-01", "revision": "00", "distance": 0.1},
                {"bid_no": "SYN-01", "revision": "01", "distance": 0.1}]
        result = self.recommend([newer, bid], hits=hits)["bids"]
        self.assertEqual([r["revision"] for r in result], ["00", "01"])
        self.assertEqual(result[0]["distance"], 0.1)

    def test_search_sees_only_filtered_candidates(self):
        def search(query, allowed):
            self.assertIn("웹", query)
            self.assertEqual(allowed, {("SYN-01", "00"), ("SYN-03", "00"), ("SYN-05", "00")})
            return []
        self.recommend(search=search)

    def test_faiss_reads_all_chunks(self):
        class Store:
            index = SimpleNamespace(ntotal=10)
            def similarity_search_with_score(inner, query, k):
                self.assertEqual(k, 10)
                return [(SimpleNamespace(metadata={"bid_no": "SYN-01", "revision": "00"}), 0.2)]
        self.assertEqual(len(faiss_hits(Store(), "웹", {("SYN-01", "00")})), 1)

    def test_legacy_metadata_rejected(self):
        with self.assertRaises(RuntimeError):
            faiss_hits(None, "웹", {("SYN-01", "00")})
        store = SimpleNamespace(index=SimpleNamespace(ntotal=1),
                                similarity_search_with_score=lambda *a, **k: [
                                    (SimpleNamespace(metadata={"source": "old.pdf"}), 0.2)])
        with self.assertRaises(ValueError):
            faiss_hits(store, "웹", {("SYN-01", "00")})

    def test_invalid_distance(self):
        for distance in (-1, "NaN", "Infinity"):
            with self.subTest(distance=distance), self.assertRaises(ValueError):
                self.recommend(hits=[{"bid_no": "SYN-01", "revision": "00", "distance": distance}])

    def test_csv_bom_and_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bids.csv"
            path.write_text('\ufeffbid_no,revision,regions\nX,00,null\n', encoding="utf-8")
            row = load_bids_csv(path)[0]
            self.assertEqual(row["revision"], "00")
            self.assertIsNone(row["regions"])

    def test_no_total_and_manual_items(self):
        result = self.score()
        self.assertNotIn("total", result)
        self.assertTrue(result["needs_review"])
        self.assertEqual([x["expected"] for x in result["items"]], [10, 10, "담당자 판단", "담당자 판단"])

    def test_missing_profile_not_zero(self):
        del self.profile["credit_rating"]
        self.profile["track_records"][0].pop("completed_at")
        result = self.score()
        self.assertIn("credit_rating", result["missing_fields"])
        self.assertEqual(result["items"][0]["status"], "missing_profile")
        self.assertEqual(result["items"][1]["expected"], "담당자 판단")
        self.assertTrue(result["questions"])

    def test_performance_period_and_category(self):
        self.profile["track_records"].extend([
            {"completed_at": "2023-12-31", "category": "SW"},
            {"completed_at": "2026-10-24", "category": "SW"},
            {"completed_at": "2026-10-23", "category": "건설"}])
        self.assertEqual(self.score()["items"][0]["used_profile"]["metric"], "2")

    def test_performance_date_inclusive(self):
        self.profile["track_records"] = [
            {"completed_at": "2024-01-01", "category": "SW"},
            {"completed_at": "2026-10-23", "category": "SW"}]
        self.assertEqual(self.score()["items"][0]["expected"], 10)

    def test_missing_amount_unit_not_assumed(self):
        self.table = scoring_table(self.cases["scoring_templates"][1])
        del self.profile["track_records"][0]["amount_unit"]
        result = calculate_scores(self.table, self.profile, "SYN-02", "00")
        self.assertEqual(result["items"][0]["status"], "missing_profile")

    def test_no_source_no_scoring(self):
        self.table["items"][0]["sources"] = []
        self.assertEqual(self.score()["items"][0]["status"], "manual")

    def test_cross_revision_rejected_including_source(self):
        for target in (self.table, self.table["items"][0], self.table["items"][0]["sources"][0]):
            target["revision"] = "01"
            with self.assertRaises(ValueError):
                self.score()
            target["revision"] = "00"

    def test_overlapping_or_out_of_range_rules_manual(self):
        item = self.table["items"][0]
        item["rule"]["bands"][0]["max"] = 5
        self.assertEqual(self.score()["items"][0]["status"], "manual")
        item["rule"] = {"type": "category", "values": {"2": 11}}
        self.assertEqual(self.score()["items"][0]["status"], "manual")

    def test_gap_and_unknown_rating_manual(self):
        self.table["items"][0]["rule"]["bands"] = [{"min": 100, "score": 10}]
        self.profile["credit_rating"] = "unknown"
        self.assertTrue(all(r["status"] == "manual" for r in self.score()["items"]))

    def test_ratio_rounding_cap_and_no_invented_rounding(self):
        item = self.table["items"][0]
        item["metric"] = {"field": "ratio_input"}
        self.profile["ratio_input"] = 2
        item["rule"] = {"type": "ratio", "denominator": 3, "multiplier": 10,
                        "cap": 10, "rounding": {"places": 2, "mode": "half_up"}}
        self.assertEqual(self.score()["items"][0]["expected"], 6.67)
        self.profile["ratio_input"] = 4
        self.assertEqual(self.score()["items"][0]["expected"], 10)
        item["rule"]["denominator"] = 0
        self.assertEqual(self.score()["items"][0]["status"], "manual")

    def test_input_not_mutated(self):
        original = copy.deepcopy([self.bids, self.profile, self.table])
        self.recommend()
        self.score()
        self.assertEqual([self.bids, self.profile, self.table], original)

    def test_direct_amount_unit_conversion(self):
        item = self.table["items"][0]
        item["metric"] = {"field": "revenue", "unit": "KRW"}
        item["rule"] = {"type": "bands", "bands": [{"min": 150000000, "score": 10}]}
        self.profile["revenue"] = {"value": 150, "unit": "백만원"}
        self.assertEqual(self.score()["items"][0]["expected"], 10)
        self.profile["revenue"] = 150
        self.assertEqual(self.score()["items"][0]["status"], "missing_profile")

    def test_malformed_extracted_rules_require_manual(self):
        item = self.table["items"][0]
        for rule in ([], {"type": "category", "values": []},
                     {"type": "bands", "bands": [None]},
                     {"type": "bands", "bands": [{"score": 1, "min_inclusive": "false"}]}):
            item["rule"] = rule
            self.assertEqual(self.score()["items"][0]["status"], "manual")

    def test_negative_budget_and_empty_credit(self):
        self.profile["budget_min"] = -1
        with self.assertRaises(ValueError):
            self.recommend()
        self.profile["credit_rating"] = ""
        self.assertEqual(self.score()["items"][1]["status"], "missing_profile")

    def test_negative_bid_budget_rejected(self):
        # 음수 공고 금액을 미확인으로 넘기면 금액 필터 없이 추천되므로 거부한다.
        self.bids[0]["budget"] = "-5"
        with self.assertRaises(ValueError):
            self.recommend()

    def test_unreadable_bid_budget_stays_unknown(self):
        self.bids[0]["budget"] = "미정"
        result = self.recommend()
        row = next(b for b in result["bids"] if b["bid_no"] == "SYN-01")
        self.assertIn("금액 비교 정보 미확인", row["unknown"])

    def test_csv_negative_budget_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bids.csv"
            path.write_text("bid_no,revision,budget\nX,00,-5\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_bids_csv(path)

    def test_raw_restriction_not_silently_interpreted(self):
        self.bids[0]["licenses"] = [{"all": ["A", "B"]}]
        with self.assertRaises(ValueError):
            self.recommend()

    def checklist(self, extracted=None, **kwargs):
        return build_checklist(extracted or extracted_checklist(), self.profile, "SYN-01", "00",
                               now=self.now, **kwargs)

    def test_owned_is_not_submitted(self):
        row = self.checklist()["documents"][0]
        self.assertTrue(row["owned"])
        self.assertFalse(row["submitted"])
        self.assertEqual(row["d_day"], 0)
        self.assertEqual(row["remaining_seconds"], 8 * 3600)
        self.assertEqual(row["status"], "upcoming")

    def test_similar_doc_not_owned(self):
        self.profile["owned_docs"] = ["사업자등록증 사본", "실적 확인서"]
        self.assertFalse(any(r["owned"] for r in self.checklist()["documents"]))

    def test_explicit_alias(self):
        self.profile["owned_docs"] = ["사업자등록 증명"]
        result = self.checklist(aliases={"사업자등록 증명": "사업자등록증"})
        self.assertTrue(result["documents"][0]["owned"])

    def test_unknown_owned_docs(self):
        self.profile["owned_docs"] = None
        self.assertIsNone(self.checklist()["documents"][0]["owned"])

    def test_missing_date_date_only_expired_and_timezone(self):
        extracted = extracted_checklist()
        for value, status in ((None, "unknown"), ("2026-10-23", "needs_review"),
                              ("2026-10-23T09:59:59+09:00", "expired"),
                              ("2026-10-23T01:00:00Z", "expired")):
            extracted["documents"][0]["due"] = value
            row = self.checklist(extracted)["documents"][0]
            self.assertEqual(row["status"], status)
            if status == "expired":
                self.assertEqual(row["remaining_seconds"], 0)

    def test_checklist_source_and_scope(self):
        extracted = extracted_checklist()
        extracted["documents"][0]["sources"][0]["revision"] = "01"
        with self.assertRaises(ValueError):
            self.checklist(extracted)
        extracted = extracted_checklist()
        extracted["documents"][0]["sources"] = []
        with self.assertRaises(ValueError):
            self.checklist(extracted)


if __name__ == "__main__":
    unittest.main()
