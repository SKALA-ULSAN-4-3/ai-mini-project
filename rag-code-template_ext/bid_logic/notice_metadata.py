"""원문으로 확인한 공고·차수의 지역과 단계별 기한을 공급 경계에서 보완한다."""
from copy import deepcopy
import json
from pathlib import Path
import re

from .common import check_scope, region, seoul_time

FACTS = json.loads(Path(__file__).with_name('notice_metadata.json').read_text(encoding='utf-8'))
for fact in FACTS:
    check_scope(fact, fact['bid_no'], fact['revision'])
    for value in fact.get('regions', []):
        region(value)
    for event in fact.get('deadlines', []):
        seoul_time(event['due'])


def notice_fact(row):
    # 최신 차수 또는 다른 공고에 과거 원문의 조건을 적용하지 않는다.
    key = (row.get('bid_no') or row.get('bidNtceNo'),
           row.get('revision') or row.get('bid_order') or row.get('bidNtceOrd'))
    return next((fact for fact in FACTS if key == (fact['bid_no'], fact['revision'])), None)


def apply_notice_metadata(row):
    fact = notice_fact(row)
    if fact is None:
        return row
    result = dict(row)
    result['metadata_sources'] = deepcopy(fact['sources'])
    result['metadata_notes'] = list(fact['notes'])
    if 'regions' in fact:
        result['regions'] = [region(value) for value in fact['regions']]
    if fact.get('deadlines'):
        result['deadlines'] = [{**{k: v for k, v in event.items() if k != 'aliases'},
                                'sources': deepcopy(fact['sources'])} for event in fact['deadlines']]
        participation = next(e for e in fact['deadlines'] if e['id'] == 'participation')
        result.update(deadline=participation['due'], deadline_kind='participation',
                      deadline_event=participation['event'])
    return result


def expired_deadline_reason(row):
    if row.get('deadline_kind') == 'participation':
        return '신규 참가신청 기한이 지났습니다. 이미 신청한 업체의 후속 제출 기한은 별도로 확인해야 합니다.'
    return '입찰이 마감되었습니다.'


def add_notice_schedule(extracted):
    fact = notice_fact(extracted)
    if fact is None or not fact.get('deadlines'):
        return extracted
    result = deepcopy(extracted)
    normalize = lambda text: re.sub(r'\s+', '', text)
    aliases = {normalize(alias) for event in fact['deadlines'] for alias in event['aliases']}
    stable_ids = {'notice_' + e['id'] for e in fact['deadlines']}
    schedules = []
    for item in result.get('schedule', []):
        name = normalize(item.get('event', ''))
        if item['id'] in stable_ids or name in aliases:
            continue
        # 일반적인 '제안서 제출'은 파일인지 제본인지 모호하다. 임의로 하나의 마감으로 통합하지 않는다.
        if name in {'제안서제출', '제안서제출마감'}:
            item.update(due=None, needs_review=True)
            note = '파일 제출과 제본 제출 기한이 다릅니다. 별도 일정 항목을 확인하세요.'
            item['notes'] = list(dict.fromkeys([*item.get('notes', []), note]))
        schedules.append(item)
    for event in fact['deadlines']:
        schedules.append({'id': 'notice_' + event['id'], 'event': event['event'],
            'bid_no': fact['bid_no'], 'revision': fact['revision'], 'due': event['due'],
            'sources': deepcopy(fact['sources']), 'notes': list(fact['notes']), 'needs_review': True})
    result['schedule'] = schedules
    return result
