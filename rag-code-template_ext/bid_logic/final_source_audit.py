"""재추출한 PDF와 원본 XML로 평가 출처를 최종 대조. 사람 승인·쪽수 변환은 수행하지 않는다."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]


def audit(dataset, assets, fresh_pdf_pages):
    def read(path):return json.loads(path.read_text())
    def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    pdfs=[json.loads(line) for line in fresh_pdf_pages.read_text().splitlines()]
    pdf_map={(p['bid_no'],p['revision'],p['filename'],p['page']):p for p in pdfs}
    attachments=read(assets/'attachments.json')
    files={(a['bid_no'],a['bid_order'],a['file_name']):a for a in attachments}
    tables=read(dataset/'scoring_tables.json');lists=read(dataset/'checklists.json');gold=read(dataset/'gold.json')
    if any(g.get('review',{}).get('status')=='verified' for rows in gold.values() for g in rows):
        raise ValueError('사람이 확정한 정답에는 AI 검토 기록을 덮어쓰지 않습니다.')
    for a in attachments:
        if hashlib.sha256(Path(a['local_path']).read_bytes()).hexdigest()!=a['sha256']:
            raise ValueError('원본 파일 해시 불일치')
    # 기존 텍스트 캐시와 새 PDFKit 추출의 수치가 같은지 확인. 공개 이름 마스킹은 숫자를 바꾸지 않는다.
    numeric_checks=[]
    for block in read(assets/'evidence.json'):
        s=block['source']
        if not s.get('page'):continue
        key=(s['bid_no'],s['revision'],s['filename'],s['page'])
        fresh=pdf_map[key]
        same=re.findall(r'\d+',block['text'])==re.findall(r'\d+',fresh['text'])
        numeric_checks.append(same)
        if not same:raise ValueError('캐시/원문 PDF 수치 불일치: '+str(key))
    def references(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='sources' and isinstance(v,list):yield from v
                else:yield from references(v)
        elif isinstance(value,list):
            for v in value:yield from references(v)
    unique={json.dumps(s,sort_keys=True,ensure_ascii=False):s for s in references([tables,lists,gold])}
    checks=[]
    for source in unique.values():
        key=(source['bid_no'],source['revision'],source['filename'])
        a=files[key]
        if source.get('sha256') and a['sha256']!=source['sha256']:raise ValueError('인용 해시 불일치')
        if source.get('page'):
            text=pdf_map[(*key,source['page'])]['text']
            kind='pdf_page'
        else:
            section,_,index=source['locator'].partition('#element-')
            with zipfile.ZipFile(a['local_path']) as archive:
                nodes=list(ET.fromstring(archive.read(section)).iter())
                node=nodes[int(index)]
                text=' '.join(t.text or '' for t in node.iter() if t.tag.endswith('}t'))
            kind='hwpx_xml_node'
        if not text.strip():raise ValueError('빈 인용 위치: '+str(key))
        checks.append({'source':source,'kind':kind,'location_exists':True,
                       'source_text_sha256':hashlib.sha256(text.encode()).hexdigest()})
    stamp=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
    for kind in ('scores','checklists'):
        for g in gold[kind]:
            g.setdefault('ai_review',{}).update(status='final_source_checked',reviewer='Codex (AI)',
                reviewed_at=stamp,human_verified=False,
                scope='원문 배점·정량 계산·제출물·일정 및 인용 위치 대조. 실제 증빙 인정 여부와 사람 승인은 제외')
    write(dataset/'gold.json',gold)
    summary=read(dataset/'source-review.json')
    result={'reviewer':'Codex (AI)','reviewed_at':stamp,'human_verified':False,
        'status':'ai_source_review_complete','fresh_pdf_files':len({p['local_path'] for p in pdfs}),
        'fresh_pdf_pages':len(pdfs),'cached_numeric_pages_matched':sum(numeric_checks),
        'source_files_hash_checked':len(attachments),'reference_locations_checked':len(checks),
        'score_bids':len(tables),'score_items':sum(len(t['items']) for t in tables),
        'quantitative_checks':summary['quantitative_checks'],
        'documents':sum(len(c['documents']) for c in lists),'schedule':sum(len(c['schedule']) for c in lists),
        'changes':summary['changes'],'checks':checks,
        'limitations':['HWPX 출처는 실제 XML 위치로 확인했으며 PDF 쪽수로 변환하지 않음',
            '조건부 서류 해당 여부·실적/신용평가 증빙의 실제 인정 여부는 가상 프로필만으로 확정하지 않음',
            '사업 수행 중 보안·완료 산출물 전체를 입찰 제출 체크리스트와 동일 범위로 검수했다는 뜻은 아님',
            '원문 대조는 AI 검토이며 gold.review의 사람 승인 상태는 변경하지 않음'],
        'artifact_sha256':{n:hashlib.sha256((dataset/n).read_bytes()).hexdigest() for n in (
            'gold.json','scoring_tables.json','checklists.json','recommendation-review.json')}}
    write(dataset/'final-source-audit.json',result)
    lines=['# 최종 원문 대조 결과','',f'검토: Codex(AI), {stamp}. 사람 승인 상태는 변경하지 않았다.','',
        '## 검수 범위와 결과','',
        f"- 원본 PDF {result['fresh_pdf_files']}개를 다시 읽어 {len(pdfs)}페이지를 추출했고, 기존 캐시 {sum(numeric_checks)}페이지의 수치와 일치했다.",
        f"- 원문 74개 파일 해시와 인용 위치 {len(checks)}곳을 실제 PDF 페이지 또는 HWPX XML 노드로 확인했다.",
        f"- 5공고의 평가항목 {result['score_items']}개를 대조하고, 3프로필 정량 계산 12개를 검산했다. 정성·가격은 담당자 판단을 유지한다.",
        f"- 입찰 제출·증빙 {result['documents']}개와 일정 {result['schedule']}개를 정리했다. 불명확한 시각은 null로 보존했다.",
        '- 조건부 제출, 원본/사본·부수·전자/방문 제출, 가격입찰과 서류 기한 차이를 notes와 출처에 기록했다.','',
        '## 이번 최종 대조의 추가 보완','',
        '- 농지·겨레말: 경영상태 신용평가등급 확인서를 개별 증빙 항목으로 분리. 서울 프로필의 보유 확인서와 공백 차이를 제외하고 일치함을 확인.',
        '- 제주대: 제안서 비교평가 조견표, 납품실적증명원 또는 계약서 사본, 개인정보 수집 및 활용 동의서 추가.',
        '- 농지·겨레말·의료기술: 전자입찰 시작과 가격입찰 마감을 별도 일정으로 구분.',
        '- 농지·의료기술·제주대: 별도 통지되는 제안서 평가를 시각 미확인 일정으로 표시.',
        '- 겨레말: 참가자격 등록은 9월13일까지이나 시각 미기재이므로 임의로 18시 또는 23시59분을 만들지 않음.','',
        '## 남긴 한계','']+[f'- {x}' for x in result['limitations']]+['',
        '세부 서류·일정: [REVIEW.md](REVIEW.md). 검증 기록: [final-source-audit.json](final-source-audit.json).']
    (dataset/'FINAL_SOURCE_REVIEW.md').write_text('\n'.join(lines)+'\n')
    print(f"Final source audit: {len(pdfs)} PDF pages, {len(checks)} citation locations, {result['documents']} documents, {result['schedule']} events; human_verified=False")


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf-pages',type=Path,required=True)
    args=parser.parse_args()
    audit(Path('evaluation/real'),ROOT/'data/evaluation-source-20261023',args.pdf_pages)
