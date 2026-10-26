"""C4: 출처가 있는 선언적 구간/등급표만 계산한다. eval이나 LLM 호출 없음."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_HALF_EVEN

from .common import calendar_date, check_scope, identity, number, require_sources

UNITS = {"KRW": Decimal(1), "천원": Decimal(1000), "백만원": Decimal(1000000),
         "억원": Decimal(100000000)}
ROUNDING = {"half_up": ROUND_HALF_UP, "down": ROUND_DOWN, "half_even": ROUND_HALF_EVEN}


def _filter_record(record, filters, prefix):
    missing = []
    for field, allowed in filters.items():
        if field not in record or record[field] is None:
            missing.append(f"{prefix}.{field}")
        elif str(record[field]).lower() not in [str(v).lower() for v in allowed]:
            return False, []
    return not missing, missing


def _period_date(metric, profile, name):
    if metric.get(name + "_reference") == "notice_date":
        if not profile.get("notice_date"):
            return None, ["notice_date"]
        return calendar_date(profile["notice_date"]), []
    return calendar_date(metric[name]), []


def _metric_value(metric, profile):
    if not isinstance(metric, dict) or not isinstance(metric.get("field"), str):
        raise ValueError("계산 지표의 field가 필요합니다.")
    field = metric["field"]
    if field not in profile or profile[field] is None or profile[field] == "":
        return None, [field], {}
    raw = profile[field]
    if field == "credit_rating" and (metric.get("credit_valid_on_notice") or metric.get("credit_max_age_months")):
        required = ["notice_date", "credit_rating_issued_at"]
        if metric.get("credit_valid_on_notice"):
            required.append("credit_rating_valid_until")
        missing = [f for f in required if not profile.get(f)]
        if missing:
            return None, missing, {}
        notice = calendar_date(profile["notice_date"])
        issued = calendar_date(profile["credit_rating_issued_at"])
        if issued > notice:
            raise ValueError("공고일 이후 발급된 신용등급입니다. 인정 가능한 확인서를 확인해 주세요.")
        if metric.get("credit_valid_on_notice") and calendar_date(profile["credit_rating_valid_until"]) < notice:
            raise ValueError("공고일 기준 신용등급 유효기간이 만료되었습니다.")
        if metric.get("credit_max_age_months"):
            from calendar import monthrange
            months = notice.year * 12 + notice.month - 1 - metric["credit_max_age_months"]
            year, month0 = divmod(months, 12)
            oldest = notice.replace(year=year, month=month0 + 1,
                day=min(notice.day, monthrange(year, month0 + 1)[1]))
            if issued < oldest:
                raise ValueError("신용등급 발급일이 원문에서 정한 인정기간을 벗어났습니다.")
    if field == "personnel":
        if not isinstance(raw, list):
            raise ValueError("personnel은 전문인력 증빙 정보 배열이어야 합니다.")
        records, missing = [], []
        as_of = None
        if metric.get("as_of_reference") == "notice_date":
            if not profile.get("notice_date"):
                return None, ["notice_date"], {}
            as_of = calendar_date(profile["notice_date"])
        for i, record in enumerate(raw):
            if not isinstance(record, dict):
                raise ValueError("전문인력 항목은 객체여야 합니다.")
            accepted, fields = _filter_record(record, metric.get("filters", {}), f"personnel[{i}]")
            missing.extend(fields)
            if not accepted:
                continue
            if as_of is not None:
                if not record.get("employed_from"):
                    missing.append(f"personnel[{i}].employed_from")
                    continue
                if calendar_date(record["employed_from"]) > as_of:
                    continue
                if record.get("employed_to") and calendar_date(record["employed_to"]) < as_of:
                    continue
            records.append(record)
        return len(records), missing, {"personnel": records, "metric": str(len(records))}
    if field != "track_records":
        # 금액형 일반 필드는 단위를 함께 전달한 경우에만 변환한다.
        if metric.get("unit") is not None:
            if not isinstance(raw, dict) or raw.get("value") is None or not raw.get("unit"):
                return None, [f"{field}.value/unit"], {field: raw}
            converted = number(raw["value"]) * UNITS[raw["unit"]] / UNITS[metric["unit"]]
            return converted, [], {field: raw, "metric": str(converted), "unit": metric["unit"]}
        used = {field: raw}
        if field == "credit_rating":
            used.update({k: profile[k] for k in ("credit_rating_issued_at", "credit_rating_valid_until") if k in profile})
        return raw, [], used
    if not isinstance(raw, list):
        raise ValueError("track_records는 배열이어야 합니다.")
    # 인정 기간은 원문에서 확정한 절대 날짜로 전달. 기간이 없으면 추정하지 않는다.
    start, start_missing = _period_date(metric, profile, "from")
    end, end_missing = _period_date(metric, profile, "to")
    if start_missing or end_missing:
        return None, start_missing + end_missing, {}
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
        accepted, fields = _filter_record(record, metric.get("filters", {}), f"track_records[{i}]")
        missing.extend(fields)
        if not accepted:
            continue
        if metric.get("min_record_amount") is not None:
            if record.get("amount") is None or not record.get("amount_unit"):
                missing.append(f"track_records[{i}].amount/amount_unit")
                continue
            amount = number(record["amount"]) * UNITS[record["amount_unit"]]
            if amount < 0:
                raise ValueError("실적 금액은 음수일 수 없습니다.")
            threshold = number(metric["min_record_amount"]) * UNITS[metric["unit"]]
            if amount < threshold:
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
    used = {"track_records": records, "aggregate": str(value)}
    if metric.get("reference_amount") is not None:
        denominator = number(metric["reference_amount"])
        if denominator <= 0:
            raise ValueError("실적 비율 기준금액은 양수여야 합니다.")
        value = number(value) / denominator * Decimal(100)
        used.update(reference_amount=str(denominator), unit="%")
    used["metric"] = str(value)
    return value, missing, used


def review_guidance(item):
    """자동 점수가 없어도 원문의 요구사항을 기존 reason 열에서 확인할 수 있게 한다."""
    requirements = item.get("requirements") or []
    texts = list(dict.fromkeys(r["text"] for r in requirements if r.get("text") and r.get("sources")))
    if texts:
        return "평가 시 확인할 요소: " + " / ".join(texts)
    basis = item.get("basis")
    if basis:
        return "원문 평가 기준: " + basis
    return "구체적인 평가요소가 추출되지 않았습니다. 원문 평가표와 세부 배점기준을 확인해 주세요."


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
    profile = dict(profile)
    if table.get("notice_date"):
        profile["notice_date"] = table["notice_date"]
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
        result["requirements"] = item.get("requirements", [])
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
                document = item["metric"].get("required_document")
                if document and item["rule"].get("missing_document_score") is not None:
                    if profile.get("owned_docs") is None:
                        result.update(status="missing_profile", missing_fields=["owned_docs"],
                                      reason="신용평가 증빙서류의 보유·제출 가능 여부를 확인해 주세요.")
                        all_missing.add("owned_docs")
                        result["reason"] += " · " + review_guidance(item)
                        output.append(result)
                        continue
                    normalize = lambda s: "".join(s.split())
                    if normalize(document) not in [normalize(d) for d in profile["owned_docs"]]:
                        score = number(item["rule"]["missing_document_score"])
                        if not 0 <= score <= maximum:
                            raise ValueError("증빙 미제출 점수가 배점 범위를 벗어났습니다.")
                        result.update(expected=float(score), status="calculated",
                                      used_profile={"owned_docs": profile["owned_docs"]},
                                      reason=f"{document} 없음으로 입력됨: 원문 미제출 기준을 적용한 예상 점수")
                        output.append(result)
                        continue
                value, missing, used = _metric_value(item["metric"], profile)
                result["used_profile"] = used
                if profile.get("notice_date"):
                    result["used_profile"]["notice_date"] = profile["notice_date"]
                if missing:
                    result.update(status="missing_profile", missing_fields=missing,
                                  reason="점수 계산에 필요한 프로필 정보 부족")
                    all_missing.update(missing)
                else:
                    measured = used.get("metric", value)
                    unit = used.get("unit", "명" if item["metric"].get("field") == "personnel" else "")
                    result.update(expected=_score(item, value, maximum), status="calculated",
                                  reason=f"원문 기준에 따라 코드로 계산한 예상 점수 · 적용 값: {measured}{unit}")
            except (ValueError, KeyError, TypeError, ArithmeticError) as error:
                result["reason"] = f"계산 기준 확인 필요: {error}"
        if result["status"] != "calculated":
            result["reason"] += " · " + review_guidance(item)
        output.append(result)
    missing = sorted(all_missing)
    return {"bid_no": bid_no, "revision": revision, "items": output, "needs_review": True,
            "missing_fields": missing, "questions": [f"{field} 정보를 입력해 주세요." for field in missing]}
