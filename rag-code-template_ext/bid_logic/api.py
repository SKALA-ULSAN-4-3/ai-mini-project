"""백엔드 담당자의 인증된 프로필 의존성과 데이터 공급자를 받는 라우터 팩토리.

이 모듈을 import하는 것만으로는 어떤 경로도 등록되지 않는다.
"""

from datetime import date, datetime
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .checklist import build_checklist
from .common import SEOUL
from .recommendation import recommend_bids
from .scoring import calculate_scores


class BidListResponse(BaseModel):
    bids: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    candidate_count: int
    needs_review: bool


class ScoreResponse(BaseModel):
    bid_no: str
    revision: str
    items: list[dict[str, Any]]
    needs_review: bool
    missing_fields: list[str]
    questions: list[str]


class ChecklistResponse(BaseModel):
    bid_no: str
    revision: str
    documents: list[dict[str, Any]]
    schedule: list[dict[str, Any]]
    needs_review: bool


def create_bid_router(*, profile_dependency: Callable, bids_provider: Callable,
                      scoring_provider: Callable, checklist_provider: Callable,
                      search: Callable, clock=None):
    """공급자는 동기 함수. profile_dependency는 sync/async FastAPI Depends 함수.

    인증 의존성이 서명·만료 검증 후 프로필 dict를 반환해야 한다.
    JWT 미검증/만료 401, 프로필 없음 404는 해당 의존성이 발생시킨다.
    문서 공급자(bid_no, revision)는 정확한 차수를 반환하고 없으면 None.
    """
    if any(not callable(f) for f in (profile_dependency, bids_provider, scoring_provider,
                                     checklist_provider, search)):
        raise ValueError("인증된 프로필 및 모든 데이터 공급 함수를 연결해야 합니다.")
    clock = clock or (lambda: datetime.now(SEOUL))
    router = APIRouter(tags=["공고 추리기·점수·체크리스트"])

    def invoke(action):
        try:
            return action()
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except (OSError, KeyError, TypeError, RuntimeError) as error:
            raise HTTPException(status_code=503, detail="공고 데이터 연동 상태를 확인해 주세요.") from error

    def selected_payload(provider, bid_no, revision):
        value = provider(bid_no, revision)
        if value is None:
            raise HTTPException(status_code=404, detail="해당 공고·차수의 데이터가 없습니다.")
        return value

    @router.get("/bids", response_model=BidListResponse)
    def bids(start: date = Query(..., alias="from"), end: date = Query(..., alias="to"),
             limit: int = Query(5, ge=1, le=20), profile: dict = Depends(profile_dependency)):
        return invoke(lambda: recommend_bids(bids_provider(), profile, start, end,
                                             now=clock(), search=search, limit=limit))

    # revision 필수: 어느 차수인지 모르는 요청을 최신이라고 추정하지 않는다.
    @router.get("/bids/{bid_no}/score", response_model=ScoreResponse)
    def score(bid_no: str, revision: str = Query(..., min_length=1),
              profile: dict = Depends(profile_dependency)):
        return invoke(lambda: calculate_scores(selected_payload(scoring_provider, bid_no, revision),
                                              profile, bid_no, revision))

    @router.get("/bids/{bid_no}/checklist", response_model=ChecklistResponse)
    def checklist(bid_no: str, revision: str = Query(..., min_length=1),
                  profile: dict = Depends(profile_dependency)):
        return invoke(lambda: build_checklist(selected_payload(checklist_provider, bid_no, revision),
                                             profile, bid_no, revision, now=clock()))

    return router
