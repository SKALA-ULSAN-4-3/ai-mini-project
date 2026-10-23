"""②→③'의 API 계약. 외부 API/LLM/실제 JWT를 호출하지 않는다."""
import copy
import unittest

from bid_logic import embedding_title_similarity

try:
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient
    from bid_logic.api import create_bid_router
    API_AVAILABLE = True
except ImportError:
    API_AVAILABLE = False


def listing(no):
    return {"bid_no": no, "bid_order": "000", "title": "웹 구축",
            "bidNtceDt": "2026-10-23 09:00:00", "bidClseDt": "2026-11-01 18:00:30",
            "asignBdgtAmt": "100000000", "indstrytyLmtYn": "Y",
            "attachments": [{"file_name": "공고문.pdf", "url": "https://example.test/notice.pdf"}]}


def metadata(no, regions=None):
    return {"bid_no": no, "revision": "000", "title": "웹 구축", "published_at": "2026-10-23",
            "deadline": "2026-11-01T18:00:30+09:00", "budget": "100000000",
            "regions": regions or [], "industries": [], "licenses": [], "company_sizes": [], "certs": []}


class EmbeddingTest(unittest.TestCase):
    def test_cosine_ranks_vectors_and_skips_blank_titles(self):
        class Embeddings:
            def embed_query(self, query):
                return [2, 0]

            def embed_documents(self, titles):
                self.seen = titles
                return [[0, 3], [4, 0]]
        embeddings = Embeddings()
        self.assertEqual(embedding_title_similarity(embeddings, "웹", ["연구", "", "홈페이지"]), [0, 0, 1])
        self.assertEqual(embeddings.seen, ["연구", "홈페이지"])

    def test_bad_embedding_dimensions_rejected(self):
        class Embeddings:
            def embed_query(self, query):
                return [1, 0]

            def embed_documents(self, titles):
                return [[1]]
        with self.assertRaises(ValueError):
            embedding_title_similarity(Embeddings(), "웹", ["홈페이지"])


