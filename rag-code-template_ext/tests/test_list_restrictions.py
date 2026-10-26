import unittest

from bid_logic.shortlist import shortlist_bids, recheck_metadata, recheck_after_ingest


def listing(**extra):
    return {'bid_no': 'B1', 'revision': '000', 'title': '웹 개발',
            'deadline': '2026-11-15 18:00:00', 'published_at': '2026-09-01',
            'indstrytyLmtYn': 'Y', **extra}


def region_detail(values, status='limited'):
    return {'status': status, 'lookup_status': 'complete', 'values': values, 'source': 'region_api'}


def industry_detail(*names):
    return {'status': 'limited', 'lookup_status': 'complete', 'source': 'license_api',
            'requirements': [{'name': name, 'code': code, 'group_no': '1', 'sequence': str(i),
                              'alternatives': [], 'specialties': ''} for i, (name, code) in enumerate(names, 1)]}


class ListingRestrictionTests(unittest.TestCase):
    def result(self, row, profile=None):
        return shortlist_bids([row], profile or {'region': '강원', 'industry': '학술·연구용역', 'licenses': ['1169']},
                              start='2026-11-01', end='2026-11-30', now='2026-10-26T10:00:00+09:00')

    def test_actual_region_and_target_industry_replace_generic_unknowns(self):
        result = self.result(listing(region_restriction=region_detail(['강원특별자치도']),
                                     industry_restriction=industry_detail(('학술.연구용역', '1169'))))
        bid = result['bids'][0]
        self.assertEqual(bid['region_restriction']['summary'], '지역제한: 강원특별자치도')
        self.assertIn('학술.연구용역 (1169)', bid['industry_restriction']['summary'])
        self.assertEqual(bid['industry_restriction']['profile_match'], 'matched')
        self.assertFalse(any('지역' in u or '업종' in u for u in bid['unknown']))

    def test_region_mismatch_excludes_candidate(self):
        result = self.result(listing(region_restriction=region_detail(['강원특별자치도'])), {'region': '울산'})
        self.assertFalse(result['bids'])
        self.assertIn('지역 제한 조건 불일치', result['excluded'][0]['reasons'])

    def test_district_is_not_widened_to_whole_province(self):
        row = listing(region_restriction=region_detail(['강원특별자치도 평창군']))
        result = self.result(row)
        self.assertEqual(result['bids'][0]['region_restriction']['profile_match'], 'needs_detail')
        self.assertIn('시군구', ' '.join(result['bids'][0]['unknown']))
        self.assertFalse(self.result(row, {'region': '울산'})['bids'])

    def test_no_registration_explicit_none_and_failed_lookup_have_distinct_labels(self):
        no_rows = self.result(listing(region_restriction=region_detail([], 'not_listed'),
                                      industry_restriction={'status': 'none'}))['bids'][0]
        self.assertIn('등록 내역 없음', no_rows['region_restriction']['summary'])
        self.assertEqual(no_rows['industry_restriction']['summary'], '업종제한: 없음')
        self.assertFalse(any('업종' in u or '지역' in u for u in no_rows['unknown']))
        failed = self.result(listing(region_restriction={'status': 'unavailable'},
                                     industry_restriction={'status': 'unavailable'}))['bids'][0]
        self.assertIn('조회 실패', failed['region_restriction']['summary'])
        self.assertIn('조회 실패', failed['industry_restriction']['summary'])

    def test_industry_n_is_not_unknown_without_detail_api(self):
        bid = self.result(listing(indstrytyLmtYn='N', regions=[]))['bids'][0]
        self.assertEqual(bid['industry_restriction']['status'], 'none')
        self.assertFalse(any('업종' in u or '지역' in u for u in bid['unknown']))

    def test_multiple_required_licenses_are_displayed_without_false_or_qualification(self):
        row = listing(industry_restriction=industry_detail(
            ('소프트웨어사업자(컴퓨터관련서비스사업)', '1468'), ('정보통신공사업', '0036')))
        bid = self.result(row, {'industry': '1468'})['bids'][0]
        detail = bid['industry_restriction']
        self.assertIn('1468', detail['summary'])
        self.assertIn('0036', detail['summary'])
        self.assertEqual(detail['profile_match'], 'manual_review')
        self.assertNotIn('업종 제한 있음, 대상 업종 미확인', bid['unknown'])

    def test_single_license_alternative_matches_exact_code(self):
        detail = industry_detail(('정보통신공사업', '0036'))
        detail['requirements'][0]['alternatives'] = [{'name': '소프트웨어사업자', 'code': '1468'}]
        bid = self.result(listing(industry_restriction=detail), {'licenses': '1468'})['bids'][0]
        self.assertEqual(bid['industry_restriction']['profile_match'], 'matched')

    def test_recheck_preserves_details_and_region_restriction(self):
        row = listing(region_restriction=region_detail(['강원특별자치도']),
                      industry_restriction=industry_detail(('학술.연구용역', '1169')))
        metadata = recheck_metadata(row)
        self.assertIn('region_restriction', metadata)
        result = recheck_after_ingest([row], [metadata], {'region': '울산'}, '2026-11-01', '2026-11-30',
                                      now='2026-10-26T10:00:00+09:00', hits=[])
        self.assertEqual(result['bids'][0]['recheck']['status'], 'disqualified')
        self.assertIn('지역 제한 조건 불일치', result['bids'][0]['recheck']['reasons'])


if __name__ == '__main__':
    unittest.main()
