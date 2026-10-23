"""4번 Java 백엔드(로그인 · JWT 발급 · 회사 프로필)와 3번 공고 API를 잇는 인증 의존성.

Python 서버는 JWT 비밀키를 따로 갖지 않는다. 받은 Bearer 토큰을 그대로 백엔드
GET /api/profile에 전달하고, 서명 · 만료 검증과 프로필 조회는 백엔드가 한다.
(비밀키를 한 곳에서만 관리하고, 프로필 원본도 DB 하나만 본다.)

BACKEND_URL(예: http://localhost:8080)이 설정되어 있으면 서버 시작 시 자동으로 연결된다.
"""
import json
import os
import urllib.error
import urllib.request

from fastapi import Header, HTTPException

TIMEOUT_SECONDS = 5


def backend_url() -> str:
    return os.getenv("BACKEND_URL", "").strip().rstrip("/")


def _backend_message(error: urllib.error.HTTPError, default: str) -> str:
    # 백엔드 오류 형식: {"code", "message", "request_id"}
    try:
        return json.loads(error.read().decode("utf-8")).get("message") or default
    except (ValueError, UnicodeDecodeError, AttributeError):
        return default


def get_authenticated_profile(authorization: str | None = Header(default=None)) -> dict:
    """3번 create_bid_router가 요구하는 profile_dependency: 401(토큰) · 404(프로필 없음) · 503(백엔드 장애)."""
    if not authorization or not authorization[:7].lower() == "bearer " or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="로그인이 필요합니다. Authorization: Bearer <토큰>을 보내 주세요.",
                            headers={"WWW-Authenticate": "Bearer"})
    if not backend_url():
        raise HTTPException(status_code=503, detail="BACKEND_URL이 설정되지 않아 회사 프로필을 확인할 수 없습니다.")

    request = urllib.request.Request(f"{backend_url()}/api/profile",
                                     headers={"Authorization": authorization, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            profile = json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise HTTPException(status_code=401, detail=_backend_message(error, "유효하지 않거나 만료된 인증 토큰입니다."),
                                headers={"WWW-Authenticate": "Bearer"}) from error
        if error.code == 404:
            raise HTTPException(status_code=404, detail=_backend_message(error, "등록된 회사 프로필이 없습니다.")) from error
        raise HTTPException(status_code=503, detail="회사 프로필 서비스가 응답하지 않습니다.") from error
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise HTTPException(status_code=503, detail="회사 프로필 서비스에 연결할 수 없습니다.") from error

    if not isinstance(profile, dict):
        raise HTTPException(status_code=503, detail="회사 프로필 응답 형식이 올바르지 않습니다.")
    # 3번 계산에 쓰지 않는 식별 · 시각 필드는 넘기지 않는다
    return {k: v for k, v in profile.items() if k not in ("id", "created_at", "updated_at")}
