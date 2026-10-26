"""가짜 비동기 모델로만 실행 흐름 검증. 외부 LLM/토큰 비용 없음."""

import asyncio
import copy
import unittest

from bid_logic.agent_runner import run_scoring_agent
from bid_logic.evaluate import load_cases, scoring_table


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.messages = []

    async def __call__(self, messages, specs):
        self.messages.append(messages)
        return copy.deepcopy(next(self.responses))


def call(identifier, name, **arguments):
    return {"id": identifier, "name": name, "arguments": arguments}


def all_items():
    return {"tool_calls": [call("1", "calc_score", item_id="performance"),
                           call("2", "calc_score", item_id="credit"),
                           call("3", "mark_manual", item_id="technical", reason="정성 평가"),
                           call("4", "mark_manual", item_id="price", reason="가격 미정")]}


class AgentRunnerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cases = load_cases()
        self.table = scoring_table(cases["scoring_templates"][0])
        self.profile = copy.deepcopy(cases["profiles"][0])

    async def run_agent(self, model, **kwargs):
        return await run_scoring_agent(self.table, self.profile, "SYN-01", "00", model=model, **kwargs)

    async def test_only_tool_scores_authoritative(self):
        model = ScriptedModel([all_items(), {"content": "총점 999점이라고 주장해도 무시"}])
        result = await self.run_agent(model)
        self.assertEqual(result["status"], "complete")
        self.assertEqual([r["expected"] for r in result["items"]], [10, 10, "담당자 판단", "담당자 판단"])
        self.assertNotIn("total", result)
        self.assertIsNone(result["token_usage"])
        self.assertIsNone(result["cost"])

    async def test_rule_not_sent_to_model(self):
        model = ScriptedModel([all_items(), {}])
        result = await self.run_agent(model)
        tool_messages = [m for m in model.messages[-1] if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 4)
        for message in tool_messages:
            self.assertNotIn('"rule"', message["content"])
        # 최종 결과는 C4 고정 경로와 같은 키를 유지해 비교할 수 있어야 한다.
        self.assertIn("rule", result["items"][0])

    async def test_missing_profile_returns_questions(self):
        del self.profile["credit_rating"]
        result = await self.run_agent(ScriptedModel([all_items(), {}]))
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("credit_rating", result["missing_fields"])
        self.assertTrue(result["questions"])

    async def test_premature_finish_not_complete(self):
        result = await self.run_agent(ScriptedModel([{"content": "완료"}]))
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(len(result["unresolved_items"]), 4)

    async def test_tool_errors_return_to_model_then_recover(self):
        model = ScriptedModel([{"tool_calls": [call("bad", "calc_score", item_id="credit", score=999)]},
                               all_items(), {}])
        result = await self.run_agent(model)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["tool_calls"][0]["status"], "error")
        self.assertEqual(model.messages[1][-1]["role"], "tool")

    async def test_no_overwrite_completed_item(self):
        calls = all_items()
        calls["tool_calls"].append(call("5", "mark_manual", item_id="credit", reason="잘못 변경"))
        result = await self.run_agent(ScriptedModel([calls, {}]))
        self.assertEqual(result["items"][1]["expected"], 10)
        self.assertEqual(result["tool_calls"][-1]["status"], "error")

    async def test_max_rounds(self):
        result = await self.run_agent(ScriptedModel([{"tool_calls": [call("1", "get_profile")]}]), max_rounds=1)
        self.assertEqual(result["status"], "max_rounds")

    async def test_max_tool_calls_even_in_one_batch(self):
        result = await self.run_agent(ScriptedModel([all_items()]), max_tool_calls=2)
        self.assertEqual(result["status"], "max_tool_calls")
        self.assertEqual(len(result["items"]), 2)

    async def test_timeout(self):
        async def slow(messages, specs):
            await asyncio.sleep(1)
        result = await self.run_agent(slow, timeout_seconds=0.01)
        self.assertEqual(result["status"], "timeout")

    async def test_model_error_not_leaked(self):
        async def broken(messages, specs):
            raise RuntimeError("secret-credential")
        result = await self.run_agent(broken)
        self.assertEqual(result["status"], "model_error")
        self.assertNotIn("secret-credential", str(result))

    async def test_malformed_response(self):
        for response in ([], {"tool_calls": "bad"}, {"tool_calls": [{"id": "x"}]},
                         {"usage": {"input_tokens": -1, "output_tokens": 3}}):
            result = await self.run_agent(ScriptedModel([response]))
            self.assertEqual(result["status"], "invalid_response")

    async def test_report_only_supplied_usage(self):
        first = {**all_items(), "usage": {"input_tokens": 10, "output_tokens": 5}}
        result = await self.run_agent(ScriptedModel([first, {}]))
        self.assertEqual(result["token_usage"], {"input_tokens": 10, "output_tokens": 5, "complete": False})

    async def test_bad_configuration(self):
        for kwargs in ({"max_rounds": 0}, {"max_tool_calls": True}, {"timeout_seconds": float("nan")}):
            with self.assertRaises(ValueError):
                await self.run_agent(ScriptedModel([]), **kwargs)
        with self.assertRaises(ValueError):
            await self.run_agent(lambda *a: {})

    async def test_wrong_scope_before_model_calls(self):
        self.table["revision"] = "01"
        with self.assertRaises(ValueError):
            await self.run_agent(ScriptedModel([]))


if __name__ == "__main__":
    unittest.main()
