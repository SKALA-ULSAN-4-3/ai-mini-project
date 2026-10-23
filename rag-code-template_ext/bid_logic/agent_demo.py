"""합성 데이터·가짜 모델로 X2 실행기 동작을 시연. 실제 성능 비교가 아니다."""

import argparse
import asyncio
import json
from pathlib import Path

from .agent_runner import run_scoring_agent
from .evaluate import load_cases, scoring_table


async def run_demo():
    cases = load_cases()
    table = scoring_table(cases["scoring_templates"][0])
    round_number = 0

    async def fake_model(messages, specs):
        nonlocal round_number
        round_number += 1
        if round_number == 1:
            return {"tool_calls": [{"id": "table", "name": "get_scoring_table", "arguments": {}},
                                   {"id": "profile", "name": "get_profile", "arguments": {}}]}
        if round_number == 2:
            return {"tool_calls": [{"id": item["id"],
                                    "name": "calc_score" if item["kind"] == "quantitative" else "mark_manual",
                                    "arguments": {"item_id": item["id"], **(
                                        {} if item["kind"] == "quantitative" else {"reason": "정성·가격 항목"})}}
                                   for item in table["items"]]}
        return {"content": "가짜 모델 실행 종료"}

    result = await run_scoring_agent(table, cases["profiles"][0], "SYN-01", "00", model=fake_model)
    return {"dataset_kind": "synthetic", "model_kind": "scripted_fake", "actual_llm_called": False,
            "human_verified": False, "x2_comparison": None, "result": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="X2 오프라인 시연: 실제 LLM 호출 없음")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run_demo())
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["result"]["status"] != "complete":
        raise SystemExit(1)
