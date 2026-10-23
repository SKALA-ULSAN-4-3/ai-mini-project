"""X2 도구 계층 검증. LLM 호출 없이 합성 fixture만 사용한다."""

import copy
import unittest

from bid_logic import TOOL_SPECS, ScoringTools, calculate_scores
from bid_logic.agent_tools import VISIBLE_ITEM_FIELDS
from bid_logic.evaluate import load_cases, scoring_table


class ScoringToolsTest(unittest.TestCase):
    def setUp(self):
        self.cases = load_cases()
        self.table = scoring_table(self.cases["scoring_templates"][0])
        self.profile = copy.deepcopy(self.cases["profiles"][0])

    def tools(self, table=None, profile=None):
        source = self.table if table is None else table
        return ScoringTools(scoring_provider=lambda b, r: source,
                            profile_provider=lambda: self.profile if profile is None else profile,
                            bid_no="SYN-01", revision="00")

    def test_requires_providers_and_scope(self):
        for kwargs in ({"scoring_provider": None}, {"profile_provider": None},
                       {"bid_no": ""}, {"revision": " "}):
            base = {"scoring_provider": lambda b, r: self.table,
                    "profile_provider": lambda: self.profile,
                    "bid_no": "SYN-01", "revision": "00", **kwargs}
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                ScoringTools(**base)

    def test_table_hides_rule_and_metric(self):
        # 에이전트가 기준을 지어내지 못하도록 실행용 필드는 보여 주지 않는다.
        items = self.tools().get_scoring_table()["items"]
        self.assertEqual(len(items), 4)
        for item in items:
            self.assertEqual(set(item), set(VISIBLE_ITEM_FIELDS))
            self.assertNotIn("rule", item)
            self.assertNotIn("metric", item)

    def test_calc_score_matches_fixed_path(self):
        # X2 도구가 C4 고정 경로와 같은 점수를 내야 비교가 성립한다.
        fixed = calculate_scores(self.table, self.profile, "SYN-01", "00")
        tools = self.tools()
        for expected in fixed["items"]:
            if expected["status"] != "calculated":
                continue
            actual = tools.calc_score(expected["id"])
            self.assertEqual(actual["expected"], expected["expected"])
            self.assertEqual(actual["status"], "calculated")

    def test_calc_score_asks_when_profile_missing(self):
        del self.profile["credit_rating"]
        result = self.tools().calc_score("credit")
        self.assertEqual(result["status"], "missing_profile")
        self.assertEqual(result["expected"], "담당자 판단")
        self.assertIn("credit_rating", result["missing_fields"])
        self.assertTrue(result["questions"])

    def test_mark_manual_shape_matches_fixed_path(self):
        fixed = calculate_scores(self.table, self.profile, "SYN-01", "00")
        qualitative = next(x for x in fixed["items"] if x["id"] == "technical")
        manual = self.tools().mark_manual("technical", "제안서 작성 전이라 예측 불가")
        self.assertEqual(set(manual) - {"questions"}, set(qualitative))
        self.assertEqual(manual["expected"], "담당자 판단")
        self.assertEqual(manual["max"], 70)
        self.assertTrue(manual["needs_review"])

    def test_mark_manual_requires_reason(self):
        for reason in ("", "   ", None):
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                self.tools().mark_manual("technical", reason)

    def test_unknown_item_id_rejected(self):
        tools = self.tools()
        for item_id in ("없는항목", "", None):
            with self.subTest(item_id=item_id), self.assertRaises(ValueError):
                tools.calc_score(item_id)

    def test_missing_extraction_rejected(self):
        tools = ScoringTools(scoring_provider=lambda b, r: None,
                             profile_provider=lambda: self.profile,
                             bid_no="SYN-01", revision="00")
        with self.assertRaises(ValueError):
            tools.get_scoring_table()

    def test_scope_locked_to_one_bid(self):
        # 공급자에 전달되는 공고·차수는 생성 시점 값으로 고정된다.
        seen = []

        def provider(bid_no, revision):
            seen.append((bid_no, revision))
            return self.table

        tools = ScoringTools(scoring_provider=provider, profile_provider=lambda: self.profile,
                             bid_no="SYN-01", revision="00")
        tools.get_scoring_table()
        tools.calc_score("credit")
        self.assertEqual(set(seen), {("SYN-01", "00")})

    def test_table_fetched_once(self):
        calls = []
        tools = ScoringTools(scoring_provider=lambda b, r: calls.append(1) or self.table,
                             profile_provider=lambda: self.profile,
                             bid_no="SYN-01", revision="00")
        tools.get_scoring_table()
        tools.calc_score("credit")
        tools.mark_manual("price", "입찰가 미정")
        self.assertEqual(len(calls), 1)

    def test_calls_recorded(self):
        tools = self.tools()
        tools.get_scoring_table()
        tools.get_profile()
        tools.calc_score("credit")
        tools.mark_manual("price", "입찰가 미정")
        self.assertEqual([c["tool"] for c in tools.calls],
                         ["get_scoring_table", "get_profile", "calc_score", "mark_manual"])
        self.assertEqual(tools.calls[-1]["arguments"],
                         {"item_id": "price", "reason": "입찰가 미정"})

    def test_dispatch_runs_named_tool(self):
        tools = self.tools()
        self.assertEqual(tools.dispatch("calc_score", {"item_id": "credit"})["expected"], 10)
        self.assertEqual(tools.dispatch("get_scoring_table")["bid_no"], "SYN-01")

    def test_dispatch_rejects_unknown_tool_and_arguments(self):
        tools = self.tools()
        with self.assertRaises(ValueError):
            tools.dispatch("delete_everything", {})
        with self.assertRaises(ValueError):
            tools.dispatch("calc_score", {"item_id": "credit", "score": 10})
        with self.assertRaises(ValueError):
            tools.dispatch("calc_score", {})

    def test_tool_specs_cover_four_planned_tools(self):
        names = [spec["function"]["name"] for spec in TOOL_SPECS]
        self.assertEqual(names, ["get_scoring_table", "get_profile", "calc_score", "mark_manual"])
        for spec in TOOL_SPECS:
            self.assertEqual(spec["type"], "function")
            self.assertTrue(spec["function"]["description"])
            self.assertEqual(spec["function"]["parameters"]["type"], "object")

    def test_wrong_table_item_or_source_scope_rejected_for_every_item_tool(self):
        for location in ("table", "item", "source"):
            for method, arguments in (("get_scoring_table", ()), ("calc_score", ("credit",)),
                                      ("mark_manual", ("credit", "검토 필요"))):
                bad = copy.deepcopy(self.table)
                target = bad if location == "table" else bad["items"][0] if location == "item" else bad["items"][0]["sources"][0]
                target["revision"] = "01"
                with self.subTest(location=location, method=method), self.assertRaises(ValueError):
                    getattr(self.tools(table=bad), method)(*arguments)

    def test_duplicate_ids_and_invalid_items_rejected_before_tools_run(self):
        self.table["items"].append(copy.deepcopy(self.table["items"][0]))
        with self.assertRaises(ValueError):
            self.tools().get_scoring_table()

    def test_returned_data_cannot_modify_cached_rules_or_sources(self):
        tools = self.tools()
        shown = tools.get_scoring_table()
        shown["items"][0]["sources"][0]["revision"] = "bad"
        result = tools.calc_score("credit")
        result["rule"]["values"]["AA"] = 999
        self.assertEqual(tools.calc_score("credit")["expected"], 10)

    def test_profile_and_table_snapshots_survive_provider_mutation(self):
        tools = self.tools()
        result = tools.get_profile()
        result["track_records"].clear()
        self.profile["credit_rating"] = "B"
        tools.get_scoring_table()
        self.table["items"][1]["rule"]["values"]["AA"] = 999
        self.assertEqual(tools.calc_score("credit")["expected"], 10)
        self.assertEqual(len(tools.get_profile()["track_records"]), 2)

    def test_empty_nonobject_arguments_rejected(self):
        for arguments in ([], "", 0, False):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.tools().dispatch("get_profile", arguments)


if __name__ == "__main__":
    unittest.main()
