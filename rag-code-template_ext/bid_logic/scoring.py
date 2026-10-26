"""C4: 출처가 있는 선언적 구간/등급표만 계산한다. eval이나 LLM 호출 없음."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_HALF_EVEN

from .common import calendar_date, check_scope, identity, number, require_sources

UNITS = {"KRW": Decimal(1), "천원": Decimal(1000), "백만원": Decimal(1000000),
         "억원": Decimal(100000000)}
ROUNDING = {"half_up": ROUND_HALF_UP, "down": ROUND_DOWN, "half_even": ROUND_HALF_EVEN}


def _metric_value(metric, profile):
    if not isinstance(metric, dict) or not isinstance(metric.get("field"), str):
        raise ValueError("계산 지표의 field가 필요합니다.")
    field = metric["field"]
    if field not in profile or profile[field] is None or profile[field] == "":
        return None, [field], {}
    raw = profile[field]
    if field != "track_records":
        # 금액형 일반 필드는 단위를 함께 전달한 경우에만 변환한다.
        if metric.get("unit") is not None:
            if not isinstance(raw, dict) or raw.get("value") is None or not raw.get("unit"):
                return None, [f"{field}.value/unit"], {field: raw}
            converted = number(raw["value"]) * UNITS[raw["unit"]] / UNITS[metric["unit"]]
            return converted, [], {field: raw, "metric": str(converted), "unit": metric["unit"]}
        return raw, [], {field: raw}
    if not isinstance(raw, list):
        raise ValueError("track_records는 배열이어야 합니다.")
    # 인정 기간은 원문에서 확정한 절대 날짜로 전달. 기간이 없으면 추정하지 않는다.
    start, end = calendar_date(metric["from"]), calendar_date(metric["to"])
    if start > end:
        raise ValueError("실적 인정 기간이 뒤집혔습니다.")
    records, missing = [], []
    for i, record in enumerate(raw):
        if not isinstance(record, dict):
            raise ValueError("실적 항목은 객체여야 합니다.")
        if not record.get("completed_at"):
            missing.append(f"track_records[{i}].completed_at")
            continue
        if not start <= calendar_date(record["completed_at"]) <= end:
            continue
        categories = metric.get("categories")
        if categories is not None:
            if not isinstance(categories, list) or any(not isinstance(c, str) for c in categories):
                raise ValueError("실적 인정 분야는 문자열 배열이어야 합니다.")
            if not record.get("category"):
                missing.append(f"track_records[{i}].category")
                continue
            if record["category"] not in categories:
                continue
        records.append(record)
    if metric["aggregate"] == "count":
        value = len(records)
    elif metric["aggregate"] == "sum":
        value = Decimal(0)
        for i, record in enumerate(records):
            if record.get("amount") is None or not record.get("amount_unit"):
                missing.append(f"track_records(인정대상)[{i}].amount/amount_unit")
                continue
            amount = number(record["amount"])
            if amount < 0:
                raise ValueError("실적 금액은 음수일 수 없습니다.")
            value += amount * UNITS[record["amount_unit"]]
        value /= UNITS[metric["unit"]]
    else:
        raise ValueError("지원하지 않는 실적 집계 방식입니다.")
    return value, missing, {"track_records": records, "metric": str(value)}


def _inside(value, band):
    lower, upper = band.get("min"), band.get("max")
    return ((lower is None or (value >= number(lower) if band.get("min_inclusive", True)
                              else value > number(lower))) and
            (upper is None or (value <= number(upper) if band.get("max_inclusive", False)
                              else value < number(upper))))


def _validate_bands(bands, maximum):
    if not isinstance(bands, list) or not bands or any(not isinstance(b, dict) for b in bands):
        raise ValueError("구간표가 없습니다.")
    for band in bands:
        for flag in ("min_inclusive", "max_inclusive"):
            if flag in band and not isinstance(band[flag], bool):
                raise ValueError("구간 경계 포함 여부는 boolean이어야 합니다.")
        score = number(band["score"])
        if not 0 <= score <= maximum:
            raise ValueError("배점 범위를 벗어난 점수입니다.")
        low, high = band.get("min"), band.get("max")
        if low is not None and high is not None:
            if number(low) > number(high) or (number(low) == number(high) and
                    not (band.get("min_inclusive", True) and band.get("max_inclusive", False))):
                raise ValueError("비어 있거나 뒤집힌 구간입니다.")
    # 어느 입력값에서든 중복 점수가 생기는 구간표는 계산하지 않는다.
    ordered = sorted(bands, key=lambda b: number(b["min"]) if b.get("min") is not None
                     else Decimal("-Infinity"))
    for left, right in zip(ordered, ordered[1:]):
        if left.get("max") is None or right.get("min") is None:
            raise ValueError("채점 구간이 겹칩니다.")
        high, low = number(left["max"]), number(right["min"])
        if high > low or (high == low and left.get("max_inclusive", False)
                          and right.get("min_inclusive", True)):
            raise ValueError("채점 구간이 겹칩니다.")


def _score(item, value, maximum):
    rule = item["rule"]
    if not isinstance(rule, dict):
        raise ValueError("채점 규칙은 객체여야 합니다.")
    if rule["type"] == "category":
        values = rule["values"]
        if not isinstance(values, dict) or not values or any(
                not 0 <= number(score) <= maximum for score in values.values()):
            raise ValueError("등급표의 점수가 배점 범위를 벗어났습니다.")
        if str(value) not in values:
            raise ValueError("원문 등급표에서 프로필 값을 찾을 수 없습니다.")
        result = number(values[str(value)])
    elif rule["type"] == "bands":
        _validate_bands(rule["bands"], maximum)
        matches = [b for b in rule["bands"] if _inside(number(value), b)]
        if len(matches) != 1:
            raise ValueError("적용할 단일 채점 구간이 없습니다.")
        result = number(matches[0]["score"])
    elif rule["type"] == "ratio":
        # 원문에 비례식이 있는 경우만 사용. 임의 수식 문자열은 실행하지 않는다.
        denominator = number(rule["denominator"])
        if denominator <= 0:
            raise ValueError("비례식 분모는 양수여야 합니다.")
        result = number(value) / denominator * number(rule["multiplier"])
        if rule.get("cap") is not None:
            cap = number(rule["cap"])
            if not 0 <= cap <= maximum:
                raise ValueError("상한이 배점 범위를 벗어났습니다.")
            result = min(result, cap)
    else:
        raise ValueError("지원하지 않는 계산 기준입니다.")
    if rule.get("rounding") is not None:
        rounding = rule["rounding"]
        if not isinstance(rounding, dict):
            raise ValueError("반올림 기준은 객체여야 합니다.")
        places = rounding["places"]
        if isinstance(places, bool) or not isinstance(places, int) or not 0 <= places <= 8:
            raise ValueError("소수 자릿수는 0~8이어야 합니다.")
        result = result.quantize(Decimal(1).scaleb(-places), rounding=ROUNDING[rounding["mode"]])
    if not 0 <= result <= maximum:
        raise ValueError("계산 결과가 배점 범위를 벗어났습니다.")
    return float(result)


def calculate_scores(table, profile, bid_no, revision):
    """총점 없는 {items, needs_review, missing_fields, questions} 반환."""
    check_scope(table, bid_no, revision)
    output, all_missing, seen = [], set(), set()
    for item in table["items"]:
        check_scope(item, bid_no, revision)
        item_id = item["id"]
        if item_id in seen:
            raise ValueError("채점 항목 id가 중복되었습니다.")
        seen.add(item_id)
        result = {"id": item_id, "item": item["item"], "max": item.get("max"),
                  "expected": "담당자 판단", "status": "manual", "needs_review": True,
                  "sources": item.get("sources", []), "basis": item.get("basis"),
                  "rule": item.get("rule"), "used_profile": {}, "missing_fields": []}
        if item.get("kind") in ("qualitative", "price"):
            result["reason"] = "정성·가격 항목은 담당자 판단"
        elif item.get("kind") != "quantitative":
            result["reason"] = "평가 항목 종류 미확인"
        elif not item.get("metric") or not item.get("rule"):
            note = item.get("rule_note") or "원문에서 계산 가능한 산정표를 확인하지 못했습니다."
            result["reason"] = f"계산 기준 확인 필요: {note}"
        else:
            try:
                require_sources(item)
                if not item.get("basis"):
                    raise ValueError("원문 채점 기준 설명이 없습니다.")
                maximum = number(item["max"])
                if maximum < 0:
                    raise ValueError("배점은 음수일 수 없습니다.")
                value, missing, used = _metric_value(item["metric"], profile)
                result["used_profile"] = used
                if missing:
                    result.update(status="missing_profile", missing_fields=missing,
                                  reason="점수 계산에 필요한 프로필 정보 부족")
                    all_missing.update(missing)
                else:
                    result.update(expected=_score(item, value, maximum), status="calculated",
                                  reason="원문 기준에 따라 코드로 계산한 예상 점수")
            except (ValueError, KeyError, TypeError, ArithmeticError) as error:
                result["reason"] = f"계산 기준 확인 필요: {error}"
        output.append(result)
    missing = sorted(all_missing)
    return {"bid_no": bid_no, "revision": revision, "items": output, "needs_review": True,
            "missing_fields": missing, "questions": [f"{field} 정보를 입력해 주세요." for field in missing]}
