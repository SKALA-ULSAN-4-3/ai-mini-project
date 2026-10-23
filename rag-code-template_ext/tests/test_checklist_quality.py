import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from bid_logic.checklist_quality import reconcile_required_docs


class ChecklistQualityTest(unittest.TestCase):
    def test_actual_checklist_provider_repairs_before_conversion(self):
        root = Path(__file__).resolve().parents[1]
        namespace = {}
        for filename, function in (("knowledge_bridge.py", "to_bid_logic_checklist"),
                                   ("rag_external-web_pdf_closed_llm.py", "get_extracted_checklist")):
            tree = ast.parse((root / filename).read_text())
            nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function]
            exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, "exec"), namespace)
        raw = {"docs": [], "schedule": [], "due_iso": "2026-09-14T11:00+09:00"}
        source = {"bid_no":"A", "revision":"000", "filename":"notice.pdf", "page":1}
        text = "제출서류: 정량적 제안서 제출\n입찰서류 제출 마감 일시: 2026년 9월 11일(금) 11:00"
        namespace.update(VECTORSTORE_PDF=object(), stored_bids=lambda store:{("A", "000")},
            cached=lambda *args:raw, bid_chunks=lambda *args:[SimpleNamespace(page_content=text, metadata=source)],
            source_ref=lambda meta:meta, source_label=lambda meta:"notice.pdf p.1")
        result = namespace["get_extracted_checklist"]("A", "000")
        self.assertEqual(result["documents"][0]["doc"], "정량적 제안서")
        self.assertEqual(result["documents"][0]["due"], "2026-09-11T11:00:00+09:00")
        self.assertTrue(result["needs_review"])
        self.assertEqual(raw["docs"], [])

    def test_missing_proposals_and_correct_date_source(self):
        refs={1:{'page':8},2:{'page':9},3:{'page':10}}
        texts={1:'제출서류: 정량적 제안서 및 정성적 제안서, 발표자료를 제출',
               2:'제안서 평가회 안내',3:'제안서 평가회: 2026. 9. 16.(수) 14:00'}
        raw={'docs':[], 'schedule':[{'event':'제안서 평가회','when':'2026-09-16T14:00:00',
             'due_iso':'2026-09-16T14:00:00','source_refs':[refs[2]]}]}
        result=reconcile_required_docs(raw,texts,refs,{})
        self.assertEqual(len(result['docs']),3)
        self.assertEqual(result['schedule'][0]['source_refs'],[refs[3]])
        self.assertTrue(result['needs_review'])
        self.assertEqual(raw['docs'],[])

    def test_separate_document_and_price_deadline(self):
        texts={1:'입찰서류 제출 마감 일시: 2026년 9월 11일(금) 11:00\n가격입찰 마감: 2026년 9월 14일(월) 11:00'}
        result=reconcile_required_docs({'docs':[{'doc_name':'사업자등록증','due_iso':'2026-09-14T11:00+09:00'},
            {'doc_name':'가격입찰서'}],'schedule':[]},texts,{1:{'page':1}},{})
        self.assertEqual(result['docs'][0]['due_iso'],'2026-09-11T11:00:00+09:00')
        self.assertIsNone(result['docs'][1]['due_iso'])

    def test_ambiguous_deadlines_and_unsupported_event_remain_unknown(self):
        texts={1:'입찰서류 제출 마감: 2026.9.11. 11:00',2:'입찰서류 제출 마감: 2026.9.12. 11:00'}
        result=reconcile_required_docs({'docs':[{'doc_name':'제안서'}], 'schedule':[
            {'event':'평가회','when':'2026.9.16. 14:00','due_iso':'2026-09-16T14:00+09:00'}]},texts,{1:{},2:{}},{})
        self.assertIsNone(result['docs'][0]['due_iso'])
        self.assertIsNone(result['schedule'][0]['due_iso'])
        self.assertTrue(result['needs_review'])
