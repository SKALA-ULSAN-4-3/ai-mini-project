"""X2 사전 준비: 주입한 비동기 모델로 Tool Calling 흐름을 실행한다.

LLM SDK/네트워크/운영 API를 연결하지 않는다. 읽어 둔 데이터의 스냅샷만 사용한다.
모델 어댑터 계약과 오프라인 실행 예시는 HANDOFF.md에 정의한다.
"""

import asyncio
from copy import deepcopy
import inspect
import json
import math
from time import perf_counter

from .agent_tools import ScoringTools, TOOL_SPECS


async def run_scoring_agent(table, profile, bid_no, revision, *, model,
                            max_rounds=8, max_tool_calls=20, timeout_seconds=10):
    """전체 시간/모델 호출/도구 호출 예산을 제한한다. 최종 점수는 도구 결과만 사용.

    model(messages, tool_specs)는 async 함수이고 정규화된 dict를 반환해야 한다.
    데이터 공급 I/O는 호출 전에 끝내야 한다. model은 취소를 준수해야 한다.
    """
    if not (inspect.iscoroutinefunction(model) or
            inspect.iscoroutinefunction(getattr(model, "__call__", None))):
        raise ValueError("model은 취소 가능한 비동기 함수여야 합니다.")
    for name, value in (("max_rounds", max_rounds), ("max_tool_calls", max_tool_calls)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name}는 양의 정수여야 합니다.")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not (
            math.isfinite(timeout_seconds) and timeout_seconds > 0):
        raise ValueError("timeout_seconds는 양의 유한한 숫자여야 합니다.")
    started = perf_counter()
    table, profile = deepcopy(table), deepcopy(profile)
    tools = ScoringTools(scoring_provider=lambda *a: table, profile_provider=lambda: profile,
                         bid_no=bid_no, revision=revision)
    # 최초에 전체 범위/프로필을 검증하고 이후에는 외부 I/O 없이 같은 입력을 사용한다.
    tools._table()
    tools._profile()
    order = [item["id"] for item in table["items"]]
    if not order:
        raise ValueError("채점할 항목이 없습니다.")
    messages = [{"role": "system", "content": (
        "공고 채점 보조다. get_scoring_table/get_profile로 확인하고 각 항목에 calc_score 또는 "
        "mark_manual을 호출하라. 점수와 기준을 만들지 말고 정성·가격은 담당자 판단으로 넘겨라. "
        "부족한 프로필은 도구가 반환한 질문으로 확인한다. 모든 항목 처리 후 종료하라.")},
        {"role": "user", "content": json.dumps({"bid_no": bid_no, "revision": revision}, ensure_ascii=False)}]
    resolved, events, usage_records = {}, [], []
    model_calls, tool_calls = 0, 0
    seen_call_ids = set()

    def finish(status):
        items = [resolved[item_id] for item_id in order if item_id in resolved]
        missing = sorted({field for item in items for field in item.get("missing_fields", [])})
        questions = list(dict.fromkeys(q for item in items for q in item.get("questions", [])))
        measured_usage = [u for u in usage_records if u is not None]
        usage = None
        if measured_usage:
            usage = {name: sum(u[name] for u in measured_usage)
                     for name in ("input_tokens", "output_tokens")}
            usage["complete"] = len(measured_usage) == model_calls
        return {"bid_no": tools.bid_no, "revision": tools.revision, "items": deepcopy(items),
                "needs_review": True, "missing_fields": missing, "questions": questions,
                "status": status, "unresolved_items": [i for i in order if i not in resolved],
                "tool_calls": deepcopy(events), "model_calls": model_calls,
                "latency_ms": (perf_counter() - started) * 1000,
                "token_usage": usage, "cost": None}

    for _ in range(max_rounds):
        remaining = timeout_seconds - (perf_counter() - started)
        if remaining <= 0:
            return finish("timeout")
        model_calls += 1
        try:
            response = await asyncio.wait_for(model(deepcopy(messages), deepcopy(TOOL_SPECS)), remaining)
        except asyncio.TimeoutError:
            return finish("timeout")
        except Exception:
            # 연결 대상의 예외 원문에 인증 정보가 있을 수 있으므로 그대로 반환하지 않는다.
            return finish("model_error")
        if not isinstance(response, dict):
            return finish("invalid_response")
        usage = response.get("usage")
        if usage is not None and (not isinstance(usage, dict) or any(
                isinstance(usage.get(k), bool) or not isinstance(usage.get(k), int) or usage[k] < 0
                for k in ("input_tokens", "output_tokens"))):
            return finish("invalid_response")
        usage_records.append(usage)
        calls = response.get("tool_calls", [])
        if not isinstance(calls, list) or not isinstance(response.get("content", ""), str):
            return finish("invalid_response")
        if not calls:
            if len(resolved) != len(order):
                return finish("incomplete")
            return finish("needs_input" if any(r.get("missing_fields") for r in resolved.values()) else "complete")
        # 잘못된 배치를 부분 실행하지 않도록 도구 호출 형식을 먼저 확인한다.
        ids = set()
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("id"), str) or not call["id"] or (
                    call["id"] in ids or call["id"] in seen_call_ids) or not isinstance(call.get("name"), str):
                return finish("invalid_response")
            ids.add(call["id"])
        seen_call_ids.update(ids)
        messages.append({"role": "assistant", "content": response.get("content", ""),
                         "tool_calls": deepcopy(calls)})
        for call in calls:
            if perf_counter() - started >= timeout_seconds:
                return finish("timeout")
            if tool_calls >= max_tool_calls:
                return finish("max_tool_calls")
            tool_calls += 1
            arguments = call.get("arguments", {})
            try:
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("도구 인자는 객체여야 합니다.")
                item_id = arguments.get("item_id")
                if call["name"] in ("calc_score", "mark_manual") and item_id in resolved:
                    raise ValueError("이미 처리한 항목을 덮어쓸 수 없습니다.")
                result = tools.dispatch(call["name"], arguments)
                if call["name"] in ("calc_score", "mark_manual"):
                    resolved[result["id"]] = deepcopy(result)
                event = {"id": call["id"], "tool": call["name"], "arguments": deepcopy(arguments),
                         "status": "ok", "result_status": result.get("status")}
            except (ValueError, KeyError, TypeError):
                result = {"error": "도구 이름·인자·공고 범위를 확인해 주세요."}
                event = {"id": call["id"], "tool": call["name"], "status": "error"}
            events.append(event)
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
    return finish("max_rounds")
