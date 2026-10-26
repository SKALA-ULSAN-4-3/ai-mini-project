import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from data_pipeline import collect_bids as collector
from data_pipeline import search_jobs


def attachment(number='B1', revision='000', name='제안요청서.hwpx', sequence=1):
    return {'bidNtceNo': number, 'bidNtceOrd': revision, 'atchSno': str(sequence),
            'eorderDocDivNm': '제안요청서', 'eorderAtchFileNm': name,
            'eorderAtchFileUrl': 'https://www.g2b.go.kr/pn/pnp/pnpe/UntyAtchFile/'
                               f'downloadRfpFile.do?rfpNo=R1&rfpOrd=000&rfpUntyAtchFileNo={sequence}'}


def response(items, total=None, code='00'):
    return io.BytesIO(json.dumps({'response': {'header': {'resultCode': code},
                       'body': {'items': items, 'totalCount': len(items) if total is None else total}}}).encode())


class EorderAttachmentTests(unittest.TestCase):



    def test_exact_scope_and_source_fields(self):
        rfp = attachment()
        agreement = attachment(name='기술지원협약서.pdf', sequence=2)
        agreement['eorderDocDivNm'] = '기타문서'
        opener = SimpleNamespace(open=lambda request, timeout: response(
            [attachment(revision='001'), attachment(number='OTHER'), rfp, agreement, rfp]))
        with patch.object(collector, 'build_opener', return_value=opener):
            files = collector.lookup_eorder_attachments('test-key', 'B1', '000')
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]['file_name'], '제안요청서.hwpx')
        self.assertEqual(files[1]['document_type'], '기타문서')
        self.assertTrue(all((f['bid_no'], f['bid_order'], f['source']) == ('B1', '000', 'eorder') for f in files))

    def test_pagination_and_request_parameters(self):
        calls = []
        def opened(request, timeout):
            query = parse_qs(urlparse(request.full_url).query)
            calls.append(query)
            return response([attachment(sequence=int(query['pageNo'][0]))], total=101)
        with patch.object(collector, 'build_opener', return_value=SimpleNamespace(open=opened)):
            files = collector.lookup_eorder_attachments('test-key', 'B1', '000')
        self.assertEqual(len(files), 2)
        self.assertEqual([c['pageNo'] for c in calls], [['1'], ['2']])
        self.assertTrue(all(c['inqryDiv'] == ['2'] and c['bidNtceOrd'] == ['000'] for c in calls))

    def test_missing_revision_or_nonofficial_url_is_rejected(self):
        for changed in ({'bidNtceOrd': ''}, {'eorderAtchFileUrl': 'https://example.test/rfp.hwpx'}):
            with self.subTest(changed=changed), \
                    patch.object(collector, 'build_opener', return_value=SimpleNamespace(
                        open=lambda request, timeout: response([{**attachment(), **changed}]))):
                with self.assertRaises(collector.CollectionError):
                    collector.lookup_eorder_attachments('test-key', 'B1', '000')

    def test_api_failure_is_not_an_empty_success_or_secret_leak(self):
        opener = SimpleNamespace(open=lambda request, timeout: response([], code='30'))
        with patch.object(collector, 'build_opener', return_value=opener):
            with self.assertRaises(collector.CollectionError) as caught:
                collector.lookup_eorder_attachments('private-test-key', 'B1', '000')
        self.assertNotIn('private-test-key', str(caught.exception))

    def test_merge_deduplicates_urls_and_rejects_other_revision(self):
        item = {'bidNtceNo': 'B1', 'bidNtceOrd': '000',
                'ntceSpecDocUrl1': 'https://www.g2b.go.kr/notice', 'ntceSpecFileNm1': '공고문.pdf',
                'eorder_attachments': [
                    {'bid_no': 'B1', 'bid_order': '000', 'file_name': '공고문.pdf', 'url': 'https://www.g2b.go.kr/notice'},
                    {'bid_no': 'B1', 'bid_order': '001', 'file_name': '다른차수.hwpx', 'url': 'https://www.g2b.go.kr/wrong'},
                    {'bid_no': 'B1', 'bid_order': '000', 'file_name': '제안요청서.hwpx', 'url': 'https://www.g2b.go.kr/rfp'}]}
        self.assertEqual(list(collector.attachments(item)), [
            ('공고문.pdf', 'https://www.g2b.go.kr/notice'), ('제안요청서.hwpx', 'https://www.g2b.go.kr/rfp')])

    def test_lookup_failure_clears_stale_eorder_files_and_does_not_claim_notice_only(self):
        item = {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'eorder_attachments': [{'stale': True}],
                'ntceSpecDocUrl1': 'https://www.g2b.go.kr/notice', 'ntceSpecFileNm1': '공고문.pdf'}
        with patch.object(collector, 'lookup_eorder_attachments', side_effect=collector.CollectionError('조회 실패')):
            enriched = search_jobs._enrich_eorder(item, 'test-key')
        saved = {'search_id': 'a' * 32, 'items': [enriched], 'request': {'queries': ['웹']},
                 'collected_at': '2026-10-26', 'page_limit_reached': False}
        row = search_jobs._public_search(saved, False)['items'][0]
        self.assertEqual(enriched['eorder_attachments'], [])
        self.assertEqual(row['attachment_lookup_status'], 'unavailable')
        self.assertFalse(row['notice_only'])
        self.assertTrue(row['warnings'])


if __name__ == '__main__':
    unittest.main()
