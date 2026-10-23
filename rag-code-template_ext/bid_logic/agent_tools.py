"""X2 선작성: 채점 에이전트가 호출할 도구 4개.

Tool Calling 루프, 실제 LLM 호출, C4 고정 경로와의 비교 측정은 포함하지 않는다.
점수를 만드는 주체는 여전히 `calculate_scores`이고, 에이전트는 항목마다
계산할지 사람에게 넘길지 고르는 역할만 한다.
"""

from copy import deepcopy

from .common import check_scope
from .scoring import calculate_scores

# 에이전트가 기준을 지어내지 못하도록 판단에 필요한 필드만 보여 준다.
# rule/metric은 코드가 실행할 값이므로 전달하지 않는다.
VISIBLE_ITEM_FIELDS = ("id", "item", "kind", "max", "basis", "sources")

TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_scoring_table",
        "description": "현재 공고·차수의 채점 항목 목록을 반환한다. 배점과 원문 기준을 포함한다.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_profile",
        "description": "인증된 회사 프로필을 반환한다. 점수 계산의 입력이다.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "calc_score",
        "description": "정량 항목 하나를 원문 기준에 따라 코드로 계산한다. "
                       "프로필 정보가 부족하면 점수 대신 필요한 필드와 질문을 반환한다.",
        "parameters": {"type": "object", "properties": {
            "item_id": {"type": "string", "description": "채점 항목 id"}},
            "required": ["item_id"]}}},
    {"type": "function", "function": {
        "name": "mark_manual",
        "description": "항목을 담당자 판단으로 넘긴다. 정성·가격 항목이거나 "
                       "원문 기준으로 계산할 수 없을 때 사용한다.",
        "parameters": {"type": "object", "properties": {
            "item_id": {"type": "string", "description": "채점 항목 id"},
            "reason": {"type": "string", "description": "사람에게 넘기는 이유"}},
            "required": ["item_id", "reason"]}}},
]


class ScoringTools:
    """한 공고·차수에 묶인 도구 모음.

    에이전트가 다른 공고로 벗어나거나 채점 기준·배점을 지어내지 못하도록
    도구는 `item_id`만 받고, 실제 기준은 공급자가 준 원문 추출 결과에서 찾는다.
    호출 기록은 `calls`에 남아 기획서의 `tool_calls[]`와 X2 비교에 쓴다.
    """

    def __init__(self, *, scoring_provider, profile_provider, bid_no, revision):
        if not callable(scoring_provider) or not callable(profile_provider):
            raise ValueError("채점표와 프로필 공급 함수를 연결해야 합니다.")
        if not isinstance(bid_no, str) or not bid_no.strip():
            raise ValueError("bid_no는 비어 있지 않은 문자열이어야 합니다.")
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("revision은 비어 있지 않은 문자열이어야 합니다.")
        self.bid_no, self.revision = bid_no.strip(), revision.strip()
        self._scoring_provider = scoring_provider
        self._profile_provider = profile_provider
        self._table_cache = None
        self._profile_cache = None
        self.calls = []

    def _log(self, tool, arguments, result):
        self.calls.append({"tool": tool, "arguments": arguments,
                           "status": result.get("status") if isinstance(result, dict) else None})
        return deepcopy(result)

    def _table(self):
        # 한 번만 불러 같은 입력으로 비교할 수 있게 하고 공급자 호출 비용도 줄인다.
        if self._table_cache is None:
            table = self._scoring_provider(self.bid_no, self.revision)
            if table is None:
                raise ValueError("해당 공고·차수의 채점표 추출 결과가 없습니다.")
            # 공급자가 잘못된 공고·차수나 출처를 반환해도 모든 도구에서 차단한다.
            table = deepcopy(table)
            check_scope(table, self.bid_no, self.revision)
            if not isinstance(table.get("items"), list):
                raise ValueError("채점 항목 목록이 필요합니다.")
            seen = set()
            for item in table["items"]:
                check_scope(item, self.bid_no, self.revision)
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id.strip() or item_id in seen:
                    raise ValueError("채점 항목 id가 없거나 중복되었습니다.")
                seen.add(item_id)
            self._table_cache = table
        return self._table_cache

    def _profile(self):
        if self._profile_cache is None:
            profile = self._profile_provider()
            if not isinstance(profile, dict):
                raise ValueError("프로필 공급 함수는 dict를 반환해야 합니다.")
            self._profile_cache = deepcopy(profile)
        return self._profile_cache

    def _item(self, item_id):
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValueError("item_id는 비어 있지 않은 문자열이어야 합니다.")
        matches = [i for i in self._table()["items"] if i.get("id") == item_id.strip()]
        if len(matches) != 1:
            raise ValueError("채점표에서 해당 item_id를 하나로 특정할 수 없습니다.")
        return matches[0]

    def get_scoring_table(self):
        items = [{k: item.get(k) for k in VISIBLE_ITEM_FIELDS} for item in self._table()["items"]]
        result = {"bid_no": self.bid_no, "revision": self.revision, "items": items}
        self.calls.append({"tool": "get_scoring_table", "arguments": {},
                           "status": f"{len(items)} items"})
        return deepcopy(result)

    def get_profile(self):
        profile = self._profile()
        self.calls.append({"tool": "get_profile", "arguments": {},
                           "status": f"{len(profile)} fields"})
        return deepcopy(profile)

    def calc_score(self, item_id):
        """C4 고정 경로와 같은 `calculate_scores`로 계산한다. 별도 채점 로직이 없다."""
        item = self._item(item_id)
        table = self._table()
        single = {"bid_no": self.bid_no, "revision": self.revision,
                  "sources": table.get("sources", []), "items": [item]}
        outcome = calculate_scores(single, self._profile(), self.bid_no, self.revision)
        result = {**outcome["items"][0], "questions": outcome["questions"]}
        return self._log("calc_score", {"item_id": item_id}, result)

    def mark_manual(self, item_id, reason):
        """`calculate_scores`의 manual 항목과 같은 키를 만들어 두 경로를 비교할 수 있게 한다."""
        item = self._item(item_id)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("담당자 판단으로 넘기는 이유가 필요합니다.")
        result = {"id": item["id"], "item": item["item"], "max": item.get("max"),
                  "expected": "담당자 판단", "status": "manual", "needs_review": True,
                  "sources": item.get("sources", []), "basis": item.get("basis"),
                  "rule": item.get("rule"), "used_profile": {}, "missing_fields": [],
                  "reason": reason.strip(), "questions": []}
        return self._log("mark_manual", {"item_id": item_id, "reason": reason.strip()}, result)

    def dispatch(self, name, arguments=None):
        """LLM이 고른 도구 이름과 인자를 실행한다. 모르는 도구는 거부한다."""
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ValueError("도구 인자는 객체여야 합니다.")
        handlers = {"get_scoring_table": lambda: self.get_scoring_table(),
                    "get_profile": lambda: self.get_profile(),
                    "calc_score": lambda: self.calc_score(**arguments),
                    "mark_manual": lambda: self.mark_manual(**arguments)}
        if name not in handlers:
            raise ValueError(f"지원하지 않는 도구입니다: {name}")
        allowed = {s["function"]["name"]: set(
            s["function"]["parameters"]["properties"]) for s in TOOL_SPECS}[name]
        if set(arguments) - allowed:
            raise ValueError(f"{name}이 받지 않는 인자입니다: {sorted(set(arguments) - allowed)}")
        try:
            return handlers[name]()
        except TypeError as error:  # 인자 누락을 에이전트가 고칠 수 있게 ValueError로 돌린다.
            raise ValueError(f"{name} 인자를 확인해 주세요: {error}") from error
