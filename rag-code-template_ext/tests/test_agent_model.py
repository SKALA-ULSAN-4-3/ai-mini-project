import asyncio
from types import SimpleNamespace as NS
import unittest

from bid_logic.agent_model import OpenAIChatModel, usage_cost
from bid_logic.agent_runner import run_scoring_agent
from bid_logic.evaluate import load_cases, scoring_table


class AdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_roundtrip_preserves_tool_ids_and_usage(self):
        cases=load_cases();table=scoring_table(cases["scoring_templates"][0]);requests=[]
        async def create(**request):
            requests.append(request)
            calls=[]
            if len(requests)==1:
                for item in table["items"]:
                    name="calc_score" if item["kind"]=="quantitative" else "mark_manual"
                    arguments='{"item_id":"'+item["id"]+'"'+(',"reason":"정성·가격"' if name=="mark_manual" else '')+'}'
                    calls.append(NS(id=item["id"],type="function",function=NS(name=name,arguments=arguments)))
            return NS(model="fixture-model",choices=[NS(message=NS(content=None,tool_calls=calls))],
                      usage=NS(prompt_tokens=100,completion_tokens=20,prompt_tokens_details=NS(cached_tokens=50)))
        client=NS(chat=NS(completions=NS(create=create)))
        adapter=OpenAIChatModel(client,model="fixture-model")
        result=await run_scoring_agent(table,cases["profiles"][0],table["bid_no"],table["revision"],model=adapter)
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["token_usage"]["input_tokens"],200)
        self.assertTrue(result["token_usage"]["complete"])
        assistant=next(m for m in requests[1]["messages"] if m["role"]=="assistant")
        self.assertEqual(assistant["tool_calls"][0]["type"],"function")
        self.assertIn("arguments",assistant["tool_calls"][0]["function"])
        self.assertFalse(requests[0]["store"])
        self.assertEqual(adapter.usage_records[0]["cached_input_tokens"],50)

    async def test_timeout_cancels_sdk_request(self):
        cancelled=[]
        async def create(**request):
            try:await asyncio.sleep(10)
            finally:cancelled.append(True)
        adapter=OpenAIChatModel(NS(chat=NS(completions=NS(create=create))))
        cases=load_cases();table=scoring_table(cases["scoring_templates"][0])
        result=await run_scoring_agent(table,cases["profiles"][0],table["bid_no"],table["revision"],
                                       model=adapter,timeout_seconds=0.01)
        self.assertEqual(result["status"],"timeout")
        self.assertEqual(cancelled,[True])
        self.assertIsNone(result["token_usage"])

    def test_cost_uses_actual_cached_input_and_incomplete_stays_unknown(self):
        rates=dict(input_per_million=2.5,output_per_million=10,cached_per_million=1.25)
        records=[{"input_tokens":1000000,"cached_input_tokens":500000,"output_tokens":100}]
        self.assertAlmostEqual(usage_cost(records,**rates),1.876)
        self.assertIsNone(usage_cost(records+[None],**rates))