@unittest.skipUnless(API_AVAILABLE, "FastAPI/httpx 필요")
class PipelineFlowTest(unittest.TestCase):
    def setUp(self):
        self.profile = {"region": "서울", "keywords": ["웹"], "owned_docs": ["사업자등록증"]}
        self.saved = [listing(f"A{i:02}") for i in range(25)]
        self.rows = [metadata(row["bid_no"]) for row in self.saved]
        self.loaded = set()
        self.provider_calls, self.search_calls = [], []

        def profile(authorization: str | None = Header(None)):
            if authorization != "Bearer fixture":
                raise HTTPException(401)
            return copy.deepcopy(self.profile)

        def saved(search_id, current_profile):
            self.provider_calls.append((search_id, current_profile))
            if search_id == "forbidden":
                raise HTTPException(403)
            return {"items": copy.deepcopy(self.saved)} if search_id == "mine" else None

        def search(query, keys):
            self.search_calls.append(keys)
            return [{"bid_no": no, "revision": revision, "distance": 0.2} for no, revision in keys]

        self.args = dict(profile_dependency=profile, bids_provider=lambda: self.rows,
                         scoring_provider=lambda *a: None, checklist_provider=lambda *a: None,
                         search=search, search_results_provider=saved,
                         title_similarity=lambda q, titles: list(range(len(titles))),
                         loaded_keys_provider=lambda: self.loaded,
                         clock=lambda: "2026-10-23T10:00:00+09:00")
        self.client = self.client_with()
        self.headers = {"Authorization": "Bearer fixture"}
        self.url = "/bids?from=2026-10-01&to=2026-10-31&search_id=mine"

    def client_with(self, **overrides):
        app = FastAPI()
        app.include_router(create_bid_router(**{**self.args, **overrides}))
        return TestClient(app)

    def payload(self, *numbers):
        return {"from": "2026-10-01", "to": "2026-10-31",
                "bids": [{"bid_no": no, "revision": "000"} for no in numbers]}

    def test_twenty_listings_rank_without_body_and_keep_links(self):
        response = self.client.get(self.url, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(len(result["bids"]), 20)
        self.assertEqual(result["bids"][0]["bid_no"], "A24")
        self.assertEqual(result["ranking_kind"], "injected")
        self.assertEqual(result["stage"], "list_only")
        self.assertEqual(result["search_id"], "mine")
        self.assertEqual(result["bids"][0]["attachments"], self.saved[0]["attachments"])
        self.assertIn("업종 제한 있음, 대상 업종 미확인", result["bids"][0]["unknown"])
        self.assertFalse(self.search_calls)
        self.assertEqual(self.provider_calls[0], ("mine", self.profile))

    def test_search_id_missing_unknown_or_forbidden(self):
        for search_id, code in (("", 422), ("missing", 404), ("forbidden", 403)):
            url = self.url.replace("search_id=mine", f"search_id={search_id}")
            self.assertEqual(self.client.get(url, headers=self.headers).status_code, code)
        disconnected = self.client_with(search_results_provider=None)
        self.assertEqual(disconnected.get(self.url, headers=self.headers).status_code, 503)

    def test_raw_api_officer_fields_are_not_exposed(self):
        for row in self.saved:
            row.update(ntceInsttOfclNm="담당자 이름", ntceInsttOfclTelNo="전화번호",
                       ntceInsttOfclEmailAdrs="이메일", internal_owner="내부 사용자")
        response = self.client.get(self.url, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        for row in response.json()["bids"]:
            self.assertNotIn("ntceInsttOfclNm", row)
            self.assertNotIn("ntceInsttOfclTelNo", row)
            self.assertNotIn("ntceInsttOfclEmailAdrs", row)
            self.assertNotIn("internal_owner", row)

    def test_authentication_before_any_data_access(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.post("/bids/recheck", json=self.payload("A00")).status_code, 401)
        self.assertFalse(self.provider_calls)
        self.assertFalse(self.search_calls)

    def test_recheck_only_loaded_targets_and_no_new_api_search(self):
        self.loaded = {("A00", "000"), ("A01", "000"), ("A02", "000")}
        self.rows[1]["regions"] = ["부산"]
        response = self.client.post("/bids/recheck", headers=self.headers,
                                    json=self.payload("A00", "A01", "A03"))
        self.assertEqual(response.status_code, 200)
        statuses = [row["recheck"]["status"] for row in response.json()["bids"]]
        self.assertEqual(statuses, ["confirmed", "disqualified", "not_evaluated"])
        self.assertEqual(self.search_calls, [{("A00", "000")}])
        self.assertFalse(self.provider_calls)

    def test_recheck_duplicate_or_more_than_twenty_rejected(self):
        for payload in (self.payload("A00", "A00"), self.payload(*[f"A{i:02}" for i in range(21)])):
            self.assertEqual(self.client.post("/bids/recheck", headers=self.headers, json=payload).status_code, 422)

    def test_recheck_bad_identity_period_or_missing_revision_rejected(self):
        missing_revision = self.payload("A00")
        del missing_revision["bids"][0]["revision"]
        reverse = {**self.payload("A00"), "from": "2026-11-01"}
        for payload in (self.payload("   "), missing_revision, reverse):
            self.assertEqual(self.client.post("/bids/recheck", headers=self.headers, json=payload).status_code, 422)

    def test_connect_forwards_saved_search_and_loaded_keys(self):
        from integration_support import load_integration
        app = FastAPI()
        namespace = load_integration(app=app)
        namespace.update(get_extracted_scoring_table=self.args["scoring_provider"],
                         get_extracted_checklist=self.args["checklist_provider"],
                         stored_bids=lambda store: self.loaded)
        namespace["connect_bid_routes"](self.args["profile_dependency"],
            bids_provider=self.args["bids_provider"],
            search_results_provider=self.args["search_results_provider"],
            title_similarity=self.args["title_similarity"])
        client = TestClient(app)
        self.assertEqual(client.get(self.url, headers=self.headers).status_code, 200)
        # 저장 검색과 같은 search_id를 전달한다. 공고문 미적재 시 벡터 검색을 시도하지 않는다.
        self.assertEqual(client.post("/bids/recheck", headers=self.headers,
                                     json=self.payload("A00")).status_code, 422)
        result = client.post("/bids/recheck", headers=self.headers,
                             json={**self.payload("A00"), "search_id": "mine"})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["bids"][0]["recheck"]["status"], "not_evaluated")

    def test_score_preserves_rfp_409(self):
        def pending(*args):
            raise HTTPException(409, "제안요청서 준비 중")
        response = self.client_with(scoring_provider=pending).get("/bids/A00/score?revision=000", headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_agent_route_requires_auth_and_propagates_rfp_409(self):
        calls=[]
        async def model(messages,tools):
            calls.append(True)
            return {"content":"", "tool_calls":[]}
        def pending(*args):
            raise HTTPException(409,"제안요청서 준비 중")
        client=self.client_with(agent_model=model,scoring_provider=pending)
        payload={"bid_no":"A00","revision":"000"}
        self.assertEqual(client.post("/agent/score",json=payload).status_code,401)
        self.assertEqual(client.post("/agent/score",json=payload,headers=self.headers).status_code,409)
        self.assertFalse(calls)
        self.assertEqual(self.client.post("/agent/score",json=payload,headers=self.headers).status_code,404)

    def test_agent_route_uses_same_supplied_scoring_table(self):
        from bid_logic.evaluate import load_cases,scoring_table
        table=scoring_table(load_cases()["scoring_templates"][0])
        async def model(messages,tools):
            if any(m["role"]=="tool" for m in messages):
                return {"content":"", "tool_calls":[]}
            return {"content":"", "tool_calls":[{"id":i["id"],"name":"calc_score",
                    "arguments":{"item_id":i["id"]}} for i in table["items"]]}
        client=self.client_with(agent_model=model,scoring_provider=lambda no,rev:table,
            profile_dependency=lambda:load_cases()["profiles"][0])
        response=client.post("/agent/score",json={"bid_no":table["bid_no"],"revision":table["revision"]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["status"],"complete")
        self.assertEqual(response.json()["bid_no"],table["bid_no"])
        self.assertNotIn("total",response.json())

    def test_multiple_checklists_keep_bid_revision_and_ownership(self):
        def extracted(no, revision):
            return {"bid_no": no, "revision": revision, "documents": [
                {"id": "registration", "doc": "사업자등록증", "bid_no": no, "revision": revision,
                 "due": "2026-11-01T18:00:00+09:00", "sources": [
                     {"bid_no": no, "revision": revision, "filename": "rfp.pdf", "page": 1}]}], "schedule": []}
        client = self.client_with(checklist_provider=extracted)
        for no in ("A00", "A01"):
            response = client.get(f"/bids/{no}/checklist?revision=000", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result["bid_no"], no)
            self.assertTrue(result["documents"][0]["owned"])
            self.assertEqual(result["documents"][0]["d_day"], 9)


if __name__ == "__main__":
    unittest.main()
