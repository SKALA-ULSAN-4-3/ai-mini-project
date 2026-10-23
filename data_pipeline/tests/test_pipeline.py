from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_pipeline.audit_dataset import clean_chunks
from data_pipeline.build_dataset import collect_dataset
from data_pipeline.collect_bids import parse_response
from data_pipeline.convert_documents import validate_text_quality
from data_pipeline.knowledge import KnowledgeStore, ingest_processed
from data_pipeline.metadata import extract_deadline, extract_deadlines
from data_pipeline.privacy import mask_personal

ROOT=Path(__file__).resolve().parents[1]


def page(text, bid="B1", number=1, doc="d1", converted=False):
    return dict(text=text,bid_no=bid,bid_order="000",document_id=doc,page=number,
                file_name="공고문.pdf",source_url="https://www.g2b.go.kr/file",requires_layout_review=converted)


class DataQualityTests(unittest.TestCase):
    def test_repeat_glyph_corruption_is_rejected(self):
        with self.assertRaises(RuntimeError): validate_text_quality(["입 "*120])

    def test_contacts_survive_name_masking(self):
        result=mask_personal("담당자 홍길동 02-1234-5678 hong@g2b.go.kr",["홍길동"])
        self.assertIn("02-1234-5678",result)
        self.assertIn("hong@g2b.go.kr",result)
        self.assertNotIn("홍길동",result)

    def test_page_dedupe_preserves_aliases_and_bid_boundaries(self):
        text="참가자격 제출서류 및 과업 내용 상세 설명 "*20
        pages=[page(text,doc="converted",converted=True),page(text,doc="original"),page(text,bid="B2",doc="other")]
        chunks=[{**p,"char_start":0,"char_end":len(text),"chunk_id":p["document_id"]} for p in pages]
        result,duplicates=clean_chunks(pages,chunks)
        self.assertEqual({r["document_id"] for r in result},{"original","other"})
        self.assertEqual(len(duplicates),1)
        self.assertEqual(len(result[0]["equivalent_sources"]),2)
        self.assertEqual(clean_chunks(pages,result)[0],result)

    def test_api_errors_do_not_expose_secret(self):
        with self.assertRaises(Exception) as raised: parse_response(b'<error><returnReasonCode>30</returnReasonCode><message>SECRETKEY</message></error>')
        self.assertNotIn("SECRETKEY",str(raised.exception))

    def test_deadline_is_not_notice_date(self):
        value,source=extract_deadline([page("공고일 2026.10.01\n입찰서 제출 마감일시: 2026.10.30 10:00")])
        self.assertEqual(value,"2026-10-30 10:00:00")
        self.assertEqual(source["page"],1)

    def test_date_range_uses_end_and_registration_stays_separate(self):
        ps=[page("입찰참가신청 2026.10.08.(목) ~ 18:00\n제안서 제출 파일 2026.11.11.(수) ~14:00\n입찰서 제출기간 2026.10.01 10:00 ~2026.10.30 11:00")]
        values=extract_deadlines(ps)
        self.assertIn(("registration","2026-10-08 18:00:00"),[(r["kind"],r["deadline"]) for r in values])
        self.assertIn(("proposal","2026-11-11 14:00:00"),[(r["kind"],r["deadline"]) for r in values])
        self.assertEqual(extract_deadline(ps)[0],"2026-10-30 11:00:00")

    def test_submission_period_under_proposal_heading(self):
        self.assertEqual(extract_deadline([page("5. 제안서 제출\n가. 직접 제출\n나. 제출기간: 2026. 8. 14.(금) 14:00까지")])[0],"2026-08-14 14:00:00")


class SelectionTests(unittest.TestCase):
    def test_latest_cancelled_notice_and_search_only_preserve_download_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def item(no,order="000",kind="등록공고"):
                return dict(bidNtceNo=no,bidNtceOrd=order,bidNtceNm="웹 시스템 개발",ntceKindNm=kind,
                            bidNtceDt="2026-08-03",ntceSpecFileNm1="공고문.pdf",ntceSpecDocUrl1="https://www.g2b.go.kr/a")
            payload={"request":{"start":"2026-08-01","end":"2026-10-23","queries":["개발"],"candidate_limit":120},
                     "items":[item("CANCEL"),item("CANCEL","001","취소공고"),item("GOOD")]}
            (root/"candidates.json").write_text(json.dumps(payload))
            before=b'keep downloaded manifest'
            (root/"attachments.csv").write_bytes(before)
            with patch("data_pipeline.collect_bids.download_file") as download:
                collect_dataset(root,date(2026,8,1),date(2026,10,23),count=1,
                                queries=["개발"],search_only=True)
                download.assert_not_called()
            self.assertEqual(json.loads((root/"selection.json").read_text()),["GOOD_000"])
            self.assertEqual((root/"attachments.csv").read_bytes(),before)


