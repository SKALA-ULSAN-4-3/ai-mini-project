"""테스트 앱에만 가상 인증을 주입. 운영 JWT 검증을 구현한 것이 아니다."""

import copy
from pathlib import Path
import tempfile
import unittest

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    from bid_logic.api import create_bid_router
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False

from bid_logic.evaluate import FIXTURES, extracted_checklist, load_cases, scoring_table
from bid_logic import load_bids_csv, faiss_hits
from integration_support import load_integration


@unittest.skipUnless(API_AVAILABLE, "FastAPI/httpx가 설치된 환경에서 API 테스트 실행")
class ApiTest(unittest.TestCase):
    def setUp(self):
        cases = load_cases()
        self.calls = 0

        # 오직 테스트용. 실제 애플리케이션에 이 함수를 사용하지 않는다.
        def test_profile(authorization: str | None = Header(None)):
            if authorization != "Bearer fixture-only":
                raise HTTPException(status_code=401, detail="테스트 인증 실패")
            return copy.deepcopy(cases["profiles"][0])

        self.table = scoring_table(cases["scoring_templates"][0])

        def provide_bids():
            self.calls += 1
            return load_bids_csv(FIXTURES / "bids.synthetic.csv")

        def provide_score(bid_no, revision):
            return self.table if (bid_no, revision) == ("SYN-01", "00") else None

        self.arguments = dict(profile_dependency=test_profile, bids_provider=provide_bids,
                              scoring_provider=provide_score,
                              checklist_provider=lambda *a: extracted_checklist(),
                              search=lambda *a: [], clock=lambda: cases["now"])
        self.app = FastAPI()
        self.app.include_router(create_bid_router(**self.arguments))
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer fixture-only"}

    def test_unauthorized_all_routes_before_data_access(self):
        for path in ("/bids?from=2026-10-01&to=2026-10-31",
                     "/bids/SYN-01/score?revision=00", "/bids/SYN-01/checklist?revision=00"):
            for headers in ({}, {"Authorization": "Bearer expired-or-invalid"}):
                self.assertEqual(self.client.get(path, headers=headers).status_code, 401)
        self.assertEqual(self.calls, 0)

    def test_bids_aliases_and_schema(self):
        response = self.client.get("/bids?from=2026-10-01&to=2026-10-31", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidate_count"], 3)
        self.assertIn("reason", response.json()["bids"][0])

    def test_scores_and_checklist_json(self):
        response = self.client.get("/bids/SYN-01/score?revision=00", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["expected"], 10)
        self.assertNotIn("total", response.json())
        response = self.client.get("/bids/SYN-01/checklist?revision=00", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["documents"][0]["owned"])

    def test_invalid_period_and_missing_revision_422(self):
        for path in ("/bids?from=2026-11-01&to=2026-10-01", "/bids/SYN-01/score",
                     "/bids?from=bad&to=2026-10-01"):
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 422)

    def test_unknown_bid_revision_404(self):
        self.assertEqual(self.client.get("/bids/SYN-01/score?revision=01",
                                         headers=self.headers).status_code, 404)

    def test_profile_missing_404(self):
        def missing_profile():
            raise HTTPException(status_code=404, detail="프로필 등록 필요")
        self.app.dependency_overrides[self.arguments["profile_dependency"]] = missing_profile
        self.assertEqual(self.client.get("/bids?from=2026-10-01&to=2026-10-31",
                                         headers=self.headers).status_code, 404)

    def test_provider_failure_503(self):
        def unavailable():
            raise OSError("internal path or credentials should not be exposed")
        args = {**self.arguments, "bids_provider": unavailable}
        app = FastAPI()
        app.include_router(create_bid_router(**args))
        response = TestClient(app).get("/bids?from=2026-10-01&to=2026-10-31", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("credentials", response.text)
        def unavailable_search(*args):
            raise RuntimeError("벡터 저장소 준비 중")
        app = FastAPI()
        app.include_router(create_bid_router(**{**self.arguments, "search": unavailable_search}))
        response = TestClient(app).get("/bids?from=2026-10-01&to=2026-10-31", headers=self.headers)
        self.assertEqual(response.status_code, 503)

    def test_factory_requires_dependencies_and_import_adds_no_route(self):
        self.assertFalse(any(r.path == "/bids" for r in FastAPI().routes))
        with self.assertRaises(ValueError):
            create_bid_router(**{**self.arguments, "profile_dependency": None})

    def test_openapi_preserves_query_contract(self):
        schema = self.client.get("/openapi.json").json()
        params = schema["paths"]["/bids"]["get"]["parameters"]
        self.assertTrue({"from", "to"}.issubset({p["name"] for p in params}))
        self.assertIn("ScoreResponse", schema["components"]["schemas"])


@unittest.skipUnless(API_AVAILABLE, "FastAPI/httpx가 설치된 환경에서 API 테스트 실행")
class MainFileIntegrationTest(unittest.TestCase):
    """원본 파일의 연결 함수를 실행한다. 기존 LLM/DB 초기화는 실행하지 않는다."""

    def setUp(self):
        self.cases = load_cases()
        self.app = FastAPI()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        (self.base / "data").mkdir()
        (self.base / "data" / "bids.csv").write_bytes((FIXTURES / "bids.synthetic.csv").read_bytes())
        self.namespace = load_integration(app=self.app, base_dir=self.base)
        self.register = self.namespace["register_bid_routes"]

        def profile(authorization: str | None = Header(None)):
            if authorization != "Bearer fixture-only":
                raise HTTPException(status_code=401)
            return self.cases["profiles"][0]
        self.arguments = dict(profile_dependency=profile,
                              scoring_provider=lambda *a: scoring_table(self.cases["scoring_templates"][0]),
                              checklist_provider=lambda *a: extracted_checklist(),
                              clock=lambda: self.cases["now"])
        self.headers = {"Authorization": "Bearer fixture-only"}
        self.url = "/bids?from=2026-10-01&to=2026-10-31"

    def test_explicit_registration_and_existing_route_preserved(self):
        @self.app.post("/rag-query")
        def existing_query(payload: dict):
            return {"prompt": payload["prompt"], "response": "existing"}
        client = TestClient(self.app)
        self.assertEqual(client.get(self.url).status_code, 404)
        self.register(**self.arguments, search=lambda *a: [])
        self.assertEqual(client.get(self.url).status_code, 401)
        result = client.post("/rag-query", json={"prompt": "질문"})
        self.assertEqual(result.json(), {"prompt": "질문", "response": "existing"})

    def test_default_csv_location_and_all_three_routes(self):
        self.register(**self.arguments, search=lambda *a: [])
        client = TestClient(self.app)
        self.assertEqual(client.get(self.url, headers=self.headers).json()["candidate_count"], 3)
        for suffix in ("score", "checklist"):
            self.assertEqual(client.get(f"/bids/SYN-01/{suffix}?revision=00",
                                         headers=self.headers).status_code, 200)

    def test_vectorstore_resolved_at_request_time(self):
        self.register(**self.arguments)
        client = TestClient(self.app)
        self.assertEqual(client.get(self.url, headers=self.headers).status_code, 503)
        from types import SimpleNamespace
        doc = SimpleNamespace(metadata={"bid_no": "SYN-05", "revision": "00"})
        self.namespace["VECTORSTORE_PDF"] = SimpleNamespace(
            index=SimpleNamespace(ntotal=1), similarity_search_with_score=lambda *a, **kw: [(doc, 0.1)])
        result = client.get(self.url, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["bids"][0]["bid_no"], "SYN-05")

    def test_duplicate_registration_rejected(self):
        self.register(**self.arguments)
        before = len(self.app.routes)
        with self.assertRaises(RuntimeError):
            self.register(**self.arguments)
        self.assertEqual(len(self.app.routes), before)


if __name__ == "__main__":
    unittest.main()
