"""4번 백엔드 연결(backend_auth) 검증. 가짜 /api/profile 서버를 띄워 확인하며 LLM · 실제 DB 호출 없음."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from fastapi import HTTPException
    from backend_auth import get_authenticated_profile, require_login
except ImportError:  # FastAPI가 없는 환경
    get_authenticated_profile = None

PROFILE = {"id": 1, "business_registration_number": "1234567890", "industry": "SW", "licenses": [],
           "region": "울산", "company_size": "중소기업", "certs": [], "credit_rating": None,
           "track_records": [], "owned_docs": ["사업자등록증"], "budget_min": None, "budget_max": None,
           "keywords": ["플랫폼"], "created_at": "2026-10-23T07:14:08Z", "updated_at": "2026-10-23T07:14:08Z"}


class FakeBackend(BaseHTTPRequestHandler):
    # 백엔드(4번)의 실제 응답 형식: 오류는 {"code", "message", "request_id"}
    def do_GET(self):
        token = self.headers.get("Authorization", "")
        if self.path == "/api/auth/check":
            # 토큰만 확인하는 API: 프로필이 없어도 로그인은 유효
            ok = token in ("Bearer good", "Bearer no-profile")
            status, body = (200, {"ok": True, "business_registration_number": "1234567890", "corporate_name": "테스트"}) if ok \
                else (401, {"code": "UNAUTHORIZED", "message": "유효하지 않거나 만료된 인증 토큰입니다.", "request_id": "x"})
        elif token == "Bearer good":
            status, body = 200, PROFILE
        elif token == "Bearer no-profile":
            status, body = 404, {"code": "RESOURCE_NOT_FOUND", "message": "등록된 회사 프로필이 없습니다.", "request_id": "x"}
        elif token == "Bearer broken":
            status, body = 500, {"code": "INTERNAL_SERVER_ERROR", "message": "서버 내부 오류", "request_id": "x"}
        else:
            status, body = 401, {"code": "UNAUTHORIZED", "message": "유효하지 않거나 만료된 인증 토큰입니다.", "request_id": "x"}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class FakeBackendCase(unittest.TestCase):
    """가짜 백엔드를 띄우고 BACKEND_URL을 그쪽으로 돌린다 (각 테스트 끝에 원래 값 복원)."""
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.saved = os.environ.get("BACKEND_URL")
        os.environ["BACKEND_URL"] = f"http://127.0.0.1:{self.server.server_port}/"

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("BACKEND_URL", None)
        else:
            os.environ["BACKEND_URL"] = self.saved


@unittest.skipIf(get_authenticated_profile is None, "FastAPI 미설치")
class BackendAuthTest(FakeBackendCase):
    def status_of(self, authorization):
        with self.assertRaises(HTTPException) as caught:
            get_authenticated_profile(authorization)
        return caught.exception.status_code

    def test_valid_token_returns_profile_for_bid_logic(self):
        profile = get_authenticated_profile("Bearer good")
        self.assertEqual(profile["region"], "울산")
        self.assertEqual(profile["owned_docs"], ["사업자등록증"])
        self.assertNotIn("created_at", profile)

    def test_missing_or_malformed_header_is_401_without_calling_backend(self):
        self.assertEqual(self.status_of(None), 401)
        self.assertEqual(self.status_of("good"), 401)
        self.assertEqual(self.status_of("Bearer "), 401)

    def test_backend_statuses_are_passed_through(self):
        self.assertEqual(self.status_of("Bearer forged"), 401)
        self.assertEqual(self.status_of("Bearer no-profile"), 404)
        self.assertEqual(self.status_of("Bearer broken"), 503)

    def test_unreachable_or_unset_backend_is_503(self):
        os.environ["BACKEND_URL"] = "http://127.0.0.1:9"   # 닫힌 포트
        self.assertEqual(self.status_of("Bearer good"), 503)
        os.environ["BACKEND_URL"] = ""
        self.assertEqual(self.status_of("Bearer good"), 503)


@unittest.skipIf(get_authenticated_profile is None, "FastAPI 미설치")
class RequireLoginTest(FakeBackendCase):
    """질의 · 요약 · 검색 · 음성 API용 로그인 확인 (프로필 없이 토큰만)."""

    def status_of(self, authorization):
        with self.assertRaises(HTTPException) as caught:
            require_login(authorization)
        return caught.exception.status_code

    def test_token_only_check(self):
        self.assertEqual(require_login("Bearer good")["business_registration_number"], "1234567890")
        self.assertTrue(require_login("Bearer no-profile")["ok"])     # 프로필이 없어도 질문은 가능
        self.assertEqual(self.status_of(None), 401)
        self.assertEqual(self.status_of("Bearer forged"), 401)

    def test_open_without_backend_and_503_when_down(self):
        os.environ["BACKEND_URL"] = ""
        self.assertIsNone(require_login(None))                     # 로컬 개발 · 평가는 그대로
        os.environ["BACKEND_URL"] = "http://127.0.0.1:9"
        self.assertEqual(self.status_of("Bearer good"), 503)


if __name__ == "__main__":
    unittest.main()
