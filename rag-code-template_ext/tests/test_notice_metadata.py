from copy import deepcopy
from pathlib import Path
import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from bid_logic.api import create_bid_router
from bid_logic.checklist import build_checklist
from bid_logic.notice_metadata import FACTS, add_notice_schedule, apply_notice_metadata
from bid_logic.recommendation import load_bids_csv, recommend_bids
from bid_logic.shortlist import recheck_metadata, shortlist_bids

MASAN = 'R26BK01707131'
YEONGJIN = 'R26BK01753530'


def row(no, **values):
    return {'bid_no': no, 'revision': '000', 'title': '용역',
        'published_at': '2026-09-01' if no == MASAN else '2026-10-01',
        'deadline': '2026-09-14T14:00:00+09:00' if no == MASAN else None,
        'budget': '100000000', 'regions': None,
        'industries': None, 'licenses': None, 'company_sizes': None, 'certs': None, **values}


class NoticeMetadataTest(unittest.TestCase):
    def test_masan_region_or_before_deadline_in_both_rankers(self):
        for location, accepted in [('경상남도', True), ('부산광역시', True), ('서울', False), ('울산', False)]:
            with self.subTest(location=location):
                profile = {'region': location}
                body = recommend_bids([row(MASAN)], profile, '2026-09-01', '2026-09-30',
                                      now='2026-09-02T10:00:00+09:00')
                listed = shortlist_bids([row(MASAN)], profile, now='2026-09-02T10:00:00+09:00')
                self.assertEqual(bool(body['bids']), accepted)
                self.assertEqual(bool(listed['bids']), accepted)
                if not accepted:
                    self.assertIn('지역', listed['excluded'][0]['reasons'][0])

    def test_masan_region_unknown_remains_needs_review(self):
        result = recommend_bids([row(MASAN)], {}, '2026-09-01', '2026-09-30', now='2026-09-02T10:00:00+09:00')
        self.assertTrue(result['bids'][0]['needs_review'])
        self.assertIn('프로필 region 미확인', result['bids'][0]['unknown'])

    def test_exact_bid_revision_and_raw_api_aliases(self):
        raw = {'bidNtceNo': MASAN, 'bidNtceOrd': '000'}
        self.assertEqual(apply_notice_metadata(raw)['regions'], ['경남', '부산'])
        for other in (row(MASAN, revision='001'), row('OTHER'), row(YEONGJIN, revision='001')):
            self.assertEqual(apply_notice_metadata(other), other)
        self.assertNotIn('metadata_sources', raw)

    def test_participation_boundary_and_no_false_proposal_expiry(self):
        for when, accepted in [('2026-10-08T17:59:59+09:00', True),
                               ('2026-10-08T18:00:00+09:00', False),
                               ('2026-10-09T10:00:00+09:00', False)]:
            with self.subTest(when=when):
                body = recommend_bids([row(YEONGJIN)], {}, '2026-10-01', '2026-10-31', now=when)
                listed = shortlist_bids([row(YEONGJIN)], {}, now=when)
                for result in (body, listed):
                    self.assertEqual(bool(result['bids']), accepted)
                    if not accepted:
                        self.assertIn('신규 참가신청', result['excluded'][0]['reasons'][0])
                        self.assertNotEqual(result['excluded'][0]['reasons'][0], '입찰이 마감되었습니다.')

    def test_three_deadlines_sources_survive_list_and_recheck_conversion(self):
        result = shortlist_bids([row(YEONGJIN)], {}, now='2026-10-07T16:00:00+09:00')['bids'][0]
        self.assertEqual(result['deadline'], '2026-10-08T18:00:00+09:00')
        self.assertEqual(result['deadline_kind'], 'participation')
        self.assertEqual(len(result['deadlines']), 3)
        for item in result['deadlines']:
            self.assertEqual(item['sources'][0]['page'], 2)
            self.assertEqual(item['sources'][0]['bid_no'], YEONGJIN)
        converted = recheck_metadata(result)
        self.assertEqual(converted['deadlines'], result['deadlines'])

    def test_data_and_schedules_not_mutated_and_enrichment_idempotent(self):
        original = row(YEONGJIN); frozen = deepcopy(original)
        once = apply_notice_metadata(original)
        self.assertEqual(original, frozen)
        self.assertEqual(apply_notice_metadata(once), once)
        once['deadlines'][0]['sources'][0]['page'] = 999
        self.assertEqual(apply_notice_metadata(original)['deadlines'][0]['sources'][0]['page'], 2)
        extracted = {'bid_no': YEONGJIN, 'revision': '000', 'documents': [], 'schedule': []}
        frozen = deepcopy(extracted)
        enhanced = add_notice_schedule(extracted)
        self.assertEqual(add_notice_schedule(enhanced), enhanced)
        self.assertEqual(extracted, frozen)

    def test_checklist_each_deadline_has_own_status(self):
        extracted = {'bid_no': YEONGJIN, 'revision': '000', 'documents': [], 'schedule': []}
        before = build_checklist(extracted, {}, YEONGJIN, '000', now='2026-10-09T10:00:00+09:00')
        statuses = {r['id']: r['status'] for r in before['schedule']}
        self.assertEqual(statuses, {'notice_participation': 'expired',
            'notice_proposal_file': 'upcoming', 'notice_proposal_bound': 'upcoming'})
        boundary = build_checklist(extracted, {}, YEONGJIN, '000', now='2026-11-11T14:00:00+09:00')
        statuses = {r['id']: r['status'] for r in boundary['schedule']}
        self.assertEqual(statuses['notice_proposal_file'], 'expired')
        self.assertEqual(statuses['notice_proposal_bound'], 'upcoming')

    def test_alias_duplicates_replaced_and_ambiguous_proposal_not_given_false_date(self):
        sources = deepcopy(next(f['sources'] for f in FACTS if f['bid_no']==YEONGJIN))
        common = {'bid_no': YEONGJIN, 'revision': '000', 'sources': sources, 'due': '2026-12-01T18:00:00+09:00'}
        extracted = {'bid_no': YEONGJIN, 'revision': '000', 'documents': [], 'schedule': [
            {**common, 'id': 'old', 'event': '제본 제출'},
            {**common, 'id': 'ambiguous', 'event': '제안서 제출'}]}
        result = build_checklist(extracted, {}, YEONGJIN, '000', now='2026-10-07T16:00:00+09:00')
        self.assertNotIn('old', [r['id'] for r in result['schedule']])
        ambiguous = next(r for r in result['schedule'] if r['id']=='ambiguous')
        self.assertIsNone(ambiguous['due'])
        self.assertTrue(ambiguous['needs_review'])

    def test_real_csv_has_region_and_participation_cutoff(self):
        path = Path(__file__).resolve().parents[1] / 'evaluation/real/bids.csv'
        bids = {r['bid_no']: r for r in load_bids_csv(path)}
        self.assertEqual(bids[MASAN]['regions'], ['경남', '부산'])
        self.assertEqual(bids[YEONGJIN]['deadline'], '2026-10-08T18:00:00+09:00')
        self.assertEqual(len(bids[YEONGJIN]['deadlines']), 3)

    def test_real_api_returns_stages_and_independent_checklist_dates(self):
        clock = ['2026-10-07T16:00:00+09:00']
        app = FastAPI()
        app.include_router(create_bid_router(profile_dependency=lambda: {},
            bids_provider=lambda: [row(YEONGJIN)], scoring_provider=lambda *a: None,
            checklist_provider=lambda *a: {'bid_no': YEONGJIN, 'revision': '000', 'documents': [], 'schedule': []},
            search=lambda *a: [], clock=lambda: clock[0]))
        with TestClient(app) as client:
            result = client.get('/bids?from=2026-10-01&to=2026-10-31')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(len(result.json()['bids'][0]['deadlines']), 3)
            clock[0] = '2026-10-09T10:00:00+09:00'
            listed = client.get('/bids?from=2026-10-01&to=2026-10-31').json()
            self.assertFalse(listed['bids'])
            checklist = client.get(f'/bids/{YEONGJIN}/checklist?revision=000')
            self.assertEqual(checklist.status_code, 200)
            self.assertEqual([s['status'] for s in checklist.json()['schedule']], ['expired', 'upcoming', 'upcoming'])
