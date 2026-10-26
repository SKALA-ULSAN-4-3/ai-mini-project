"""원문 사업 범위와 프로필을 대조한 고정 60개 판정. 추천 순위에서 정답을 생성하지 않는다."""
from copy import deepcopy
import csv
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
# 원문을 읽고 정한 업무 분류다. '시스템/개발' 또는 발주기관 이름만으로 분류하지 않는다.
# campus: 학사·학생·교육 서비스, business: 업무처리/데이터 연계, web: 홈페이지/CMS/포털.
SPECS={
 'R26BK01667722':('business','농지·국유농지 데이터 연계와 행정정보 기능개선'),
 'R26BK01706837':('business','사전 DB 분석·변환·이관과 검색 기반 구축. 웹/CMS 전문 과업으로 단정하지 않음'),
 'R26BK01751013':('business','의료기술 재평가 업무 흐름·통계·DB 검색 기능개선'),
 'R26BK01661818':('campus','대학 온라인 학습관리시스템(LMS) 고도화'),
 'R26BK01706954':('other','도서관 AI 학술정보 탐색. 학사·학생관리나 홈페이지/CMS와는 핵심 과업이 다름'),
 'R26BK01707131':('campus','학사제도 유연화와 전문기술석사과정 행정 시스템 개발'),
 'R26BK01753451':('business','녹색자금 집행검증 업무와 통합관리 기능개발'),
 'R26BK01662752':('business','ERPMES 업무처리와 제조 DX 설문관리 시스템'),
 'R26BK01707212':('other','디지털 트윈 모델 및 실가상 연동. 학사·업무처리·웹/CMS와 핵심 기술 목적이 다름'),
 'R26BK01659989':('campus','학부 학사·중도탈락 예측·졸업요건 자가진단의 웹서비스 연계'),
 'R26BK01657129':('other','IR시스템이라는 공고명만으로 학사·학생관리와의 직접 연결을 확정하기 부족함'),
 'R26BK01663676':('business','통합정보시스템과 연구비 이지바로 모듈 전환. 대학 발주만으로 학사로 분류하지 않음'),
 'R26BK01664258':('other','소재 R&D 멀티 에이전트 연구지원 기능'),
 'R26BK01707886':('campus_web','대학 학습관리(LMS) 및 콘텐츠관리(CMS) 구축'),
 'R26BK01702784':('web','홈페이지 콘텐츠관리시스템 고도화. 대학 발주만으로 학사 과업으로 분류하지 않음'),
 'R26BK01702853':('campus','대학교 학사정보시스템 고도화'),
 'R26BK01753530':('campus','학생역량·디지털 포트폴리오 통합관리'),
 'R26BK01754897':('business','방폐물 인수관리 고도화와 시스템 연계체계 구축'),
 'R26BK01757019':('campus','nDRIMS의 이공계 연구생활장려금 학생지원 업무 전산화'),
 'R26BK01760198':('campus','Axis 기반 대학 학사행정 통합정보시스템 기능개선'),
}
# 고정 재생 시각(2026-10-07 16:00 KST)에 마감 전인 공고. 미래 검색을 수행하지 않는다.
OPEN_AT_REPLAY={'R26BK01751013','R26BK01753451','R26BK01753530',
                'R26BK01754897','R26BK01757019','R26BK01760198'}


