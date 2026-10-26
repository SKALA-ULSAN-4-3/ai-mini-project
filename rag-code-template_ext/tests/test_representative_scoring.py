"""첨부 HWP(합덕제철고 AI 활용 특허 교육 연수)의 배점표로 검산한다.

실제 공고일이 첨부에 없어 2026-10-26을 가상의 검산 기준일로만 사용한다.
실제 회사·입찰의 점수로 해석하지 않는다.
"""
from copy import deepcopy
import tempfile
import unittest

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from bid_logic.api import create_bid_router
from bid_logic.scoring import calculate_scores
from bid_logic.agent_tools import ScoringTools
from tests.test_scoring_extraction import production_functions

REF = {'bid_no': 'REP-HWP', 'revision': '000', 'filename': '제안요청서(과업내용 포함).hwp',
       'page': None, 'locator': '[붙임] 정량평가 및 정성평가 배점표 / [서식14]'}


def functions():
    # 규칙 변환 함수만 쓰므로 추출 캐시는 비어 있는 임시 폴더로 충분하다.
    with tempfile.TemporaryDirectory() as cache_dir:
        return production_functions(cache_dir)


def table():
    ns = functions()
    base = dict(explicit=True, aggregate='none', unit='none', period_from='', period_to='')
    rules = [
        dict(metric_field='track_records', rule_type='bands', aggregate='sum', unit='KRW',
             period_from='2023-10-01', period_to_notice_date=True, min_record_amount=20000000,
             reference_amount=30000000, record_filters=[
                 {'field': 'client_type', 'accepted_values': ['national', 'local', 'public']},
                 *[{'field': f, 'accepted_values': ['true']} for f in
                   ('related_training', 'vat_included', 'evidence_submitted')]],
             bands=[dict(max=40, score=4), dict(min=40, max=70, score=6),
                    dict(min=70, max=100, score=8), dict(min=100, score=10)]),
        dict(metric_field='personnel', rule_type='bands', record_filters=[
                 {'field': f, 'accepted_values': ['true']} for f in ('training_experience', 'insurance_verified')],
             bands=[dict(max=4, score=1), dict(min=4, max=7, score=3),
                    dict(min=7, max=10, score=4), dict(min=10, score=5)]),
        dict(metric_field='credit_rating', rule_type='category', credit_valid_on_notice=True,
             credit_max_age_months=12, required_document='신용평가등급 확인서', missing_document_score=0,
             categories=[{'value': k, 'score': v} for k,v in
                         [('AAA', 5), ('BB0', 4), ('B0', 3), ('CCC+', 1)]])]
    names = [('수행실적', 10, '1건 계약금액이 2천만 원 이상(VAT 포함) / 합산 기준금액 30,000천원'),
             ('전문 인력 보유 현황', 5, '입찰 공고일 현재 재직자로서 연수관련 업무경력자 / 4대 보험'),
             ('경영상태', 5, '최근 1년 이내 발급, 공고일 기준 유효한 신용평가등급 확인서. 미제출시 0점')]
    items = []
    for i,(data,(name,maximum,basis)) in enumerate(zip(rules,names)):
        payload,note=ns['build_rule'](ns['QuantRule'](**(base|data)), maximum)
        assert payload, note
        items.append({'bid_no': 'REP-HWP', 'revision': '000', 'id': str(i), 'item': name,
                      'kind': 'quantitative', 'max': maximum, 'basis': basis, 'sources': [REF], **payload})
    for i,(name,maximum,requirements) in enumerate([
        ('연수기획능력', 20, ['연수계획의 적절성', '연수 프로그램의 구성, 내용의 충실성', '연수의 전문성 및 실현가능성']),
        ('사업 관리 부문', 20, ['인력운용 및 조직 구성의 적정성', '보고 체계의 적정성',
                         '돌발상황 및 안전대책 등의 적정성', '용역수행과정에서의 누출 정보 금지 및 보안대책'])],3):
        items.append({'bid_no': 'REP-HWP', 'revision': '000', 'id': str(i), 'item': name,
            'kind': 'qualitative', 'max': maximum, 'basis': ' / '.join(requirements), 'sources': [REF],
            'requirements': [{'text': r, 'sources': [REF]} for r in requirements]})
    return {'bid_no': 'REP-HWP', 'revision': '000', 'notice_date': '2026-10-26', 'items': items}


