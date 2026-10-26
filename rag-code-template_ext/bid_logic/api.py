"""백엔드 담당자의 인증된 프로필 의존성과 데이터 공급자를 받는 라우터 팩토리.

이 모듈을 import하는 것만으로는 어떤 경로도 등록되지 않는다.
"""

from datetime import date, datetime
import logging
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from .checklist import build_checklist
from .common import SEOUL, RequestError
from .shortlist import shortlist_bids, recheck_after_ingest
from .scoring import calculate_scores
from .agent_runner import run_scoring_agent

logger = logging.getLogger(__name__)


class BidListResponse(BaseModel):
    bids: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    candidate_count: int
    needs_review: bool
    ranking_kind: str
    stage: str
    search_id: str | None = None


class BidKey(BaseModel):
    bid_no: str = Field(min_length=1, strict=True)
    revision: str = Field(min_length=1, strict=True)

    @field_validator("bid_no", "revision")
    @classmethod
    def clean_identifier(cls, value):
        if not value.strip():
            raise ValueError("공고번호·차수는 비어 있을 수 없습니다.")
        return value.strip()


class RecheckRequest(BaseModel):
    start: date = Field(alias="from")
    end: date = Field(alias="to")
    bids: list[BidKey] = Field(min_length=1, max_length=20)
    search_id: str | None = Field(default=None, min_length=1)


class RecheckResponse(BaseModel):
    bids: list[dict[str, Any]]
    needs_review: bool
    stage: str
    disqualified: list[str]
    not_evaluated: list[str]


class ScoreResponse(BaseModel):
    bid_no: str
    revision: str
    items: list[dict[str, Any]]
    needs_review: bool
    missing_fields: list[str]
    questions: list[str]


class ScoreInputs(BaseModel):
    """현재 프로필에 없는 증빙·인력 정보의 요청 단위 보완. DB에는 저장하지 않는다."""
    model_config = {"extra": "forbid"}
    personnel: list[dict[str, Any]] | None = None
    track_records: list[dict[str, Any]] | None = None
    notice_date: date | None = None
    credit_rating: str | None = None
    credit_rating_issued_at: date | None = None
    credit_rating_valid_until: date | None = None
    owned_docs: list[str] | None = None


class ChecklistResponse(BaseModel):
    bid_no: str
    revision: str
    documents: list[dict[str, Any]]
    schedule: list[dict[str, Any]]
    needs_review: bool


