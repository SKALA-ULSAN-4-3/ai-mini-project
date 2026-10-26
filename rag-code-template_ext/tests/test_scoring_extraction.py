"""실제 추출→변환→점수 API 경로의 회귀 검증. LLM 응답만 고정하고 네트워크는 쓰지 않는다."""
import ast
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import time
import tempfile
from knowledge_bridge import ExtractionCache
from threading import Barrier, Lock
from types import SimpleNamespace as NS
from typing import List, Literal, Optional
import unittest

from pydantic import BaseModel, Field
from fastapi import FastAPI
from fastapi.testclient import TestClient
from bid_logic.api import create_bid_router
from bid_logic.common import calendar_date
from bid_logic.scoring import _validate_bands, calculate_scores

ROOT = Path(__file__).resolve().parents[1]


def production_functions(cache_dir):
    # 서버 전체 import는 FAISS/LLM을 초기화하므로 기존 integration_support처럼
    # 변경 대상의 실제 함수와 Pydantic 스키마를 추출해 실행한다.
    names = {'ScoringItem', 'ScoringExtraction', 'Band', 'CategoryScore', 'QuantRule',
             'build_rule', 'scoring_rule_context', 'build_scoring', 'bid_chunks',
             'numbered_context', '_squash', 'verified_source', 'cached'}
    tree = ast.parse((ROOT / 'rag_external-web_pdf_closed_llm.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names
             or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and
                t.id in {'SCORING_KEYWORDS', 'EXTRACT_RULES'} for t in n.targets)]
    ns = dict(BaseModel=BaseModel, Field=Field, List=List, Optional=Optional, Literal=Literal,
              Document=object, re=re, time=time, calendar_date=calendar_date,
              _validate_bands=_validate_bands, elapsed_ms=lambda _: 0,
              join_spaced_letters=lambda s: s,
              source_label=lambda m: f"{m['filename']} p.{m['page']}",
              source_ref=lambda m: dict(m), EXTRACTIONS=ExtractionCache(cache_dir, 'test-scoring-v1'),
              BID_FINGERPRINTS={('R1', '000'): 'fixture-documents'})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'production_scoring', 'exec'), ns)
    bridge = ast.parse((ROOT / 'knowledge_bridge.py').read_text())
    node = next(n for n in bridge.body if isinstance(n, ast.FunctionDef) and n.name == 'to_bid_logic_scoring')
    ns['KIND'] = {'정량': 'quantitative', '정성': 'qualitative', '가격': 'price'}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'knowledge_bridge.py', 'exec'), ns)
    return ns


def document(page, text, bid_no='R1', revision='000'):
    return NS(page_content=text, metadata={'bid_no': bid_no, 'revision': revision,
              'filename': 'rfp.pdf', 'source': 'rfp.pdf', 'page': page})


class ScoringExtractionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ns = production_functions(temp.name)
        # 항목표와 등급표를 멀리 떨어뜨리고, 다른 공고·차수를 섞어 격리를 검증한다.
        docs = [document(11, '평가항목 배점 사업 이해도 10 경영상태 10 합계 20'),
                document(30, '경영상태 신용평가등급 기업신용 회사채 기업어음 AAA 10 BB0 8'),
                document(30, '신용평가등급 OTHER_ONLY AAA 99', bid_no='OTHER'),
                document(30, '신용평가등급 REVISION_ONLY AAA 99', revision='001')]
        self.ns['VECTORSTORE_PDF'] = NS(docstore=NS(_dict=dict(enumerate(docs))))
        self.no_rule = False
        self.invalid_source = False
        self.contexts = []

        def extract(schema, instruction, context):
            self.contexts.append(context)
            if schema is self.ns['ScoringExtraction']:
                return schema(items=[dict(category='기술', section='기술', item='사업 이해도', max_score=10,
                                          criteria='이해도', eval_type='정성', doc_no=1),
                                     dict(category='기술', section='정량', item='경영상태', max_score=10,
                                          criteria='신용평가등급별 점수', eval_type='정량', doc_no=1)])
            return schema(doc_no=99 if self.invalid_source else 1, explicit=not self.no_rule,
                          metric_field='credit_rating', aggregate='none', unit='none',
                          period_from='', period_to='', rule_type='category',
                          categories=[dict(value='AAA', score=10), dict(value='BB0', score=8)])
        self.ns['run_extraction'] = extract

    def table(self):
        extraction = self.ns['build_scoring']('R1', '000')
        return self.ns['to_bid_logic_scoring'](extraction, 'R1', '000')

    def test_separate_grade_page_reaches_actual_score_api(self):
        table = self.table()
        self.assertIn('회사채', self.contexts[1])
        self.assertNotIn('OTHER_ONLY', self.contexts[1])
        self.assertNotIn('REVISION_ONLY', self.contexts[1])
        quantitative = table['items'][1]
        self.assertEqual([s['page'] for s in quantitative['sources']], [11, 30])
        app = FastAPI()
        app.include_router(create_bid_router(profile_dependency=lambda: {'credit_rating': 'BB0'},
            bids_provider=lambda: [], scoring_provider=lambda *a: table,
            checklist_provider=lambda *a: None, search=lambda *a: []))
        with TestClient(app) as client:
            response = client.get('/bids/R1/score?revision=000')
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result['items'][0]['status'], 'manual')
        self.assertEqual(result['items'][1]['expected'], 8)
        self.assertEqual(result['items'][1]['status'], 'calculated')
        self.assertTrue(result['needs_review'])
        self.assertNotIn('total', result)

    def test_no_rule_preserves_extraction_reason_without_internal_field_error(self):
        self.no_rule = True
        result = calculate_scores(self.table(), {'credit_rating': 'AAA'}, 'R1', '000')['items'][1]
        self.assertEqual(result['status'], 'manual')
        self.assertIn('산정표가 명시되지 않음', result['reason'])
        self.assertNotIn('field', result['reason'])

    def test_invalid_rule_source_does_not_produce_score(self):
        self.invalid_source = True
        result = calculate_scores(self.table(), {'credit_rating': 'AAA'}, 'R1', '000')['items'][1]
        self.assertEqual(result['status'], 'manual')
        self.assertIn('출처를 확인하지 못', result['reason'])

    def test_missing_profile_requests_credit_rating(self):
        result = calculate_scores(self.table(), {}, 'R1', '000')
        self.assertEqual(result['items'][1]['status'], 'missing_profile')
        self.assertEqual(result['missing_fields'], ['credit_rating'])

    def test_no_detailed_page_has_clear_reason(self):
        self.ns['VECTORSTORE_PDF'].docstore._dict = {0: document(11, '평가항목 사업 이해도 10 경영상태 10 배점')}
        result = calculate_scores(self.table(), {'credit_rating': 'AAA'}, 'R1', '000')['items'][1]
        self.assertIn('상세 산정표를 문서에서 찾지 못', result['reason'])

    def test_old_scoring_cache_rebuilt_once(self):
        key = ('R1', '000', 'scoring')
        self.ns['BID_FINGERPRINTS'][('R1', '000')] = 'same-documents'
        self.ns['EXTRACTIONS'].get(key, 'same-documents', lambda: {'old': True})
        calls = []
        def build():
            calls.append(True)
            return {'new': True}
        for _ in range(2):
            self.assertEqual(self.ns['cached'](*key, False, build), {'new': True})
        self.assertEqual(len(calls), 1)

    def test_parallel_score_and_table_requests_share_one_extraction(self):
        start = Barrier(2)
        calls = []
        def build():
            calls.append(True)
            time.sleep(0.02)
            return {'same_result': True}
        def request():
            start.wait(timeout=2)
            return self.ns['cached']('R1', '000', 'scoring', False, build)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request) for _ in range(2)]
            results = [f.result(timeout=3) for f in futures]
        self.assertEqual(results[0], results[1])
        self.assertIsNot(results[0], results[1])
        self.assertEqual(len(calls), 1)

    def test_actual_axdx_percentage_table_is_calculated_by_code(self):
        # 실제 AXDX 제안요청서 [2] 정량평가 배점기준: 배점 10점,
        # AAA~BBB0 100%, BBB-~BB- 95%, B+~B- 90%, CCC+ 이하 70%.
        q = self.ns['QuantRule'](doc_no=1, explicit=True, metric_field='credit_rating',
            aggregate='none', unit='none', period_from='', period_to='', rule_type='category',
            category_score_unit='percent', categories=[{'value': r, 'score': s}
                for r, s in [('AAA', 100), ('BB0', 95), ('B0', 90), ('CCC+', 70)]])
        payload, note = self.ns['build_rule'](q, 10)
        self.assertEqual(note, '')
        table = self.table()
        table['items'][1].update(payload)
        for rating, expected in [('AAA', 10), ('BB0', 9.5), ('B0', 9), ('CCC+', 7)]:
            with self.subTest(rating=rating):
                result = calculate_scores(table, {'credit_rating': rating}, 'R1', '000')['items'][1]
                self.assertEqual(result['status'], 'calculated')
                self.assertEqual(result['expected'], expected)

    def test_percentage_out_of_range_and_conflicting_grade_are_rejected(self):
        base = dict(explicit=True, metric_field='credit_rating', aggregate='none', unit='none',
                    period_from='', period_to='', rule_type='category', category_score_unit='percent')
        for categories in ([{'value': 'AAA', 'score': 101}],
                           [{'value': 'B0', 'score': 95}, {'value': 'B0', 'score': 90}]):
            rule, note = self.ns['build_rule'](self.ns['QuantRule'](**base, categories=categories), 10)
            self.assertIsNone(rule)
            self.assertTrue(note)


if __name__ == '__main__':
    unittest.main()
