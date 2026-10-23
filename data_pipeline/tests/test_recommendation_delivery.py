"""실제 bid_logic + PDF 추출 + FAISS + 선택/원본 전달 API의 경계 검사."""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from data_pipeline.api import app
from data_pipeline.bid_workflow import prepare_discovery, write_json
from data_pipeline.collect_bids import CollectionError
from data_pipeline.delivery import build_archive, select_for_delivery, DeliveryIncomplete
from data_pipeline.recommendations import recommend_run, read_recommendations, _bid


def pdf(text):
    writer = PdfWriter()
    page = writer.add_blank_page(width=500, height=500)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
        NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
        DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(('BT /F1 12 Tf 10 450 Td (' + text + ') Tj ET').encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(content)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def candidate(no, text, deadline='2099-01-01 18:00:00'):
    return dict(bidNtceNo=no, bidNtceOrd='000', bidNtceNm=text,
        ntceKindNm='등록공고', bidNtceDt='2026-10-20 10:00:00', bidClseDt=deadline,
        dminsttNm='기관', presmptPrce='100000000', bidNtceDtlUrl=f'https://www.g2b.go.kr/{no}',
        ntceSpecFileNm1='입찰공고문.pdf', ntceSpecDocUrl1=f'https://www.g2b.go.kr/{no}/notice',
        ntceSpecFileNm2='신청서.hwp', ntceSpecDocUrl2=f'https://www.g2b.go.kr/{no}/form',
        ntceSpecFileNm3='안내.zip', ntceSpecDocUrl3=f'https://www.g2b.go.kr/{no}/other')


class RecommendationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run_id = 'a' * 32
        self.run = self.root / self.run_id
        self.run.mkdir()
        self.items = [candidate('WEB', 'cloud web chatbot'), candidate('ROAD', 'road construction'),
                      candidate('OLD', 'cloud web', '2020-01-01 12:00:00')]
        self.requests = []
        self.environment = patch.dict(os.environ, {'BID_DISCOVERY_ROOT': str(self.root),
            'BID_EMBEDDING_MODEL': 'local-char-ngram-v1', 'DATA_GO_KR_SERVICE_KEY': 'TEST_NOT_REAL'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.download = patch('data_pipeline.g2b_client.download_file', side_effect=self.receive)
        self.download.start()
        self.addCleanup(self.download.stop)
        self.profile = {'keywords': ['cloud web chatbot'], 'region': '울산',
                        'track_records': [{'summary': 'cloud web'}]}
        write_json(self.run / 'candidates.json', {'items': self.items,
            'request': {'start': '2026-10-01', 'end': '2026-10-23', 'queries': ['개발']}})
        self.client = TestClient(app)

    def receive(self, url, target):
        self.requests.append(url)
        target.parent.mkdir(parents=True, exist_ok=True)
        no = url.split('/')[-2]
        text = next(b['bidNtceNm'] for b in self.items if b['bidNtceNo'] == no)
        target.write_bytes(pdf(text) if url.endswith('/notice') else b'ORIGINAL HWP OR ZIP BYTES')

    def prepare(self):
        return prepare_discovery(self.run, self.profile)

    def test_pdf_ranking_calls_real_logic_excludes_expired_and_preserves_unknowns(self):
        self.prepare()
        result = recommend_run(self.run, now=datetime(2026, 10, 23))
        self.assertEqual(result['recommended_bid_ids'][0], 'WEB_000')
        self.assertEqual([b['bid_no'] for b in result['excluded']], ['OLD'])
        self.assertTrue(result['bids'][0]['sources'])
        self.assertIn('licenses 제한 미확인', result['bids'][0]['unknown'])
        self.assertEqual(result['bids'][0]['licenses'], None)
        self.assertEqual(result['bids'][0]['revision'], '000')
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(all(url.endswith('/notice') for url in self.requests))

    def test_vue_flow_selects_two_and_downloads_exact_originals(self):
        with patch('data_pipeline.api.collector.search_candidates', return_value=(self.items, False)):
            response = self.client.post('/bid-runs', json={'start': '2026-10-01', 'end': '2026-10-23',
                'queries': ['개발'], 'company_profile': self.profile})
        self.assertEqual(response.status_code, 201, response.text)
        run_id = response.json()['run_id']
        base = f'/bid-runs/{run_id}'
        recommended = self.client.get(base + '/recommendations').json()
        self.assertEqual(recommended['recommended_bid_ids'][0], 'WEB_000')
        self.assertEqual(len(self.requests), 3)
        selected = self.client.post(base + '/selection', json={'bid_ids': ['WEB_000', 'ROAD_000']})
        self.assertEqual(selected.status_code, 200, selected.text)
        delivery = selected.json()
        self.assertTrue(delivery['complete'])
        self.assertEqual(len(self.requests), 7)
        self.assertFalse(any('/OLD/form' in url or '/OLD/other' in url for url in self.requests))
        zipped = self.client.get(delivery['download_url'])
        self.assertEqual(zipped.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
            files = [n for n in archive.namelist() if n.endswith('.hwp')]
            self.assertEqual(len(files), 2)
            self.assertEqual(archive.read(files[0]), b'ORIGINAL HWP OR ZIP BYTES')
            self.assertTrue(all(not n.startswith('OLD_') for n in archive.namelist()))
        attachment = next(a for a in delivery['items'][0]['attachments'] if a['file_name'].endswith('.hwp'))
        downloaded = self.client.get(attachment['download_url'])
        self.assertEqual(downloaded.content, b'ORIGINAL HWP OR ZIP BYTES')
        self.assertIn('filename*=', downloaded.headers['content-disposition'])
        with patch('data_pipeline.bid_workflow._prepare_notices', side_effect=AssertionError('변환 금지')):
            self.assertEqual(self.client.post(base + '/selection', json={'bid_ids': ['WEB_000']}).status_code, 200)
        self.assertEqual(len(self.requests), 7)

    def test_invalid_selections_have_no_side_effects(self):
        self.prepare()
        for ids in ([], ['WEB_000'] * 2, ['WEB_000', 'ROAD_000', 'OLD_000'], ['WEB_000', 'NO_000']):
            response = self.client.post(f'/bid-runs/{self.run_id}/selection', json={'bid_ids': ids})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(self.requests), 3)
        self.assertFalse((self.run / 'user_selections.json').exists())
        self.assertEqual(self.client.get(f'/bid-runs/{self.run_id}/download').status_code, 409)
        self.assertEqual(self.client.get(f'/bid-runs/{self.run_id}/bids/WEB_000/attachments/fake').status_code, 404)

    def test_partial_failure_blocks_zip_and_retries_only_failed_attachment(self):
        self.prepare()
        def flaky(url, target):
            if url.endswith('/form'):
                raise CollectionError('일시 실패')
            return self.receive(url, target)
        with patch('data_pipeline.g2b_client.download_file', side_effect=flaky):
            result = select_for_delivery(self.run, ['WEB_000'])
        self.assertFalse(result['complete'])
        with self.assertRaises(DeliveryIncomplete):
            build_archive(self.run)
        before = len(self.requests)
        self.assertTrue(select_for_delivery(self.run, ['WEB_000'])['complete'])
        self.assertEqual(len(self.requests), before + 1)
        build_archive(self.run)

    def test_profile_change_invalidates_recommendations(self):
        self.prepare()
        recommend_run(self.run)
        self.assertIsNotNone(read_recommendations(self.run))
        prepare_discovery(self.run, {'keywords': ['road']})
        self.assertIsNone(read_recommendations(self.run))
        self.assertEqual(self.client.get(f'/bid-runs/{self.run_id}/recommendations').status_code, 409)

    def test_invalid_profile_is_rejected_before_collection(self):
        with patch('data_pipeline.api.collector.search_candidates') as search:
            response = self.client.post('/bid-runs', json={'start': '2026-10-01', 'end': '2026-10-23',
                'company_profile': {'keywords': ['web'], 'region': '서울 강남구'}})
            self.assertEqual(response.status_code, 422, response.text)
            search.assert_not_called()

    def test_query_only_avoids_pdf_and_recommendation(self):
        with patch('data_pipeline.api.collector.search_candidates', return_value=(self.items, False)):
            result = self.client.post('/bid-runs', json={'start': '2026-10-01', 'end': '2026-10-23', 'search_only': True})
        self.assertEqual(result.status_code, 201, result.text)
        self.assertIsNone(result.json()['recommendations'])
        self.assertEqual(self.requests, [])

    def test_complex_region_conditions_are_not_flattened(self):
        self.prepare()
        request = json.loads((self.run / 'evaluation_inputs.jsonl').read_text().splitlines()[0])
        with patch('data_pipeline.recommendations.region_requirement', return_value={
                'status': 'restricted', 'regions': ['울산광역시'], 'complex': True}):
            self.assertIsNone(_bid(request)['regions'])

    def test_hwp_notice_is_converted_but_selected_application_form_is_not(self):
        from data_pipeline.convert_documents import convert_run
        item = self.items[0]
        item['ntceSpecFileNm1'] = '입찰공고문.hwp'
        write_json(self.run / 'candidates.json', {'items': [item],
            'request': {'start': '2026-10-01', 'end': '2026-10-23'}})
        converted = []

        def converter(source, target, soffice):
            converted.append(source.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(pdf('cloud web chatbot'))

        def run(root):
            return convert_run(root, config={'soffice': 'test-only'}, converter=converter)

        with patch('data_pipeline.convert_documents.convert_run', side_effect=run):
            self.prepare()
            self.assertEqual(converted, ['01_입찰공고문.hwp'])
            self.assertTrue(select_for_delivery(self.run, ['WEB_000'])['complete'])
        self.assertEqual(converted, ['01_입찰공고문.hwp'])
        with zipfile.ZipFile(build_archive(self.run)) as archive:
            self.assertTrue(any(name.endswith('입찰공고문.hwp') for name in archive.namelist()))
            self.assertTrue(any(name.endswith('신청서.hwp') for name in archive.namelist()))
            self.assertFalse(any(name.endswith('.pdf') for name in archive.namelist()))

    def test_recommendation_failure_returns_run_id_for_retry_without_recollection(self):
        with patch('data_pipeline.api.collector.search_candidates', return_value=(self.items, False)), \
                patch('data_pipeline.api.recommend_run', side_effect=RuntimeError('sensitive SDK error')):
            result = self.client.post('/bid-runs', json={'start': '2026-10-01', 'end': '2026-10-23',
                'company_profile': self.profile})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('sensitive SDK error', result.text)
        self.assertTrue((self.root / result.json()['detail']['run_id'] / 'bid_list.json').is_file())

    def test_outside_file_cannot_be_delivered_via_manifest(self):
        self.prepare()
        select_for_delivery(self.run, ['WEB_000'])
        path = self.run / 'bid_list.json'
        listing = json.loads(path.read_text())
        listing['items'][0]['attachments'][0]['local_path'] = str(self.run / 'company_profile.json')
        write_json(path, listing)
        with self.assertRaises(DeliveryIncomplete):
            build_archive(self.run)

    def test_bracketed_notice_filename_is_recognized_and_pdf_preferred(self):
        from data_pipeline.bid_workflow import notice_attachment
        item = dict(bidNtceNo='LABEL', ntceSpecFileNm1='(공고) 개발 용역.hwp',
            ntceSpecDocUrl1='https://www.g2b.go.kr/hwp',
            ntceSpecFileNm2='(공고) 개발 용역.pdf', ntceSpecDocUrl2='https://www.g2b.go.kr/pdf',
            ntceSpecFileNm3='(공고) 신청서 양식.hwp', ntceSpecDocUrl3='https://www.g2b.go.kr/form')
        self.assertEqual(notice_attachment(item)[2], 'https://www.g2b.go.kr/pdf')
        self.assertIsNone(notice_attachment(dict(bidNtceNo='FORM',
            ntceSpecFileNm1='(공고) 신청서 양식.hwp', ntceSpecDocUrl1='https://www.g2b.go.kr/form')))

    def test_registration_deadline_does_not_replace_bid_closing_time(self):
        self.prepare()
        request = json.loads((self.run / 'evaluation_inputs.jsonl').read_text().splitlines()[0])
        with patch('data_pipeline.recommendations.extract_deadlines', return_value=[
                {'kind': 'registration', 'deadline': '2020-01-01 12:00:00'}]):
            self.assertEqual(_bid(request)['deadline'], '2099-01-01 18:00:00')

    def test_missing_notice_never_downloads_requirement_or_application_instead(self):
        item = dict(self.items[0])
        item['ntceSpecFileNm1'] = '제안요청서.pdf'
        write_json(self.run / 'candidates.json', {'items': [item],
            'request': {'start': '2026-10-01', 'end': '2026-10-23'}})
        listing = self.prepare()
        self.assertEqual(self.requests, [])
        bid = listing['items'][0]
        self.assertEqual(bid['notice_status'], 'notice_not_identified')
        self.assertIsNone(bid['evaluation']['score'])
        self.assertTrue(all(a['status'] == 'deferred' for a in bid['attachments']))
        self.assertEqual((self.run / 'evaluation_inputs.jsonl').read_text(), '')

    def test_external_result_only_stores_score_and_profile_change_invalidates_it(self):
        from data_pipeline.bid_workflow import record_evaluation
        listing = self.prepare()
        bid = listing['items'][0]
        self.assertIsNone(bid['evaluation']['score'])
        before = list(self.requests)
        payload = {'evaluation_input_id': bid['evaluation_input_id'],
                   'score': 8, 'max_score': 10, 'evaluator_version': 'external-test-fixture'}
        stored = record_evaluation(self.run, bid['bid_id'], payload)
        self.assertEqual(stored['score'], 8)
        self.assertEqual(self.requests, before)
        self.assertFalse((self.run / 'user_selections.json').exists())
        listing = prepare_discovery(self.run, {'keywords': ['road']})
        changed = next(b for b in listing['items'] if b['bid_id'] == bid['bid_id'])
        self.assertNotEqual(changed['evaluation_input_id'], bid['evaluation_input_id'])
        self.assertEqual(changed['evaluation']['status'], 'pending')
        self.assertIsNone(changed['evaluation']['score'])
        self.assertEqual(self.requests, before)
        with self.assertRaises(ValueError):
            record_evaluation(self.run, bid['bid_id'], payload)


if __name__ == '__main__':
    unittest.main()
