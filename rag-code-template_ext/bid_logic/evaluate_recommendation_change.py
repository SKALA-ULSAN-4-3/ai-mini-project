"""원문 마감 보정 한 건의 효과를 동일 정답·프로필·임베딩으로 재측정한다."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[1] / 'evaluation/real'
from .recommendation import load_bids_csv, recommend_bids


def evaluate(dataset=DATASET):
    def read(name):
        return json.loads((dataset / name).read_text())
    manifest = read('manifest.json')
    profiles = read('profiles.json')
    gold = {r['profile_id']: {(v['bid_no'], v['revision']) for v in r['relevant']}
            for r in read('gold.json')['recommendations']}
    hits = {r['profile_id']: r['hits'] for r in read('hits.json')}
    after = load_bids_csv(dataset / 'bids.csv')
    before = deepcopy(after)
    for correction in read('metadata-corrections.json'):
        row = next(r for r in before if (r['bid_no'], r['revision']) ==
                   (correction['bid_no'], correction['revision']))
        if correction['field'] != 'deadline' or row['deadline'] != correction['after']:
            raise ValueError('기록된 보정과 현재 CSV가 다릅니다.')
        row['deadline'] = correction['before'] or None
    cases = []
    for profile in profiles:
        pid = profile['id']
        case = {'profile_id': pid, 'relevant_count': len(gold[pid])}
        for label, rows in (('before', before), ('after', after)):
            result = recommend_bids(rows, profile, manifest['from'], manifest['to'],
                                    now=manifest['now'], hits=hits[pid])
            actual = [(r['bid_no'], r['revision']) for r in result['bids']]
            case[label] = {'precision_at_5': len(set(actual) & gold[pid]) / 5,
                           'returned': actual, 'excluded': result['excluded']}
        cases.append(case)
    return {'change': 'source-backed deadline metadata correction only', 'human_verified': False,
            'now': manifest['now'], 'cases': cases,
            'unchanged_input_sha256': {n: hashlib.sha256((dataset/n).read_bytes()).hexdigest()
                for n in ('manifest.json', 'profiles.json', 'gold.json', 'hits.json')}}


if __name__ == '__main__':
    result = evaluate()
    (DATASET / 'recommendation-improvement.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    for row in result['cases']:
        print(row['profile_id'], row['before']['precision_at_5'], '->', row['after']['precision_at_5'])