def create_bid_router(*, profile_dependency: Callable, bids_provider: Callable,
                      scoring_provider: Callable, checklist_provider: Callable,
                      search: Callable, clock=None, search_results_provider=None,
                      title_similarity=None, loaded_keys_provider=None, agent_model=None,
                      require_search_id=False):
    """공급자는 동기 함수. profile_dependency는 sync/async FastAPI Depends 함수.

    인증 의존성이 서명·만료 검증 후 프로필 dict를 반환해야 한다.
    JWT 미검증/만료 401, 프로필 없음 404는 해당 의존성이 발생시킨다.
    문서 공급자(bid_no, revision)는 정확한 차수를 반환하고 없으면 None.
    """
    if any(not callable(f) for f in (profile_dependency, bids_provider, scoring_provider,
                                     checklist_provider, search)):
        raise ValueError("인증된 프로필 및 모든 데이터 공급 함수를 연결해야 합니다.")
    if any(f is not None and not callable(f) for f in (
            search_results_provider, title_similarity, loaded_keys_provider, agent_model)):
        raise ValueError("선택 공급자는 함수여야 합니다.")
    clock = clock or (lambda: datetime.now(SEOUL))
    router = APIRouter(tags=["공고 추리기·점수·체크리스트"])

    def invoke(action):
        # 요청·프로필 문제만 422. 공급자·CSV·인덱스 데이터 문제는 사용자가 고칠 수 없으므로
        # 503으로 돌려주고, 내부 경로나 인증 정보가 섞일 수 있는 원문은 로그에만 남긴다.
        try:
            return action()
        except HTTPException:
            raise
        except RequestError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (ValueError, OSError, KeyError, TypeError, RuntimeError, ArithmeticError) as error:
            logger.exception("공고 데이터 처리 실패")
            raise HTTPException(status_code=503, detail="공고 데이터 연동 상태를 확인해 주세요.") from error

    def selected_payload(provider, bid_no, revision):
        value = provider(bid_no, revision)
        if value is None:
            raise HTTPException(status_code=404, detail="해당 공고·차수의 데이터가 없습니다.")
        return value

    def saved_rows(search_id, profile, start, end):
        if search_results_provider is None:
            raise HTTPException(503, "검색 결과 공급 함수를 연결해 주세요.")
        if not search_id or not search_id.strip():
            raise RequestError("① 검색 응답의 search_id가 필요합니다.")
        payload = search_results_provider(search_id, profile)
        if payload is None:
            raise HTTPException(404, "검색 결과가 없거나 접근할 수 없습니다.")
        if isinstance(payload, dict):
            stored_period = (payload.get("from") or str(start), payload.get("to") or str(end))
            allowed_periods = {stored_period}
            if payload.get("request_from") and payload.get("request_to"):
                # 이전 프론트는 게시 시작일을 전송한다. 같은 스냅샷의 원래 검색조건만 허용한다.
                allowed_periods.add((payload["request_from"], payload["request_to"]))
            if (str(start), str(end)) not in allowed_periods:
                raise RequestError("저장된 검색 기간과 요청 기간이 다릅니다. 새로 검색해 주세요.")
            return (payload.get("bids", payload.get("items", payload.get("results"))),
                    date.fromisoformat(stored_period[0]), date.fromisoformat(stored_period[1]))
        return payload, start, end

    @router.get("/bids", response_model=BidListResponse)
    def bids(start: date = Query(..., alias="from"), end: date = Query(..., alias="to"),
             limit: int = Query(20, ge=1, le=20),
             search_id: str | None = Query(None, min_length=1),
             profile: dict = Depends(profile_dependency)):
        def run():
            effective_start, effective_end = start, end
            if start > end:
                raise RequestError("공고 기간이 뒤집혔습니다.")
            if search_results_provider is not None or require_search_id:
                rows, effective_start, effective_end = saved_rows(search_id, profile, start, end)
            elif search_id is not None:
                raise HTTPException(status_code=503, detail="검색 결과 공급 함수를 연결해 주세요.")
            else:
                rows = bids_provider()  # 고정 CSV 평가·개발 호환. 본문 검색은 하지 않는다.
            if not isinstance(rows, (list, tuple)):
                raise ValueError("검색 결과 공고 배열이 필요합니다.")
            result = shortlist_bids(rows, profile, start=effective_start, end=effective_end, now=clock(),
                                    limit=limit, similarity=title_similarity)
            return {**result, "search_id": search_id}
        return invoke(run)

    @router.post("/bids/recheck", response_model=RecheckResponse)
    def recheck(payload: RecheckRequest, profile: dict = Depends(profile_dependency)):
        def run():
            effective_start, effective_end = payload.start, payload.end
            if payload.start > payload.end:
                raise RequestError("공고 기간이 뒤집혔습니다.")
            if require_search_id and not payload.search_id:
                raise RequestError("① 검색 응답의 search_id가 필요합니다.")
            if payload.search_id is not None:
                # CSV에는 아직 없는 새 공고도 저장 검색의 메타데이터로 재확인한다.
                # 자격 제약은 추정하지 않고 미확인 보존. 실제 적재 여부는 아래에서 검사한다.
                from .shortlist import recheck_metadata
                saved, effective_start, effective_end = saved_rows(
                    payload.search_id, profile, payload.start, payload.end)
                rows = [recheck_metadata(r) for r in saved]
            else:
                rows = bids_provider()
            if loaded_keys_provider is not None:
                loaded = set(loaded_keys_provider())
                rows = [row for row in rows if (row["bid_no"], row["revision"]) in loaded]
            return recheck_after_ingest([key.model_dump() for key in payload.bids], rows,
                                        profile, effective_start, effective_end, now=clock(), search=search)
        return invoke(run)

    # revision 필수: 어느 차수인지 모르는 요청을 최신이라고 추정하지 않는다.
    @router.get("/bids/{bid_no}/score", response_model=ScoreResponse)
    def score(bid_no: str, revision: str = Query(..., min_length=1),
              profile: dict = Depends(profile_dependency)):
        return invoke(lambda: calculate_scores(selected_payload(scoring_provider, bid_no, revision),
                                              profile, bid_no, revision))

    @router.post("/bids/{bid_no}/score", response_model=ScoreResponse)
    def score_with_inputs(bid_no: str, payload: ScoreInputs,
                          revision: str = Query(..., min_length=1),
                          profile: dict = Depends(profile_dependency)):
        supplied = payload.model_dump(mode="json", exclude_none=True)
        return invoke(lambda: calculate_scores(selected_payload(scoring_provider, bid_no, revision),
                                              {**profile, **supplied}, bid_no, revision))

    @router.get("/bids/{bid_no}/checklist", response_model=ChecklistResponse)
    def checklist(bid_no: str, revision: str = Query(..., min_length=1),
                  profile: dict = Depends(profile_dependency)):
        return invoke(lambda: build_checklist(selected_payload(checklist_provider, bid_no, revision),
                                             profile, bid_no, revision, now=clock()))

    if agent_model is not None:
        @router.post("/agent/score")
        async def agent_score(payload: BidKey, profile: dict = Depends(profile_dependency)):
            # 동기 RAG 추출 I/O가 이벤트 루프를 막지 않게 먼저 threadpool에서 읽는다.
            table = await run_in_threadpool(invoke, lambda: selected_payload(
                scoring_provider, payload.bid_no, payload.revision))
            # 모델 호출 전에 기존 C4 입력 범위와 프로필을 검사한다. 409는 그대로 전달된다.
            await run_in_threadpool(invoke, lambda: calculate_scores(
                table, profile, payload.bid_no, payload.revision))
            return await run_scoring_agent(table, profile, payload.bid_no, payload.revision,
                model=agent_model, timeout_seconds=60, max_tool_calls=max(30, len(table["items"])*2+4))

    return router
