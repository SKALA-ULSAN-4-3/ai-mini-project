"""Render 전용 진입점. 데이터 API만 제공하고 기존 Java JWT로 접근을 확인한다."""
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx

from .api import router

bearer = HTTPBearer(auto_error=False)


def authenticated(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, "Bearer JWT가 필요합니다.", headers={"WWW-Authenticate": "Bearer"})
    backend = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    if not backend.startswith("https://"):
        raise HTTPException(503, "HTTPS BACKEND_URL 설정이 필요합니다.")
    try:
        response = httpx.get(backend + "/api/auth/check",
                             headers={"Authorization": f"Bearer {credentials.credentials}"},
                             timeout=15, follow_redirects=False)
    except httpx.HTTPError:
        raise HTTPException(503, "인증 서버에 연결할 수 없습니다.") from None
    if response.status_code in (401, 403):
        raise HTTPException(response.status_code, "유효한 로그인 토큰이 필요합니다.")
    if response.status_code != 200:
        raise HTTPException(503, "인증 서버 응답을 확인하세요.")


app = FastAPI(title="나라장터 데이터 파이프라인 API", version="1.0.0")
app.include_router(router, dependencies=[Depends(authenticated)])


@app.get("/", include_in_schema=False)
def home():
    return {"service": "data_pipeline", "docs": "/docs", "health": "/health"}


@app.get("/health", tags=["운영"])
def health():
    return {"status": "ok", "service": "data_pipeline"}
