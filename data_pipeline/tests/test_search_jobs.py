import io
import json
from datetime import date, datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from data_pipeline import search_jobs
from data_pipeline import collect_bids as collector
from data_pipeline.common import read_csv, write_json
from data_pipeline.knowledge import KnowledgeStore


def text_pdf():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                             NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
        NameObject('/F1'): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 10 250 Td (Evaluation criteria and requirements) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(content)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


class DocumentReadinessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = KnowledgeStore('pdf', root=self.root / 'indexes', model='local-char-ngram-v1')
        self.item = {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'bidNtceNm': 'Test',
                     'eorder_lookup_status': 'complete', 'eorder_attachments': [],
                     'bidNtceDtlUrl': 'https://www.g2b.go.kr/detail/B1',
                     'ntceSpecFileNm1': '공고문.pdf', 'ntceSpecDocUrl1': 'https://www.g2b.go.kr/notice',
                     'ntceSpecFileNm2': '제안요청서.pdf', 'ntceSpecDocUrl2': 'https://www.g2b.go.kr/rfp'}
        patcher = patch.object(search_jobs, 'root_dir', return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pdf = text_pdf()

    def download(self, url, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.pdf)

    def process(self, full=True, downloader=None):
        with patch.object(search_jobs.collector, 'download_file', side_effect=downloader or self.download):
            return search_jobs._process_bid(self.item, full, self.store, lambda _: None)

    def test_notice_download_does_not_mean_rfp_ready(self):
        self.item.pop('ntceSpecFileNm2')
        self.item.pop('ntceSpecDocUrl2')
        result = self.process()
        self.assertTrue(result['download_complete'])
        self.assertFalse(result['rfp_ready'])
        self.assertEqual(result['rfp_status'], 'not_listed')
        self.assertEqual(result['status'], 'partial_failed')
        self.assertEqual(result['detail_url'], self.item['bidNtceDtlUrl'])
        self.assertGreater(result['indexed_chunks'], 0)

    def test_search_reports_rfp_listing_without_claiming_readiness(self):
        saved = {'search_id': 'a' * 32, 'items': [self.item],
                 'request': {'queries': ['Test']}, 'collected_at': '2026-10-26',
                 'page_limit_reached': False}
        row = search_jobs._public_search(saved, False)['items'][0]
        self.assertTrue(row['rfp_listed'])
        self.assertNotIn('rfp_ready', row)
        self.assertEqual(row['attachments'][1]['url'], self.item['ntceSpecDocUrl2'])
        self.item.pop('ntceSpecDocUrl2')
        row = search_jobs._public_search(saved, False)['items'][0]
        self.assertFalse(row['rfp_listed'])
        self.assertTrue(row['notice_only'])
        self.assertIn('해당 공고는 공고문만 있다', row['warnings'][0])

    def test_empty_or_unidentified_attachment_list_is_not_notice_only(self):
        for item in ({'bidNtceNo': 'B1'},
                     {'bidNtceNo': 'B1', 'ntceSpecDocUrl1': 'https://www.g2b.go.kr/unknown'}):
            item['eorder_lookup_status'] = 'complete'
            saved = {'search_id': 'a' * 32, 'items': [item], 'request': {'queries': ['Test']},
                     'collected_at': '2026-10-26', 'page_limit_reached': False}
            row = search_jobs._public_search(saved, False)['items'][0]
            self.assertFalse(row['notice_only'])
            self.assertFalse(row['warnings'])

    def test_rfp_ready_requires_indexed_rfp_chunks_and_retains_source_url(self):
        result = self.process()
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['download_complete'])
        self.assertTrue(result['rfp_ready'])
        self.assertEqual(result['rfp_status'], 'ready')
        self.assertEqual(result['rfp_files'][0]['url'], self.item['ntceSpecDocUrl2'])
        self.assertGreater(result['rfp_files'][0]['indexed_chunks'], 0)
        _, records, _ = self.store.load()
        self.assertTrue(any(r['file_name'] == '제안요청서.pdf' for r in records))

    def test_eorder_rfp_and_agreement_are_downloaded_and_indexed(self):
        self.item.pop('ntceSpecDocUrl2')
        self.item['eorder_attachments'] = [
            {'bid_no': 'B1', 'bid_order': '000', 'file_name': '제안요청서.pdf',
             'url': 'https://www.g2b.go.kr/rfp', 'document_type': '제안요청서'},
            {'bid_no': 'B1', 'bid_order': '000', 'file_name': '기술지원협약서.pdf',
             'url': 'https://www.g2b.go.kr/agreement', 'document_type': '기타문서'}]
        result = self.process()
        self.assertTrue(result['rfp_ready'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['rfp_files'][0]['source'], 'eorder')
        agreement = next(f for f in result['files'] if 'agreement' in f['kinds'])
        self.assertGreater(agreement['indexed_chunks'], 0)
        self.assertFalse(agreement['rfp_ready'])

    def test_agreement_alone_does_not_count_as_rfp_ready(self):
        self.item.pop('ntceSpecDocUrl2')
        self.item['eorder_attachments'] = [
            {'bid_no': 'B1', 'bid_order': '000', 'file_name': '기술지원협약서.pdf',
             'url': 'https://www.g2b.go.kr/agreement', 'document_type': '기타문서'}]
        result = self.process()
        self.assertTrue(result['download_complete'])
        self.assertFalse(result['rfp_ready'])
        self.assertEqual(result['status'], 'partial_failed')

    def test_eorder_hwpx_uses_conversion_before_becoming_ready(self):
        import hashlib
        from data_pipeline.common import write_jsonl
        self.item.pop('ntceSpecDocUrl2')
        self.item['eorder_attachments'] = [
            {'bid_no': 'B1', 'bid_order': '000', 'file_name': '제안요청서.hwpx',
             'url': 'https://www.g2b.go.kr/rfp', 'document_type': '제안요청서'}]
        def convert(folder):
            rows = read_csv(folder / 'attachments.csv')
            rfp = next(r for r in rows if r['file_name'] == '제안요청서.hwpx')
            self.assertEqual(rfp['selected'], 'True')
            source = Path(rfp['local_path'])
            target = folder / 'converted' / (source.stem + '.pdf')
            target.parent.mkdir()
            target.write_bytes(self.pdf)
            write_jsonl(folder / 'conversions.jsonl', [{
                'original_path': str(source.resolve()),
                'original_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                'pdf_path': str(target), 'pdf_sha256': hashlib.sha256(self.pdf).hexdigest(),
                'status': 'converted'}])
        with patch.object(search_jobs.converter, 'convert_run', side_effect=convert) as tool:
            result = self.process()
        tool.assert_called_once()
        self.assertTrue(result['rfp_ready'])
        self.assertEqual(result['rfp_files'][0]['preparation_status'], 'extracted')
        self.assertEqual(result['rfp_files'][0]['source'], 'eorder')

    def test_notice_stage_reports_deferred_rfp_without_failing_notice(self):
        result = self.process(full=False)
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(result['download_complete'])
        self.assertFalse(result['rfp_ready'])
        self.assertEqual(result['rfp_status'], 'not_requested')

    def test_downloaded_but_unreadable_rfp_is_not_ready(self):
        def download(url, target):
            self.download(url, target)
            if url.endswith('/rfp'):
                # 유효한 빈 PDF는 다운로드 성공이어도 적재할 텍스트가 없다.
                from pypdf import PdfWriter
                writer = PdfWriter()
                writer.add_blank_page(width=300, height=300)
                writer.write(target)
        result = self.process(downloader=download)
        self.assertTrue(result['download_complete'])
        self.assertFalse(result['rfp_ready'])
        self.assertEqual(result['rfp_status'], 'not_indexed')
        self.assertEqual(result['status'], 'partial_failed')

    def test_failed_rfp_download_is_distinct_from_not_listed(self):
        def download(url, target):
            if url.endswith('/rfp'):
                raise search_jobs.collector.CollectionError('첨부 다운로드 실패')
            self.download(url, target)
        result = self.process(downloader=download)
        self.assertFalse(result['download_complete'])
        self.assertFalse(result['rfp_ready'])
        self.assertEqual(result['rfp_status'], 'download_failed')

    def test_conversion_failure_still_reports_download_complete(self):
        self.item['ntceSpecFileNm2'] = '제안요청서.hwpx'
        with patch.object(search_jobs.converter, 'convert_run', side_effect=RuntimeError('변환 실패')):
            result = self.process()
        self.assertTrue(result['download_complete'])
        self.assertFalse(result['rfp_ready'])
        self.assertEqual(result['rfp_status'], 'not_indexed')
        self.assertEqual(result['status'], 'failed')

    def test_same_revision_uses_refreshed_attachments_in_http_job_response(self):
        from fastapi.testclient import TestClient
        from data_pipeline.api import app
        search_id = 'a' * 32
        folder = self.root / search_id
        folder.mkdir()
        old = {k: v for k, v in self.item.items() if not k.endswith('2')}
        write_json(folder / 'search.json', {'items': [old]})
        job = search_jobs.create_job(search_id, [{'bid_no': 'B1', 'bid_order': '000'}], 'documents')
        with patch.object(search_jobs.collector, 'lookup_notice', return_value=self.item), \
                patch.object(search_jobs.collector, 'lookup_eorder_attachments', return_value=[]), \
                patch.object(search_jobs.collector, 'download_file', side_effect=self.download), \
                patch.object(search_jobs, 'KnowledgeStore', return_value=self.store):
            search_jobs.run_job(job['job_id'], 'test-key')
        response = TestClient(app).get('/jobs/' + job['job_id'])
        self.assertEqual(response.status_code, 200)
        bid = response.json()['bids'][0]
        self.assertFalse(bid['revision_changed'])
        self.assertTrue(bid['download_complete'])
        self.assertTrue(bid['rfp_ready'])
        manifest = read_csv(self.root / 'documents/B1_000/attachments.csv')
        self.assertEqual(len(manifest), 2)
        refreshed = json.loads((folder / 'revision-B1-000.json').read_text())
        self.assertEqual(refreshed['ntceSpecDocUrl2'], self.item['ntceSpecDocUrl2'])


class DeadlineSearchTests(unittest.TestCase):
    def test_deadline_bounds_include_end_of_day_and_use_seoul_timezone(self):
        for raw, expected in [('2026-11-01 00:00:00', True), ('2026-11-30 23:59:59', True),
                              ('2026-11-30T15:00:00Z', False), ('2026-10-31T15:00:00Z', True),
                              ('2026-10-31 23:59:59', False), ('', False), ('invalid', False)]:
            with self.subTest(raw=raw):
                self.assertEqual(collector.deadline_in_period({'bidClseDt': raw},
                                 date(2026, 11, 1), date(2026, 11, 30)), expected)

    def test_filter_happens_before_candidate_limit(self):
        items = [{'bidNtceNo': 'OLD', 'bidClseDt': '2026-10-01 12:00'},
                 {'bidNtceNo': 'UNKNOWN', 'bidClseDt': ''},
                 {'bidNtceNo': 'MATCH', 'bidClseDt': '2026-11-15 12:00'}]
        with patch.object(collector, 'fetch_page', return_value=(items, 3)), \
                patch.object(collector.clock, 'sleep'):
            found, _ = collector.search_candidates('test', date(2026, 10, 20), date(2026, 10, 26),
                                                   ['웹'], 1,
                                                   deadline_period=(date(2026, 11, 1), date(2026, 11, 30)))
        self.assertEqual([i['bidNtceNo'] for i in found], ['MATCH'])

    def test_live_search_finds_earlier_publication_and_does_not_query_future_postings(self):
        item = {'bidNtceNo': 'EARLIER', 'bidNtceOrd': '000', 'bidNtceDt': '2026-10-15 09:00',
                'bidClseDt': '2026-11-15 18:00', 'bidNtceNm': '웹 개발',
                'ntceSpecDocUrl1': 'https://www.g2b.go.kr/notice', 'ntceSpecFileNm1': '공고문.pdf'}
        windows = []
        def fetch(key, start, end, query, page):
            windows.append((start, end))
            rows = [item] if start <= date(2026, 10, 15) <= end else []
            return rows, len(rows)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(search_jobs, 'root_dir', return_value=Path(tmp)), \
                patch.object(search_jobs, 'datetime') as clock, \
                patch.dict(os.environ, {'BID_SEARCH_LOOKBACK_DAYS': '14'}), \
                patch.object(collector, 'fetch_page', side_effect=fetch), \
                patch.object(collector, 'lookup_eorder_attachments', return_value=[]), \
                patch.object(search_jobs.restrictions, 'lookup_restrictions', return_value={
                    'region_restriction': {'lookup_status': 'complete', 'status': 'not_listed'},
                    'industry_restriction': {'lookup_status': 'complete', 'status': 'none'}}), \
                patch.object(collector.clock, 'sleep'):
            clock.now.return_value = datetime(2026, 10, 26, 10)
            result = search_jobs.search_bids(date(2026, 11, 1), date(2026, 11, 30), ['웹'], 20, 'test')
            self.assertEqual([r['bid_no'] for r in result['items']], ['EARLIER'])
            self.assertEqual(result['date_basis'], 'deadline')
            self.assertTrue(result['items'][0]['notice_only'])
            self.assertTrue(all(end <= date(2026, 10, 26) for start, end in windows))
            self.assertEqual(min(start for start, end in windows), date(2026, 10, 12))
            # 같은 조건은 새 마감일 기준 스냅샷만 캐시로 재사용한다.
            cached = search_jobs.search_bids(date(2026, 11, 1), date(2026, 11, 30), ['웹'], 20, 'test')
            self.assertTrue(cached['cached'])
            self.assertEqual(cached['search_id'], result['search_id'])

    def test_offline_cli_retains_publication_search_behavior(self):
        items = [{'bidNtceNo': 'A', 'bidClseDt': ''}]
        with patch.object(collector, 'fetch_page', return_value=(items, 1)), \
                patch.object(collector.clock, 'sleep'):
            found, _ = collector.search_candidates('test', date(2026, 10, 20), date(2026, 10, 26), ['웹'], 20)
        self.assertEqual(found, items)




if __name__ == '__main__':
    unittest.main()