class IndexTests(unittest.TestCase):
    def test_full_refresh_removes_excluded_bids_without_reembedding_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            store=KnowledgeStore("pdf",root=temp,model="local-char-ngram-v1")
            def record(key,text):return dict(chunk_id=key,group_id=key,bid_no=key,bid_order="000",text=text)
            one,two=record("B1","웹 개발 참가자격"),record("B2","학사 시스템")
            store.upsert([one,two])
            with patch("data_pipeline.knowledge.Embedder.embed",side_effect=AssertionError("기존 벡터는 재사용해야 함")):
                store.upsert([one],replace_all=True)
            _,records,status=store.load()
            self.assertEqual([r["bid_no"] for r in records],["B1"])
            self.assertEqual(status["chunks"],1)

    def test_failed_validation_blocks_ingestion_before_network(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/"validation.json").write_text(json.dumps({"hard_failures":["bad PDF"]}))
            with self.assertRaises(ValueError):ingest_processed(root)


class IngestionApiTests(unittest.TestCase):
    def test_api_only_has_data_ingestion_routes(self):
        from data_pipeline.api import app
        self.assertEqual(set(app.openapi()['paths']),{'/upload-paper','/upload-topic','/data-status'})

    @staticmethod
    def pdf_bytes():
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter();p=writer.add_blank_page(width=300,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 10 250 Td (Contact 02-1234-5678 mail@g2b.go.kr) Tj ET')
        p[NameObject('/Contents')]=writer._add_object(content)
        result=io.BytesIO();writer.write(result);return result.getvalue()

    def test_pdf_upload_accumulates_and_preserves_page_sources(self):
        from fastapi.testclient import TestClient
        from data_pipeline.api import app
        with tempfile.TemporaryDirectory() as temp:
            store=KnowledgeStore('pdf',root=temp,model='local-char-ngram-v1')
            with patch('data_pipeline.api.store',return_value=store):
                client=TestClient(app)
                for bid in ('A','B','A'):
                    response=client.post('/upload-paper',data={'bid_no':bid,'source_url':f'https://www.g2b.go.kr/{bid}'},files={'file':('notice.pdf',self.pdf_bytes(),'application/pdf')})
                    self.assertEqual(response.status_code,200,response.text)
            _,records,status=store.load()
            self.assertEqual(status['bids'],2)
            self.assertEqual(len(records),2)
            self.assertTrue(all(r['page']==1 and r['source_url'] for r in records))
            self.assertTrue(all('02-1234-5678' in r['text'] for r in records))

    def test_topic_upload_accumulates_without_remote_requests(self):
        from fastapi.testclient import TestClient
        from data_pipeline.api import app
        with tempfile.TemporaryDirectory() as temp:
            store=KnowledgeStore('web',root=temp,model='local-char-ngram-v1')
            with patch('data_pipeline.api.store',return_value=store),patch('data_pipeline.api.topic_records') as topics:
                client=TestClient(app)
                for topic in ('topic1','topic2'):
                    topics.return_value=[dict(chunk_id=topic,group_id=topic,topic=topic,text='official source text',source_url='https://www.pps.go.kr')]
                    self.assertEqual(client.post('/upload-topic',params={'topic':topic}).status_code,200)
            self.assertEqual(store.status()['documents'],2)


class CorpusIntegrationTests(unittest.TestCase):
    @unittest.skipUnless((ROOT.parent/"data/corpus/validation.json").exists(),"로컬 데이터셋이 없으면 생략")
    def test_curated_corpus_coverage_provenance_and_no_cancelled_notice(self):
        root=ROOT.parent/"data/corpus"
        report=json.loads((root/"validation.json").read_text())
        self.assertEqual(report["bids"],20)
        self.assertFalse(report["hard_failures"])
        self.assertTrue(all(r["complete"] for r in report["document_coverage"]))
        self.assertEqual(len(list((root/"pdf20").glob('*.pdf'))),20)
        selected=json.loads((root/"selection.json").read_text())
        self.assertNotIn("R26BK01661660_000",selected)
        self.assertEqual(len(selected),len(set(selected)))
        chunks=[json.loads(l) for l in (root/"processed/chunks.jsonl").read_text().splitlines()]
        self.assertEqual(len(chunks),len({r['chunk_id'] for r in chunks}))
        for r in chunks:
            self.assertTrue(all(r.get(k) for k in ('bid_no','bid_order','file_name','page','source_url','collected_at')))


if __name__=="__main__":unittest.main()
