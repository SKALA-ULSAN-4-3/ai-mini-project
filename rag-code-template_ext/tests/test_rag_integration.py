"""2번 연결 계층(knowledge_bridge)과 3번 입력 규격의 호환 검증. LLM · 네트워크 호출 없음.

1번 저장소 형식으로 만든 임시 인덱스(local-char-ngram-v1 임베딩)를 LangChain FAISS로 감싸
2번 검색과 3번 faiss_hits가 함께 동작하는지, 2번 추출 결과가 3번 계산기 · 체크리스트를 통과하는지 확인한다.
"""
import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

try:
    import knowledge_bridge as kb
    from data_pipeline.knowledge import KnowledgeStore
    from bid_logic import faiss_hits, load_bids_csv
    from bid_logic.scoring import calculate_scores
    from bid_logic.checklist import build_checklist
except ImportError as error:  # FAISS · LangChain이 없는 환경
    kb = None
    IMPORT_ERROR = error


def record(bid_no, order, page, text, name="rfp.pdf"):
    return {"chunk_id": f"{bid_no}-{order}-{page}-{abs(hash(text))}", "group_id": f"{bid_no}_{order}:{name}",
            "text": text, "bid_no": bid_no, "bid_order": order, "file_name": name, "page": page,
            "collected_at": "2026-10-23", "source_url": "https://example.test/" + name}


@unittest.skipIf(kb is None, "FAISS/LangChain 미설치")
class BridgeStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = KnowledgeStore("pdf", root=self.tmp.name, model="local-char-ngram-v1")
        store.upsert([record("R1", "000", 1, "계약방법 일반경쟁입찰 협상에 의한 계약 총액계약"),
                      record("R1", "000", 2, "제출 서류 제안서 가격 산출내역서 사업자등록증 사본"),
                      record("R2", "001", 1, "용역기간 착수일로부터 13주 이내 결제 인프라 구축")])
        self.index, self.records, self.manifest = store.load()

    def tearDown(self):
        self.tmp.cleanup()

    def test_metadata_follows_bid_logic_names(self):
        meta = kb.normalize_metadata(self.records[0])
        self.assertEqual((meta["bid_no"], meta["revision"], meta["filename"]), ("R1", "000", "rfp.pdf"))
        self.assertEqual(meta["source"], "rfp.pdf")

    def test_wrapped_store_ranks_like_inner_product(self):
        lc = kb.build_langchain_store(self.index, self.records, self.manifest)
        self.assertEqual(lc.index.ntotal, 3)
        docs = lc.similarity_search_with_score("결제 인프라 구축 기간", k=3)
        distances = [d for _, d in docs]
        self.assertEqual(distances, sorted(distances), "L2 거리는 작을수록 유사해야 3번 추천과 맞음")
        self.assertEqual(docs[0][0].metadata["bid_no"], "R2")

    def test_bid_logic_faiss_hits_accepts_wrapped_store(self):
        lc = kb.build_langchain_store(self.index, self.records, self.manifest)
        hits = faiss_hits(lc, "계약방법 총액계약", {("R1", "000"), ("R2", "001")})
        self.assertEqual({(h["bid_no"], h["revision"]) for h in hits}, {("R1", "000"), ("R2", "001")})
        best = min(hits, key=lambda h: h["distance"])
        self.assertEqual((best["bid_no"], best["revision"]), ("R1", "000"))

    def test_filter_by_bid_and_revision(self):
        lc = kb.build_langchain_store(self.index, self.records, self.manifest)
        docs = lc.similarity_search("기간", k=3, filter={"bid_no": "R1", "revision": "000"}, fetch_k=3)
        self.assertTrue(docs and all(d.metadata["bid_no"] == "R1" for d in docs))


@unittest.skipIf(kb is None, "FAISS/LangChain 미설치")
class BidsCsvConversionTest(unittest.TestCase):
    def test_pipeline_csv_loads_in_bid_logic(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "src.csv", Path(tmp) / "dst.csv"
            fields = ["bid_no", "bid_order", "title", "agency", "published_at", "deadline", "estimated_price",
                      "allocated_budget", "detail_url", "region_status", "region_restriction", "file_names",
                      "metadata_needs_review"]
            rows = [
                {"bid_no": "R1", "bid_order": "000", "title": "A", "agency": "기관", "published_at": "2026-10-20 10:00:00",
                 "deadline": "2026-11-03 10:00:00", "estimated_price": "74000000", "allocated_budget": "81,400,000",
                 "detail_url": "u", "region_status": "restricted", "region_restriction": "울산광역시",
                 "file_names": "a.pdf;b.pdf", "metadata_needs_review": "false"},
                {"bid_no": "R2", "bid_order": "001", "title": "B", "agency": "기관", "published_at": "2026-10-21",
                 "deadline": "2026-11-05", "estimated_price": "", "allocated_budget": "", "detail_url": "",
                 "region_status": "not_stated", "region_restriction": "", "file_names": "", "metadata_needs_review": ""},
            ]
            with src.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)
            self.assertEqual(kb.convert_bids_csv(src, dst), 2)
            loaded = {r["bid_no"]: r for r in load_bids_csv(dst)}
            self.assertEqual(loaded["R1"]["regions"], ["울산"])
            self.assertEqual(loaded["R1"]["budget"], "81400000")
            self.assertEqual(loaded["R1"]["deadline"], "2026-11-03T10:00+09:00")
            self.assertIsNone(loaded["R2"]["regions"])      # 미명시는 제한 없음이 아니라 미확인
            self.assertIsNone(loaded["R2"]["deadline"])     # 시각 없는 마감은 만들지 않음
            self.assertIsNone(loaded["R1"]["industries"])   # 자유 텍스트 조건은 확정하지 않음


