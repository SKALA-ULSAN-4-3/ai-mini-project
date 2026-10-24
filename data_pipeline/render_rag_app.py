"""Render 통합 진입점: 기존 RAG 서버에 포함된 데이터 API와 같은 저장소를 사용한다."""
import importlib
from pathlib import Path
import sys

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .render_app import authenticated

RAG_DIR = Path(__file__).resolve().parents[1] / "rag-code-template_ext"
if str(RAG_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_DIR))

# 기존 서버가 data_pipeline.api.router를 이미 포함하므로 중복 등록하지 않는다.
rag_server = importlib.import_module("rag_external-web_pdf_closed_llm")
app = rag_server.app
app.title = "나라장터 데이터 파이프라인 · RAG 통합 API"

PUBLIC_PATHS = frozenset({"/", "/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


@app.middleware("http")
async def require_login(request: Request, call_next):
    # OPTIONS는 기존 RAG CORS 미들웨어가 처리하고 실제 요청에 인증을 적용한다.
    if request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
        authorization = request.headers.get("authorization", "")
        parts = authorization.split(None, 1)
        credentials = (HTTPAuthorizationCredentials(scheme="Bearer", credentials=parts[1])
                       if len(parts) == 2 and parts[0].lower() == "bearer" else None)
        try:
            await run_in_threadpool(authenticated, credentials)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                                headers=exc.headers)
    return await call_next(request)


@app.get("/", include_in_schema=False)
def home():
    return {"service": "data_pipeline_and_rag", "docs": "/docs", "health": "/health"}


# 미들웨어 인증을 Swagger에도 명시해 Authorize 토큰을 모든 보호 API에 전달한다.
original_openapi = app.openapi


def combined_openapi():
    schema = original_openapi()
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["HTTPBearer"] = {
        "type": "http", "scheme": "bearer"}
    schema["security"] = [{"HTTPBearer": []}]
    schema["paths"]["/health"]["get"]["security"] = []
    return schema


app.openapi_schema = None
app.openapi = combined_openapi

# 기존 CORS 허용 정책을 그대로 가장 바깥으로 옮긴다. 인증 실패 응답에도
# CORS 헤더가 있어야 프론트가 브라우저 오류 대신 401을 확인할 수 있다.
for middleware in list(app.user_middleware):
    if middleware.cls is CORSMiddleware:
        app.user_middleware.remove(middleware)
        app.add_middleware(CORSMiddleware, *middleware.args, **middleware.kwargs)
