import io
import json
from datetime import date
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from data_pipeline import restrictions, search_jobs
from data_pipeline.collect_bids import CollectionError


def response(rows, total=None, code='00'):
    return io.BytesIO(json.dumps({'response': {'header': {'resultCode': code}, 'body': {
        'items': rows, 'totalCount': len(rows) if total is None else total}}}).encode())


class RestrictionDetailsTests(unittest.TestCase):
    def test_exact_notice_revision_and_pagination(self):
        calls = []
        def opened(request, timeout):
            query = parse_qs(urlparse(request.full_url).query)
            calls.append(query)
            if query['pageNo'] == ['1']:
                return response([{'bidNtceNo': 'B1', 'bidNtceOrd': '001'},
                                 {'bidNtceNo': 'OTHER', 'bidNtceOrd': '000'},
                                 {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'prtcptPsblRgnNm': '강원특별자치도'}], total=101)
            return response([{'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'prtcptPsblRgnNm': '서울특별시'}], total=101)
        with patch.object(restrictions.collector, 'build_opener', return_value=SimpleNamespace(open=opened)):
            rows = restrictions.lookup_rows('test-key', 'B1', '000', 'region')
        self.assertEqual([r['prtcptPsblRgnNm'] for r in rows], ['강원특별자치도', '서울특별시'])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(q['inqryDiv'] == ['2'] and q['bidNtceOrd'] == ['000'] for q in calls))

    def test_missing_revision_is_not_assumed_to_be_current(self):
        with patch.object(restrictions.collector, 'build_opener', return_value=SimpleNamespace(
                open=lambda request, timeout: response([{'bidNtceNo': 'B1'}]))):
            with self.assertRaises(CollectionError):
                restrictions.lookup_rows('test-key', 'B1', '000', 'industry')

    def test_license_codes_alternatives_groups_and_specialties_are_preserved(self):
        result = restrictions.industry_details([{
            'lmtGrpNo': '2', 'lmtSno': '1', 'lcnsLmtNm': '정보통신공사업/0036',
            'permsnIndstrytyList': '[소프트웨어사업자(컴퓨터관련서비스사업)/1468]',
            'indstrytyMfrcFldList': '[1^분야A^분야B]'}], 'Y')
        requirement = result['requirements'][0]
        self.assertEqual(requirement['code'], '0036')
        self.assertEqual(requirement['group_no'], '2')
        self.assertEqual(requirement['alternatives'][0]['code'], '1468')
        self.assertEqual(requirement['specialties'], '[1^분야A^분야B]')

    def test_empty_registration_and_explicit_none_are_distinct(self):
        self.assertEqual(restrictions.region_details([])['status'], 'not_listed')
        self.assertEqual(restrictions.region_details([{'prtcptPsblRgnNm': '전국'}])['status'], 'none')
        self.assertEqual(restrictions.industry_details([], 'N')['status'], 'none')
        self.assertEqual(restrictions.industry_details([], 'Y')['status'], 'unknown')
        self.assertEqual(restrictions.industry_details([], '')['status'], 'not_listed')

    def test_explicit_industry_n_needs_no_license_lookup(self):
        with patch.object(restrictions, 'lookup_rows', return_value=[]) as lookup:
            result = restrictions.lookup_restrictions({'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'indstrytyLmtYn': 'N'}, 'test')
        lookup.assert_called_once_with('test', 'B1', '000', 'region')
        self.assertEqual(result['industry_restriction']['status'], 'none')

    def test_lookup_failure_is_not_no_restriction_and_does_not_leak_key(self):
        opener = SimpleNamespace(open=lambda request, timeout: response([], code='30'))
        with patch.object(restrictions.collector, 'build_opener', return_value=opener):
            result = restrictions.lookup_restrictions({'bidNtceNo': 'B1', 'indstrytyLmtYn': 'Y'}, 'private-key')
        self.assertTrue(all(d['status'] == 'unavailable' for d in result.values()))
        self.assertNotIn('private-key', json.dumps(result))

    def test_cache_reuses_success_and_does_not_cache_failure(self):
        item = {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'indstrytyLmtYn': 'Y'}
        success = {'region_restriction': {'lookup_status': 'complete', 'status': 'not_listed'},
                   'industry_restriction': {'lookup_status': 'complete', 'status': 'limited', 'requirements': []}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(search_jobs, 'root_dir', return_value=Path(tmp)), \
                patch.object(restrictions, 'lookup_restrictions', return_value=success) as lookup:
            search_jobs._enrich_restrictions(item, 'test')
            search_jobs._enrich_restrictions(item, 'test')
            self.assertEqual(lookup.call_count, 1)
            # 차수가 달라지면 다른 공고 제한을 재사용하지 않는다.
            search_jobs._enrich_restrictions({**item, 'bidNtceOrd': '001'}, 'test')
            self.assertEqual(lookup.call_count, 2)
        failure = {'region_restriction': {'lookup_status': 'unavailable', 'status': 'unavailable'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(search_jobs, 'root_dir', return_value=Path(tmp)), \
                patch.object(restrictions, 'lookup_restrictions', return_value=failure) as lookup:
            search_jobs._enrich_restrictions(item, 'test')
            search_jobs._enrich_restrictions(item, 'test')
            self.assertEqual(lookup.call_count, 2)

    def test_failed_detail_lookup_does_not_freeze_whole_search_cache(self):
        item = {'bidNtceNo': 'B1', 'bidNtceOrd': '000', 'bidNtceNm': '웹 개발',
                'bidClseDt': '2026-11-15 18:00:00', 'indstrytyLmtYn': 'Y'}
        failure = {'region_restriction': {'status': 'unavailable', 'lookup_status': 'unavailable'},
                   'industry_restriction': {'status': 'unknown', 'lookup_status': 'complete'}}
        with tempfile.TemporaryDirectory() as tmp, patch.object(search_jobs, 'root_dir', return_value=Path(tmp)), \
                patch.object(restrictions, 'lookup_restrictions', return_value=failure) as lookup, \
                patch.object(search_jobs.collector, 'lookup_eorder_attachments', return_value=[]), \
                patch.object(search_jobs.collector, 'search_deadline_candidates',
                             return_value=([item], False, {'complete': True, 'requests': 1})):
            first = search_jobs.search_bids(date(2026, 10, 20), date(2026, 11, 30), ['웹'], 20, 'test')
            second = search_jobs.search_bids(date(2026, 10, 20), date(2026, 11, 30), ['웹'], 20, 'test')
            self.assertNotEqual(first['search_id'], second['search_id'])
            self.assertFalse(second['cached'])
            self.assertEqual(lookup.call_count, 2)


if __name__ == '__main__':
    unittest.main()
