"""원문 대조로 확인한 평가 정답 보완. 사람 검토 승인을 대신하지 않는다."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]


def review_sources(dataset, assets):
    def read(path): return json.loads(path.read_text())
    def write(path, data): path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    gold=read(dataset/'gold.json'); lists=read(dataset/'checklists.json'); tables=read(dataset/'scoring_tables.json')
    if any(g.get('review',{}).get('status')=='verified' for rows in gold.values() for g in rows):
        raise ValueError('사람이 확정한 정답은 자동 수정하지 않습니다.')
    before=assets/'gold-before-source-review.json'
    if not before.exists():write(before,gold)
    blocks=read(assets/'evidence.json'); attachments=read(assets/'attachments.json')
    sources={}
    for b in blocks:
        s=b['source']
        if s.get('page') and '제안요청서' not in s['filename']:
            sources[(s['bid_no'],s['page'])]=s
    def source(no,page):return deepcopy(sources[(no,page)])
    extra_evidence=[]
    def xml_source(no, phrase):
        a=next(a for a in attachments if a['bid_no']==no and a['file_name'].endswith('.hwpx') and '제안요청서' in a['file_name'])
        with zipfile.ZipFile(a['local_path']) as archive:
            for section in sorted(archive.namelist()):
                if not section.startswith('Contents/section') or not section.endswith('.xml'):continue
                for i,node in enumerate(ET.fromstring(archive.read(section)).iter()):
                    if not node.tag.endswith('}p'):continue
                    text=' '.join(n.text or '' for n in node.iter() if n.tag.endswith('}t'))
                    if phrase not in text:continue
                    ref={'bid_no':no,'revision':a['bid_order'],'filename':a['file_name'],'page':None,
                         'locator':f'{section}#element-{i}','url':a['url'],'sha256':a['sha256']}
                    extra_evidence.append({'source':ref,'text':text})
                    return ref
        raise ValueError('원문 문구를 찾지 못함: '+phrase)
    checks=[]
    for a in attachments:
        actual=hashlib.sha256(Path(a['local_path']).read_bytes()).hexdigest()
        if actual!=a['sha256']:raise ValueError('원문 파일 해시 불일치')
    fixes=[]
    for checklist in lists:
        no,revision=checklist['bid_no'],checklist['revision']
        def add(name,due,refs,notes):
            if any(d['doc']==name for d in checklist['documents']):return
            checklist['documents'].append({'id':f'doc{len(checklist["documents"])+1:02}', 'bid_no':no,
                'revision':revision,'doc':name,'due':due,'sources':refs,'notes':notes})
            fixes.append({'bid_no':no,'change':'document_added','doc':name})
        if no=='R26BK01751013':
            add('공동수급협정서','2026-10-13T18:00:00+09:00',[source(no,6),source(no,3)],
                ['공동수급 시에만 제출. 전자입찰 마감일 전일 18시. 나라장터 전자제출'])
            for d in checklist['documents']:
                if d['doc']=='중·소기업·소상공인확인서 신청 증빙서류':d['notes']=['마감일 전일까지 확인서를 발급받지 못한 업체만 제출']
                elif d['doc']=='특별법인을 확인할 수 있는 서류':d['notes']=['중소기업으로 간주되는 특별법인에 한하여 제출']
        if no=='R26BK01706837':
            add('제안서와 제출서류 일체 원본 출력물','2026-09-16T14:00:00+09:00',[source(no,10)],
                ['제안서 평가회 참석 시 각 1부. 평가회 예정 일시이므로 변경 여부 확인'])
            add('제안서 내용이 수록된 CD/USB 또는 인쇄물',None,[source(no,9)],['우선협상대상자에게 발주기관이 요구할 경우 추가 제출'])
            for name,phrase in (('실적증명원(원본대조필) 사본','실적증명원(원본대조필)'),
                                ('투입인력 자격증 사본','투입인력 자격증 사본')):
                add(name,'2026-09-14T10:00:00+09:00',[xml_source(no,phrase),source(no,4)],['정량평가 제안서의 구비서류'])
            if not any(s['id']=='evaluation_notice' for s in checklist['schedule']):
                checklist['schedule'].append({'id':'evaluation_notice','bid_no':no,'revision':revision,
                    'event':'제안서 평가회 참여 통보','due':None,'sources':[source(no,10)],
                    'notes':['2026-09-14 개별 통보. 시각은 원문에 없어 임의 생성하지 않음']})
            for d in checklist['documents']:
                if d['doc']=='발표 자료(평가 참고자료)':
                    d['notes']=['평가 참고자료. 미제출 시 제안서와 포함 서류로만 평가(공고문 p.9)']
                    if source(no,9) not in d['sources']:d['sources'].append(source(no,9))
        if no=='R26BK01706954':
            for name,phrase,page in (('경영상태 관련 증빙서류','관련 증빙서류 첨부',26),
                                     ('주요사업실적 관련 증빙서류','관련 증빙서류 필히',26)):
                ref=next(b['source'] for b in blocks if b['source']['bid_no']==no and b['source'].get('page')==page and '제안요청서' in b['source']['filename'])
                text=next(b['text'] for b in blocks if b['source']==ref)
                if phrase not in text:raise ValueError('RFP 증빙 요구 근거 없음')
                add(name,'2026-09-11T11:00:00+09:00',[deepcopy(ref),source(no,1)],['제안서에 첨부. 구체 증빙 종류는 발주기관 확인'])
            for d in checklist['documents']:
                if d['doc']=='주민등록등본':d['notes']=['개인사업자인 경우. 법인은 법인등기부등본 제출']
                elif d['doc']=='법인등기부등본':d['notes']=['법인인 경우. 입찰일 기준 3개월 이내 발급분']
                elif d['doc']=='가격제안서':d['notes']=['날인 후 별도 밀봉, 서류 마감 9월11일 11시 방문 제출. 전자 가격입찰 마감 9월14일 11시와 구분']
                elif d['doc']=='제안서':d['notes']=['10부. 9월11일 11시 방문 제출']
                elif d['doc']=='제안서 파일이 저장된 USB':d['notes']=['USB 1개']
        if no=='R26BK01760198':
            for d in checklist['documents']:
                if d['doc']=='기타서류':d['notes']=['해당사항이 있을 경우에만 제출. 제안요청서 참고']
    # 가격 배점은 기술평가표의 합계에서 추측하지 않고 가격평가 비율이 명시된 출처로 교체.
    for table in tables:
        no=table['bid_no']
        if no in ('R26BK01667722','R26BK01751013'):
            price=next(i for i in table['items'] if i['kind']=='price')
            price['sources']=[source(no,1 if no=='R26BK01667722' else 10)]
            fixes.append({'bid_no':no,'change':'price_source_corrected'})
    # 함수 출력이 아닌, 이번에 다시 읽은 원문 표의 3등급/3금액 정답.
    answers={'R26BK01667722':(5,4.75,4.5),'R26BK01706837':(5,4.5,4),'R26BK01760198':(5,4.75,4.5)}
    profiles=read(dataset/'profiles.json');profile_index={p['id']:i for i,p in enumerate(profiles)}
    by_table={t['bid_no']:t for t in tables};by_list={c['bid_no']:c for c in lists}
    stamp=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
    for g in gold['scores']:
        table=by_table[g['bid_no']];items={i['id']:i for i in table['items']}
        for item in g['items']:
            spec=items[item['id']];name=spec['item'];idx=profile_index[g['profile_id']]
            if name=='경영상태' and g['bid_no'] in answers:
                expected=answers[g['bid_no']][idx]
            elif name=='용역사업 수행실적' and g['bid_no']=='R26BK01760198':expected=(5,4,3.5)[idx]
            else:continue
            checks.append({'bid_no':g['bid_no'],'profile_id':g['profile_id'],'item':name,
                           'expected':expected,'matches_previous':item['expected']==expected})
            item['expected']=expected
        for item in g['items']:item['sources']=deepcopy(items[item['id']]['sources'])
    for g in gold['checklists']:
        c=by_list[g['bid_no']];old={d['doc']:d for d in g['documents']}
        # 추가 서류가 가상 프로필의 보유 목록에 없는지 별도로 확인.
        g['documents']=[deepcopy(old[d['doc']]) if d['doc'] in old else {
            'doc':d['doc'],'owned':False,'due':d['due'],'sources':deepcopy(d['sources'])} for d in c['documents']]
        for d in g['documents']:
            original=next(r for r in c['documents'] if r['doc']==d['doc'])
            d.update(due=original['due'],sources=deepcopy(original['sources']))
        g['schedule']=[{k:deepcopy(s[k]) for k in ('event','due','sources')} for s in c['schedule']]
    for kind,rows in gold.items():
        for g in rows:g['ai_review']={'status':'source_checked' if kind!='recommendations' else 'needs_relevance_rubric',
            'reviewer':'Codex (AI)','reviewed_at':stamp,'human_verified':False,
            'note':'원문 내용과 대조함. 사람의 최종 승인은 아님.' if kind!='recommendations' else
                   '주력 키워드와 세 프로필 공통 Axis 실적의 반영 기준이 미확정. 관련성 라벨을 객관적 정답으로 단정하지 않음.'}
    report={'reviewer':'Codex (AI)','reviewed_at':stamp,'human_verified':False,
        'scope':'평가 정답의 원문 대조. HWPX의 PDF 쪽수 대응 작업은 제외.',
        'source_files_hash_checked':len(attachments),'score_cases':15,'quantitative_checks':checks,
        'checklist_cases':15,'changes':fixes,'recommendation_cases':3,
        'recommendation_review':'needs_relevance_rubric',
        'remaining':['주력 키워드와 공통 Axis 실적 중 관련 정답에 반영할 기준 정의 및 사람 승인',
                     '조건부 서류와 증빙의 실제 해당 여부는 가상 프로필만으로 확정하지 않음'],
        'hwpx_page_mapping_changed':False}
    previous_path=dataset/'source-review.json'
    if previous_path.exists():
        changes=read(previous_path).get('changes',[])+fixes
        report['changes']=list({json.dumps(c,sort_keys=True,ensure_ascii=False):c for c in changes}.values())
    write(dataset/'gold.json',gold);write(dataset/'checklists.json',lists);write(dataset/'scoring_tables.json',tables)
    write(dataset/'source-review.json',report);write(dataset/'source-review-evidence.json',extra_evidence)
    lines=['# 평가 정답 원문 대조 결과','',
        '검토자: Codex(AI). 사람의 검토 완료로 표시하지 않았으며 HWPX 쪽수 작업은 수행하지 않았다.','',
        '## 확인 결과','',
        '- 원문 74개 파일의 SHA-256이 보존된 수집 기록과 일치한다.',
        '- 공고 5건 × 프로필 3개의 점수 정답을 대조했다. 직접 계산하는 정량 항목 12개 모두 기존 정답과 일치한다.',
        '- 나머지 정성·가격 항목은 수치를 임의 예측하지 않고 담당자 판단을 유지했다.',
        '- 농지 기술평가표의 100점 원점수와 최종 90점 환산을 구분한다. 총점은 산출하지 않는다.','',
        '## 수정한 항목','']
    for change in report['changes']:
        lines.append(f"- {change['bid_no']}: "+(f"서류 추가 — {change['doc']}" if 'doc' in change else '가격 배점 출처 보정'))
    lines+=['', '법인/개인, 특별법인, 미발급 확인서 신청 증빙, 평가 참고자료의 제출 조건도 원문에 맞춰 notes에 구분했다.', '',
        '## 확정하지 않은 항목','',
        '- 추천 정답 3개는 주력 키워드와 세 프로필에 공통으로 기재된 Axis 대학 실적을 어느 정도 반영할지 기준이 모호하다. 기존 관련성 라벨은 유지하고 needs_relevance_rubric으로 기록했다.',
        '- 기존 P@5는 이 잠정 라벨과의 비교이며, 사람이 확정한 추천 정확도가 아니다.',
        '- 실제 증빙 인정 여부와 조건부 제출 해당 여부는 가상 프로필만으로 확정하지 않는다.',
        '- gold.json의 사람 검토 상태는 pending이며, 별도의 ai_review에 이번 원문 대조 결과를 기록했다.','',
        '세부 서류·일정·배점: [REVIEW.md](REVIEW.md). 기계 판독 기록: [source-review.json](source-review.json).']
    (dataset/'SOURCE_REVIEW.md').write_text('\n'.join(lines)+'\n')
    print('Source review: 12 quantitative checks,',len(fixes),'reference changes;',len(attachments),'source hashes checked')


if __name__=='__main__':review_sources(Path('evaluation/real'),ROOT/'data/evaluation-source-20261023')