def profile():
    return {'credit_rating': 'BB0', 'credit_rating_issued_at': '2026-01-01',
        'credit_rating_valid_until': '2026-10-26', 'owned_docs': ['신용평가등급확인서'],
        'track_records': [{'completed_at': '2025-01-01', 'amount': 21000000, 'amount_unit': 'KRW',
                          'client_type': 'public', 'related_training': True, 'vat_included': True,
                          'evidence_submitted': True}],
        'personnel': [{'employed_from': '2020-01-01', 'training_experience': True,
                       'insurance_verified': True} for _ in range(6)]}


class RepresentativeScoringTest(unittest.TestCase):
    def score(self, p=None, t=None):
        return calculate_scores(t or table(), p if p is not None else profile(), 'REP-HWP', '000')

    def test_three_quantitative_items_and_manual_requirements(self):
        result = self.score()
        self.assertEqual([r['expected'] for r in result['items'][:3]], [8, 3, 4])
        self.assertTrue(all(r['status']=='calculated' for r in result['items'][:3]))
        manual = result['items'][-1]
        self.assertEqual(manual['status'], 'manual')
        self.assertIn('안전대책', manual['reason'])
        self.assertIn('보안대책', manual['reason'])
        self.assertTrue(manual['requirements'][0]['sources'])

    def test_raw_personnel_table_is_parsed_without_model_boundary_guess(self):
        ns=functions()
        text=('입찰 공고일 현재 재직자로서 연수 및 교육 관련 업무경력자. 4대 보험으로 확인\n'
              '￭ 4명 미만\n1점\n￭ 4 ~ 6명\n3점\n￭ 7 ~ 9명\n4점\n￭ 10명 이상\n5점')
        payload,refs=ns['personnel_rule_from_sources']({1:text},5)
        self.assertEqual(refs,[1])
        t=table();t['items'][1].update(payload)
        for count,expected in [(3,1),(4,3),(6,3),(7,4),(9,4),(10,5)]:
            p=profile();p['personnel']=[dict(p['personnel'][0]) for _ in range(count)]
            self.assertEqual(self.score(p,t)['items'][1]['expected'],expected)
        bad,refs=ns['personnel_rule_from_sources']({1:text,2:'4명 미만\n2점'},5)
        self.assertIsNone(bad)

    def test_grouped_credit_labels_and_lower_grades_are_normalized(self):
        ns=functions()
        q=ns['QuantRule'](explicit=True,metric_field='credit_rating',aggregate='none',unit='none',
            period_from='',period_to='',rule_type='category',categories=[
                {'value':'AAA, AA+, AA0, AA-', 'score':5},
                {'value':'BBB-, BB+, BB0, BB-', 'score':4},
                {'value':'CCC+ 이하', 'score':1}],
            required_document='신용정보업자가 발급한 신용평가등급확인서',missing_document_score=0)
        payload,note=ns['build_rule'](q,5)
        self.assertEqual(note,'')
        self.assertEqual(payload['rule']['values']['BB0'],4)
        self.assertEqual(payload['rule']['values']['D'],1)
        self.assertEqual(payload['metric']['required_document'],'신용평가등급확인서')

    def test_performance_bands_and_minimum_per_contract(self):
        for amount,expected in [(19999999,4), (20000000,6), (21000000,8), (30000000,10)]:
            p=profile();p['track_records'][0]['amount']=amount
            self.assertEqual(self.score(p)['items'][0]['expected'], expected)
        p=profile();p['track_records']*=2
        self.assertEqual(self.score(p)['items'][0]['expected'],10)
        for field,value in [('client_type','private'), ('related_training',False),
                            ('completed_at','2023-09-30'), ('completed_at','2026-10-27')]:
            p=profile();p['track_records'][0][field]=value
            self.assertEqual(self.score(p)['items'][0]['expected'],4)

    def test_missing_record_proof_is_not_silently_treated_as_zero(self):
        p=profile();del p['track_records'][0]['client_type']
        r=self.score(p)
        self.assertEqual(r['items'][0]['status'],'missing_profile')
        self.assertIn('track_records[0].client_type',r['missing_fields'])

    def test_staff_boundaries_employment_and_proof(self):
        for count,expected in [(0,1),(3,1),(4,3),(6,3),(7,4),(9,4),(10,5)]:
            p=profile();p['personnel']=[deepcopy(profile()['personnel'][0]) for _ in range(count)]
            self.assertEqual(self.score(p)['items'][1]['expected'],expected)
        for changed in ({'employed_from':'2026-10-27'}, {'employed_to':'2026-10-25'},
                        {'insurance_verified':False}, {'training_experience':False}):
            p=profile();p['personnel']=[p['personnel'][0]|changed]
            self.assertEqual(self.score(p)['items'][1]['expected'],1)
        p=profile();del p['personnel'][0]['insurance_verified']
        self.assertEqual(self.score(p)['items'][1]['status'],'missing_profile')

    def test_credit_validity_and_explicit_missing_certificate(self):
        for field,value in [('credit_rating_valid_until','2026-10-25'),
                            ('credit_rating_issued_at','2026-10-27'), ('credit_rating_issued_at','2025-10-25')]:
            p=profile();p[field]=value
            self.assertEqual(self.score(p)['items'][2]['status'],'manual')
        p=profile();p['owned_docs']=[];p.pop('credit_rating')
        self.assertEqual(self.score(p)['items'][2]['expected'],0)
        p=profile();p.pop('owned_docs')
        self.assertEqual(self.score(p)['items'][2]['status'],'missing_profile')

    def test_missing_notice_date_asks_instead_of_using_today(self):
        t=table();t['notice_date']=None
        r=self.score(t=t)
        self.assertIn('notice_date',r['missing_fields'])
        self.assertTrue(all(i['status']=='missing_profile' for i in r['items'][:3]))

    def test_agent_keeps_guidance_and_calculates_supported_quantitative_items(self):
        tools=ScoringTools(scoring_provider=lambda *a:table(),profile_provider=profile,
                           bid_no='REP-HWP',revision='000')
        self.assertEqual(tools.mark_manual('1','모델이 계산을 포기함')['expected'],3)
        self.assertIn('안전대책',tools.mark_manual('4','위원 판단 필요')['reason'])

    def test_authenticated_api_supplemental_inputs_and_authoritative_date(self):
        def auth(authorization: str | None = Header(None)):
            if authorization!='Bearer fixture':raise HTTPException(401)
            return {}
        app=FastAPI();app.include_router(create_bid_router(profile_dependency=auth,
            bids_provider=lambda:[],scoring_provider=lambda *a:table(),checklist_provider=lambda *a:None,
            search=lambda *a:[]))
        with TestClient(app) as client:
            url='/bids/REP-HWP/score?revision=000'
            self.assertEqual(client.post(url,json=profile()).status_code,401)
            p=profile()|{'notice_date':'2030-01-01'}
            response=client.post(url,json=p,headers={'Authorization':'Bearer fixture'})
            self.assertEqual(response.status_code,200)
            self.assertEqual([r['expected'] for r in response.json()['items'][:3]],[8,3,4])
            self.assertEqual(client.post(url,json={'unsupported':1},
                headers={'Authorization':'Bearer fixture'}).status_code,422)


if __name__=='__main__':unittest.main()
