"""이전 실제 모델 추출 결과에 수정한 원문 검사를 재생. 새 모델 호출은 하지 않는다."""
import json
from pathlib import Path
from .prepare_real import ROOT, write_json
from .checklist_quality import reconcile_required_docs


def verify(dataset, assets):
    blocks=json.loads((assets/'evidence.json').read_text())
    checks=[];outputs=[]
    for path in sorted((assets/'model-extractions').glob('*.json')):
        raw=json.loads(path.read_text());no=path.stem
        context=[b for b in blocks if b['id'] in raw['context_ids']]
        texts={b['id']:b['text'] for b in context};refs={b['id']:b['source'] for b in context}
        extracted={'docs':[{'doc_name':d['doc'],'note':'; '.join(d.get('notes',[])),
            'due_iso':None,'source_refs':[refs[d['doc_no']]] if d['doc_no'] in refs else []} for d in raw['payload']['documents']],
            'schedule':[{'event':e['event'],'when':e.get('due') or '', 'due_iso':e.get('due'),
            'source_refs':[refs[e['doc_no']]] if e['doc_no'] in refs else []} for e in raw['payload']['schedule']]}
        repaired=reconcile_required_docs(extracted,texts,refs,{})
        outputs.append({'bid_no':no,**repaired})
        names=''.join(d['doc_name'].replace(' ','') for d in repaired['docs'])
        if no=='R26BK01706837':
            checks.append({'case':'dictionary_quantitative_proposal','passed':'정량적제안서' in names})
            events=[e for e in repaired['schedule'] if '평가회' in e['event']]
            checks.append({'case':'dictionary_date_citation','passed':bool(events) and all(
                (e.get('source_verified') and any(s.get('page')==10 for s in e['source_refs'])) or
                (e.get('due_iso') is None and e.get('needs_review')) for e in events)})
        if no=='R26BK01751013':
            for name in ('정성적제안서','발표자료'):
                checks.append({'case':'medical_'+name,'passed':name in names})
        if no=='R26BK01706954':
            checks.append({'case':'ewha_document_deadline','passed':all(d.get('due_iso')=='2026-09-11T11:00:00+09:00'
                for d in repaired['docs'] if not any(w in d['doc_name'] for w in ('가격입찰서','전자입찰서','공동수급','협정서')))})
    report={'scope':'replay actual cached extraction and source text; not live RAG endpoint',
        'human_verified':False,'passed':sum(c['passed'] for c in checks),'total':len(checks),'checks':checks,
        'limitations':['보완 서류의 조건·수량·개별 기한은 검토 필요','일시 인용 불일치는 보정하거나 미확인 표시; 사람 확인 아님']}
    write_json(dataset/'checklist-repair-checks.json',report)
    write_json(assets/'repaired-checklists.json',outputs)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if report['passed']!=report['total']:raise SystemExit(1)


if __name__=='__main__':verify(Path('evaluation/real'),ROOT/'data/evaluation-source-20261023')