def label(dataset,assets):
    def read(path):return json.loads(path.read_text())
    def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    gold=read(dataset/'gold.json');profiles=read(dataset/'profiles.json')
    if any(g.get('review',{}).get('status')=='verified' for g in gold['recommendations']):
        raise ValueError('사람이 확정한 추천 정답은 덮어쓰지 않습니다.')
    before=assets/'recommendations-before-rubric-v1.json'
    if not before.exists():
        write(before,{'gold':gold['recommendations'],'measurements':read(dataset/'measurement-summary.json')})
    with (dataset/'bids.csv').open() as stream:
        bids=list(csv.DictReader(stream))
    if len(bids)!=20 or len(profiles)!=3 or {b['bid_no'] for b in bids}!=set(SPECS) or {p['id'] for p in profiles}!={'seoul_web','ulsan_data','jeju_campus'}:
        raise ValueError('검토한 고정 20건과 3프로필만 사용할 수 있습니다.')
    manifest=read(dataset/'manifest.json')
    if manifest['now']!='2026-10-07T16:00:00+09:00':
        raise ValueError('재생 시각이 변경되면 원문 마감 판정을 다시 검토해야 합니다.')
    expected_keywords={'seoul_web':['홈페이지','웹 서비스','콘텐츠관리','포털'],
        'ulsan_data':['정보시스템','데이터 연계','기능 개발','업무 시스템'],
        'jeju_campus':['대학','학사','학습관리','학생','Axis 프레임워크']}
    for p in profiles:
        if p['keywords']!=expected_keywords[p['id']] or [r.get('summary') for r in p['track_records']]!=['Axis 프레임워크 기반 대학 학사정보시스템 구축']:
            raise ValueError('프로필 관심 분야/실적이 바뀌면 관련성 정답을 다시 검토해야 합니다.')
    blocks=read(assets/'evidence.json')
    stamp=datetime.now(ZoneInfo('Asia/Seoul')).isoformat()
    rubric={'id':'keyword-or-transferable-track-record-v1','defined_before_rescoring':True,
        'author':'Codex (AI)','human_verified':False,
        'positive':'관심 분야 또는 기존 실적의 업무 범위와 핵심 과업이 직접 연결됨. 둘 중 하나면 관련 있음.',
        'keyword_scope':{'seoul_web':['홈페이지','CMS','포털'],
            'ulsan_data':['업무처리 시스템','데이터 변환·연계','업무 기능개선'],
            'jeju_campus':['학사','학생지원','학습관리']},
        'track_record_scope':'세 프로필 공통 대학 학사정보 실적은 학사·학생지원·학습관리 업무에 전이 가능하다고 판정. 신규 공고에 Axis 명시가 필수는 아님.',
        'negative':'시스템/개발 같은 일반 단어, 동일 발주기관·대학이라는 이유만으로 관련 판정하지 않음. 직접 연결 근거가 부족하면 평가 정답에 포함하지 않음.',
        'separate_eligibility':'사업 관련성과 마감·예산·지역을 분리. 주제 관련이며 재생 시점에 명백한 제외 사유가 없는 공고만 relevant에 기록.',
        'unknown_eligibility':'업종·면허 등 미확인 자격은 통과나 탈락으로 확정하지 않음. needs_review 유지.',
        'rubric_limit':'도메인 전이 가능성은 AI 평가자의 명시적 판단이며, 사람 정답이나 서비스 전체의 객관적 정확도를 뜻하지 않음.'}
    cases=[]
    for bid in bids:
        no=bid['bid_no'];domain,scope=SPECS[no]
        candidates=[b for b in blocks if b['source']['bid_no']==no and b['source'].get('page') and
                    '제안요청서' not in b['source']['filename']]
        title_ref=next((b for b in candidates if any(term in b['text'] for term in (
            '학습관리','콘텐츠관리','포트폴리오','nDRIMS','학사정보','학사제도'))),candidates[0])
        for profile in profiles:
            pid=profile['id']
            if domain in ('campus','campus_web'):
                related=True;basis='track_record';reason='공통 대학 학사정보 실적과 학사·학생·학습 업무가 직접 연결됨'
                if pid=='jeju_campus':basis='keywords_and_track_record'
                elif domain=='campus_web' and pid=='seoul_web':basis='keywords_and_track_record'
            elif domain=='business' and pid=='ulsan_data':
                related=True;basis='keywords';reason='관심 분야인 업무처리·데이터 연계·업무 기능개선에 해당'
            elif domain=='web' and pid=='seoul_web':
                related=True;basis='keywords';reason='관심 분야인 홈페이지·CMS에 직접 해당'
            else:
                related=False;basis='no_direct_evidence';reason='관심 분야/학사 실적과 직접 연결되는 핵심 과업 근거가 부족함'
            excludes=[]
            if no not in OPEN_AT_REPLAY:excludes.append('재생 시각 이전 마감')
            if no=='R26BK01760198' and pid!='jeju_campus':excludes.append('제주 지역 제한 불일치')
            if not profile['budget_min']<=int(bid['budget'])<=profile['budget_max']:excludes.append('희망 금액 범위 밖')
            refs=[deepcopy(title_ref['source'])]
            timing_note='고정 목록 마감과 원문 일정 대조. 날짜 기준은 2026-10-07 16:00 KST.'
            if no=='R26BK01663676':
                page=next(b for b in candidates if b['source']['page']==1)
                refs.append(deepcopy(page['source']))
                timing_note='공고문 p.1 제안서 제출 마감 2026-08-14 14:00. 원문상 마감 경과. CSV 보정 여부는 metadata-corrections.json 참조.'
            elif no=='R26BK01753530':
                page=next(b for b in candidates if b['source']['page']==2)
                refs.append(deepcopy(page['source']))
                timing_note='공고문 p.2 참가신청 10월8일 18시, 파일 제안서 11월11일 14시, 제본 11월13일 13시30분. 모두 재생 시각 이후. CSV 단일 마감은 미확인 유지.'
            cases.append({'bid_no':no,'revision':bid['revision'],'title':bid['title'],'profile_id':pid,
                'core_scope':scope,'topically_related':related,'basis':basis,'reason':reason,
                'exclusion_reasons':excludes,'included_in_gold':related and not excludes,
                'eligibility_status':'excluded' if excludes else 'no_known_exclusion_with_unknowns',
                'timing_note':timing_note,'sources':refs,'human_verified':False})
    for g in gold['recommendations']:
        relevant=[c for c in cases if c['profile_id']==g['profile_id'] and c['included_in_gold']]
        g['relevant']=[{'bid_no':c['bid_no'],'revision':c['revision']} for c in relevant]
        g['rubric_id']=rubric['id']
        g['rationale']='관심 분야 또는 업무가 직접 연결되는 기존 실적 기준으로 고정 20건을 전수 대조. 명백한 마감·금액·지역 불일치는 별도 제외. 세부 근거는 recommendation-review.json의 60개 판정 참조.'
        g['ai_review']={'status':'rubric_applied','reviewer':'Codex (AI)','reviewed_at':stamp,
                        'human_verified':False,'rubric_id':rubric['id']}
    write(dataset/'gold.json',gold)
    result={'rubric':rubric,'reviewed_at':stamp,'human_verified':False,'cases':cases,
        'input_change':'정답 라벨만 갱신. 추천 코드, profiles, bids.csv, hits, 저장 공고명 순위, 재생 시각은 변경하지 않음.',
        'input_findings':['R26BK01663676 마감 누락 보정 여부와 영향은 metadata-corrections.json 및 recommendation-improvement.json 참조.'],
        'previous_relevant':read(before)['gold']}
    write(dataset/'recommendation-review.json',result)
    lines=['# 추천 정답 재검토 — 관심 분야 또는 기존 실적','',
        '검토자: Codex(AI). 사람 검토 완료를 뜻하지 않는다. 고정 공고 20건 × 프로필 3개, 총 60개를 같은 기준으로 판정했다.','',
        '## 판정 기준','',rubric['positive'],'',rubric['track_record_scope'],'',rubric['negative'],'',
        '마감·금액·지역 제외 사유는 주제 관련성과 별도로 기록했다. 미확인 업종·면허는 임의로 탈락시키지 않았다.',
        '추천 결과는 기존 작업에서 확인했으므로 블라인드 평가는 아니다. 순위·유사도 수치에서 정답을 생성하지 않고 원문 사업 범위와 프로필을 대조했다.','',
        '## 20건 × 3프로필 판정','',
        '표의 관련은 최종 정답 포함, 마감/지역은 주제와 별개인 제외 사유, 비관련은 직접 연결 근거 부족을 뜻한다.','',
        '| 공고 | 서울 웹 | 울산 데이터 | 제주 대학 | 핵심 과업 |','| --- | --- | --- | --- | --- |']
    for bid in bids:
        row=[c for c in cases if c['bid_no']==bid['bid_no']]
        labels=['마감 제외' if '재생 시각 이전 마감' in c['exclusion_reasons'] else
                '지역 제외' if c['exclusion_reasons'] else '관련' if c['included_in_gold'] else '비관련' for c in row]
        lines.append('| '+bid['bid_no']+' | '+' | '.join(labels)+' | '+SPECS[bid['bid_no']][1]+' |')
    lines+=['','## 입력 한계','',result['input_findings'][0], '',
        '이번에는 정답만 재검토했다. 추천 알고리즘·입력·실제 임베딩 캐시는 그대로이며, 점수 변화는 정답 기준 변경에 따른 것이다.',
        '판정별 출처와 이유: [recommendation-review.json](recommendation-review.json). 재측정 결과: [REPORT.md](REPORT.md).']
    (dataset/'RECOMMENDATION_REVIEW.md').write_text('\n'.join(lines)+'\n')
    print('Applied rubric to',len(cases),'cases; relevant:',{g['profile_id']:len(g['relevant']) for g in gold['recommendations']})


if __name__=='__main__':label(Path('evaluation/real'),ROOT/'data/evaluation-source-20261023')
