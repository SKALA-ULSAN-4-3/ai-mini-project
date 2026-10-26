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
from data_pipeline import bid_progress
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
                patch.object(search_jobs.bid_progress, 'lookup_progress', return_value={
                    'lookup_status': 'complete', 'opening_results': [], 'rebids': []}), \
                patch.object(collector, 'lookup_eorder_attachments', return_value=[]), \
                patch.object(search_jobs.restrictions, 'lookup_restrictions', return_value={
                    'region_restriction': {'lookup_status': 'complete', 'status': 'not_listed'},
                    'industry_restriction': {'lookup_status': 'complete', 'status': 'none'}}), \
                patch.object(bid_progress, 'lookup_progress', return_value={
                    'lookup_status': 'complete', 'opening_results': [], 'rebids': []}), \
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


class BidProgressTests(unittest.TestCase):
    now = datetime(2026, 10, 26, 10, tzinfo=collector.KST)

    def item(self, **changes):
        return {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'bidNtceNm': '웹 개발',
                'ntceKindNm': '등록공고', 'bidNtceDt': '2026-10-20 09:00',
                'bidClseDt': '2026-11-15 18:00', 'opengDt': '2026-11-16 10:00',
                'ntceSpecFileNm1': '공고문.pdf', 'ntceSpecDocUrl1': 'https://www.g2b.go.kr/notice',
                **changes}

    def row(self, round='000', **changes):
        return {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'bidClsfcNo': '1',
                'rbidNo': round, **changes}

    def evaluate(self, *, openings=(), rebids=(), now=None, **changes):
        item = self.item(**changes)
        item['bid_progress'] = {'lookup_status': 'complete', 'opening_results': list(openings),
                                'rebids': list(rebids)}
        return bid_progress.apply_progress(item, now or self.now)

    def test_opening_result_excludes_notice_even_if_original_deadline_is_future(self):
        result = self.evaluate(openings=[self.row(progrsDivCdNm='개찰완료', opengDt='2026-10-14 15:00')])
        self.assertFalse(result['bid_progress']['recommendable'])
        self.assertEqual(result['bid_progress']['label'], '마감')

    def test_future_opening_is_not_actual_completion(self):
        result = self.evaluate()
        self.assertTrue(result['bid_progress']['recommendable'])
        self.assertFalse(result['bid_progress']['opening_confirmed'])

    def test_elapsed_opening_excludes_unknown_deadline_without_claiming_actual_result(self):
        result = self.evaluate(bidClseDt='', opengDt='2026-10-14 15:00')
        self.assertEqual(result['bid_progress']['state'], 'closed')
        self.assertFalse(result['bid_progress']['opening_confirmed'])

    def test_active_rebid_uses_new_deadline_and_cached_result_expires(self):
        result = self.evaluate(bidClseDt='2026-10-12 17:00', opengDt='2026-10-14 15:00',
            openings=[self.row(progrsDivCdNm='재입찰', opengDt='2026-10-14 15:00')],
            rebids=[self.row('001', bidClseDt='2026-11-05 18:00', opengDt='2026-11-06 10:00')])
        self.assertEqual(result['bid_progress']['state'], 'rebidding')
        self.assertEqual(result['bidClseDt'], '2026-11-05 18:00')
        self.assertEqual(result['original_bidClseDt'], '2026-10-12 17:00')
        after = bid_progress.apply_progress(result, datetime(2026, 11, 5, 18, tzinfo=collector.KST))
        self.assertFalse(after['bid_progress']['recommendable'])

    def test_completed_rebid_cannot_be_reopened_by_old_schedule(self):
        result = self.evaluate(openings=[self.row('001', progrsDivCdNm='개찰완료')],
            rebids=[self.row('001', bidClseDt='2026-11-05 18:00')])
        self.assertFalse(result['bid_progress']['recommendable'])

    def test_latest_rebid_round_wins_over_older_future_deadline(self):
        result = self.evaluate(rebids=[self.row('001', bidClseDt='2026-11-05 18:00'),
                                       self.row('002', bidClseDt='2026-10-25 18:00')])
        self.assertFalse(result['bid_progress']['recommendable'])

    def test_different_classification_does_not_close_active_rebid(self):
        result = self.evaluate(openings=[self.row('001', bidClsfcNo='2', progrsDivCdNm='개찰완료')],
            rebids=[self.row('001', bidClseDt='2026-11-05 18:00')])
        self.assertEqual(result['bid_progress']['state'], 'rebidding')

    def test_other_notice_or_revision_is_not_used(self):
        for changed in ({'bidNtceNo': 'OTHER'}, {'bidNtceOrd': '001'}):
            with self.subTest(changed=changed):
                result = self.evaluate(openings=[self.row(progrsDivCdNm='개찰완료', **changed)])
                self.assertTrue(result['bid_progress']['recommendable'])

    def test_invalid_rebid_deadline_does_not_override_closed_notice(self):
        for deadline in ('', 'invalid', '2026-11-05'):
            with self.subTest(deadline=deadline):
                result = self.evaluate(openings=[self.row(progrsDivCdNm='재입찰')],
                    rebids=[self.row('001', bidClseDt=deadline)])
                self.assertFalse(result['bid_progress']['recommendable'])

    def test_lookup_filters_revision_and_never_stores_company_fields(self):
        payload = {'response': {'header': {'resultCode': '00'}, 'body': {'totalCount': 3, 'items': [
            self.row(opengCorpInfo='private company data'), self.row(bidNtceOrd='001'),
            self.row(bidNtceNo='OTHER')]}}}
        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        with patch.object(collector, 'build_opener') as opener:
            opener.return_value.open.return_value = Response(json.dumps(payload).encode())
            result = bid_progress.lookup_rows('result-test-key', 'B1', '000', bid_progress.OPERATIONS[0])
            self.assertEqual(len(result), 1)
            self.assertNotIn('opengCorpInfo', result[0])
            request = opener.return_value.open.call_args.args[0]
            from urllib.parse import parse_qs, urlparse
            params = parse_qs(urlparse(request.full_url).query)
            self.assertEqual(params['serviceKey'], ['result-test-key'])
            self.assertEqual(params['inqryDiv'], ['4'])

    def run_search(self, rows, lookup):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        with patch.object(search_jobs, 'root_dir', return_value=Path(temp.name)), \
                patch.object(search_jobs, 'datetime') as clock, \
                patch.dict(os.environ, {'DATA_GO_KR_SCSBID_SERVICE_KEY': 'separate-result-key',
                                        'BID_SEARCH_LOOKBACK_DAYS': '7'}), \
                patch.object(collector, 'fetch_page', return_value=(rows, len(rows))), \
                patch.object(bid_progress, 'lookup_progress', side_effect=lookup) as progress_lookup, \
                patch.object(search_jobs, '_enrich_candidate', side_effect=lambda item, key: item), \
                patch.object(collector.clock, 'sleep'):
            clock.now.return_value = self.now
            result = search_jobs.search_bids(date(2026, 11, 1), date(2026, 11, 30), ['웹'], 1, 'notice-key')
            return result, progress_lookup.call_args_list

    def test_search_checks_progress_before_limit_and_admits_rebid_outside_original_deadline(self):
        closed = self.item(bidNtceNo='CLOSED')
        rebid = self.item(bidNtceNo='REBID', bidClseDt='2026-10-12 17:00', rbidPermsnYn='Y')
        def lookup(key, no, order):
            self.assertEqual(key, 'separate-result-key')
            common = dict(bidNtceNo=no, bidNtceOrd=order, bidClsfcNo='1')
            return {'lookup_status': 'complete',
                    'opening_results': [{**common, 'rbidNo': '000', 'progrsDivCdNm': '개찰완료'}],
                    'rebids': [{**common, 'rbidNo': '001', 'bidClseDt': '2026-11-05 18:00'}] if no == 'REBID' else []}
        result, calls = self.run_search([closed, rebid], lookup)
        self.assertEqual([r['bid_no'] for r in result['items']], ['REBID'])
        self.assertEqual(result['items'][0]['deadline'], '2026-11-05 18:00')
        self.assertEqual(result['progress_excluded'][0]['bid_no'], 'CLOSED')
        self.assertEqual(len(calls), 2)

    def test_lookup_failure_is_excluded_instead_of_claiming_open(self):
        def unavailable(*args): raise collector.CollectionError('개찰 조회 HTTP 403')
        result, _ = self.run_search([self.item()], unavailable)
        self.assertFalse(result['items'])
        self.assertEqual(result['progress_excluded'][0]['status'], 'unavailable')

    def test_past_opening_with_missing_deadline_is_recorded_as_closed(self):
        item = self.item(bidClseDt='', opengDt='2026-10-14 15:00')
        result, calls = self.run_search([item], lambda *args: {
            'lookup_status': 'complete', 'opening_results': [], 'rebids': []})
        self.assertFalse(result['items'])
        self.assertEqual(result['progress_excluded'][0]['label'], '마감')
        self.assertEqual(len(calls), 1)

    def test_recommendation_api_omits_closed_notice_and_uses_new_rebid_deadline(self):
        import sys
        module_path = patch('sys.path', [str(collector.ROOT / 'rag-code-template_ext'), *sys.path])
        module_path.start()
        self.addCleanup(module_path.stop)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from bid_logic.api import create_bid_router
        import knowledge_bridge
        closed = self.evaluate(openings=[self.row(progrsDivCdNm='개찰완료')])
        active = self.evaluate(bidClseDt='2026-10-12 17:00',
            openings=[self.row(progrsDivCdNm='재입찰')],
            rebids=[self.row('001', bidClseDt='2026-11-05 18:00')])
        # 별도 공고로 바꾸며 근거의 공고번호도 함께 대응시킨다.
        closed['bidNtceNo'] = 'CLOSED'
        closed['bid_progress']['opening_results'][0]['bidNtceNo'] = 'CLOSED'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / ('a' * 32)
            folder.mkdir()
            write_json(folder / 'search.json', {'search_id': 'a' * 32, 'items': [closed, active],
                'request': {'from': '2026-11-01', 'to': '2026-11-30', 'queries': ['웹'], 'date_basis': 'deadline'},
                'collected_at': '2026-10-26', 'page_limit_reached': False})
            app = FastAPI()
            app.include_router(create_bid_router(profile_dependency=lambda: {'region': '서울', 'keywords': ['웹']},
                bids_provider=lambda: [], scoring_provider=lambda *args: None,
                checklist_provider=lambda *args: None, search=lambda *args, **kwargs: [],
                search_results_provider=knowledge_bridge.search_results, require_search_id=True,
                title_similarity=lambda query, titles: [1.0] * len(titles), clock=lambda: self.now))
            public = search_jobs._public_search
            with patch.object(search_jobs, 'root_dir', return_value=root), \
                    patch.object(search_jobs, '_public_search', side_effect=lambda s, c: public(s, c, self.now)):
                response = TestClient(app).get('/bids', params={
                    'from': '2026-11-01', 'to': '2026-11-30', 'search_id': 'a' * 32})
            self.assertEqual(response.status_code, 200, response.text)
            bids = response.json()['bids']
            self.assertEqual([row['bid_no'] for row in bids], ['B1'])
            self.assertTrue(bids[0]['deadline'].startswith('2026-11-05'))


if __name__ == '__main__':
    unittest.main()