@unittest.skipIf(kb is None, "FAISS/LangChain 미설치")
class ExtractionToBidLogicTest(unittest.TestCase):
    REF = {"bid_no": "R1", "revision": "000", "filename": "rfp.pdf", "page": 12, "collected_at": "2026-10-23"}

    def test_scoring_payload_passes_calculator(self):
        extraction = {"items": [
            {"item": "웹툰 산업 이해도", "section": "이해", "max_score": 8, "criteria": "", "eval_type": "정성",
             "source_refs": [self.REF], "rule": None},
            {"item": "신용등급", "section": "역량", "max_score": 5, "criteria": "신용등급별 점수", "eval_type": "정량",
             "source_refs": [self.REF],
             "rule": {"metric": {"field": "credit_rating"}, "rule": {"type": "category", "values": {"A": 5, "B": 3}}}},
            {"item": "유사 실적", "section": "역량", "max_score": 6, "criteria": "", "eval_type": "정량",
             "source_refs": [self.REF], "rule": None},
            {"item": "입찰가격평가", "section": "가격", "max_score": 10, "criteria": "산식", "eval_type": "가격",
             "source_refs": [self.REF], "rule": None},
        ]}
        table = kb.to_bid_logic_scoring(extraction, "R1", "000")
        result = calculate_scores(table, {"credit_rating": "A"}, "R1", "000")
        status = {i["item"]: (i["status"], i["expected"]) for i in result["items"]}
        self.assertEqual(status["신용등급"], ("calculated", 5.0))
        self.assertEqual(status["웹툰 산업 이해도"][0], "manual")
        self.assertEqual(status["유사 실적"][0], "manual")       # 산정표가 없으면 추정하지 않고 담당자 판단
        self.assertEqual(status["입찰가격평가"][0], "manual")

    def test_checklist_payload_passes_builder(self):
        extraction = {"docs": [{"doc_name": "제안서", "note": "PDF", "source_refs": [self.REF]},
                               {"doc_name": "사업자등록증 사본", "note": "", "source_refs": [self.REF]}],
                      "due_iso": "2026-11-03T10:00+09:00", "due_note": "제출 기한 원문: 2026. 11. 3.(화) 10:00",
                      "schedule": [{"event": "개찰", "when": "2026. 11. 3.(화) 11:00", "due_iso": "2026-11-03T11:00+09:00",
                                    "source_refs": [self.REF]},
                                   {"event": "제안서 평가", "when": "2026. 11. 4.(수)", "due_iso": None,
                                    "source_refs": [self.REF]}]}
        payload = kb.to_bid_logic_checklist(extraction, "R1", "000")
        out = build_checklist(payload, {"owned_docs": ["사업자등록증 사본"]}, "R1", "000",
                              now="2026-10-25T09:00+09:00")
        owned = {d["doc"]: d["owned"] for d in out["documents"]}
        self.assertEqual(owned, {"제안서": False, "사업자등록증 사본": True})
        self.assertEqual(out["documents"][0]["d_day"], 9)
        events = {e["event"]: e["status"] for e in out["schedule"]}
        self.assertEqual(events, {"개찰": "upcoming", "제안서 평가": "unknown"})

    def test_attachment_kinds_from_real_api_names(self):
        # 2026-10 실제 API 검색 결과의 파일명
        self.assertEqual(kb.classify_attachment("(공고문) 2027년 용인시보건소 PACS.pdf"), {"notice"})
        self.assertEqual(kb.classify_attachment("입찰공고서_지방_1468+0036_유지관리.hwpx"), {"notice"})
        self.assertEqual(kb.classify_attachment("[제안요청서] 2027년 침해신고센터.hwp"), {"rfp"})
        self.assertEqual(kb.classify_attachment("(과업내용서)2027년 용인시.hwpx"), {"rfp"})
        self.assertEqual(kb.classify_attachment("입찰참가_첨부양식(용역).hwp"), {"other"})
        self.assertIn("cancel", kb.classify_attachment("취소공고서.hwpx"))

    def test_due_parser(self):
        self.assertEqual(kb.to_iso_due("2026.10.23.(금)09:00~11.3.(화)\n10:00"), "2026-11-03T10:00+09:00")
        self.assertIsNone(kb.to_iso_due("2026. 11. 5.(목) ~ 11. 11.(수)"))


if __name__ == "__main__":
    unittest.main()
