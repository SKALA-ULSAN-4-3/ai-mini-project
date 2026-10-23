"""OpenAI Chat Completions와 내부 비동기 도구 실행기 사이의 어댑터.

SDK import와 인증은 실제 연결 시점에만 수행한다. 자유 서술은 점수로 사용하지 않는다.
"""
from copy import deepcopy
import json


class OpenAIChatModel:
    def __init__(self, client, *, model="gpt-4o", timeout=45):
        self.client, self.model, self.timeout = client, model, timeout
        self.usage_records = []
        self.response_models = []

    async def __call__(self, messages, tool_specs):
        outgoing = []
        for message in deepcopy(messages):
            if message.get("role") == "assistant" and "tool_calls" in message:
                message["tool_calls"] = [
                    {"id": call["id"], "type": "function", "function": {
                        "name": call["name"], "arguments": call["arguments"] if isinstance(
                            call["arguments"], str) else json.dumps(call["arguments"], ensure_ascii=False)}}
                    for call in message["tool_calls"]]
            outgoing.append(message)
        result = await self.client.chat.completions.create(
            model=self.model, messages=outgoing, tools=tool_specs, tool_choice="auto",
            temperature=0, timeout=self.timeout, max_completion_tokens=4096, store=False)
        if len(result.choices) != 1:
            raise ValueError("모델 응답은 한 개여야 합니다.")
        message = result.choices[0].message
        calls = []
        for call in message.tool_calls or []:
            if call.type != "function":
                raise ValueError("지원하지 않는 모델 도구 형식입니다.")
            calls.append({"id": call.id, "name": call.function.name, "arguments": call.function.arguments})
        usage = None
        if result.usage is not None:
            usage = {"input_tokens": result.usage.prompt_tokens, "output_tokens": result.usage.completion_tokens}
            details = getattr(result.usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) or 0
            self.usage_records.append({**usage, "cached_input_tokens": cached})
        else:
            self.usage_records.append(None)
        self.response_models.append(result.model)
        return {"content": message.content or "", "tool_calls": calls, "usage": usage}


def usage_cost(records, *, input_per_million, output_per_million, cached_per_million):
    """측정 사용량 전부가 있을 때만 USD 비용을 계산한다. 단가는 호출자가 명시한다."""
    if not records or any(row is None for row in records):
        return None
    return sum(((row["input_tokens"] - row["cached_input_tokens"]) * input_per_million
                + row["cached_input_tokens"] * cached_per_million
                + row["output_tokens"] * output_per_million) / 1_000_000 for row in records)
