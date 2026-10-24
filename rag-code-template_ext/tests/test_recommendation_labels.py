from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from bid_logic.label_recommendations import label, ROOT

EVIDENCE = ROOT/'data/evaluation-source-20261023/evidence.json'


@unittest.skipUnless(EVIDENCE.exists(), "로컬 원천 데이터(data/evaluation-source-20261023) 필요")
class RecommendationLabelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dataset = Path(self.tmp.name) / 'dataset'
        self.assets = Path(self.tmp.name) / 'assets'
        self.dataset.mkdir(); self.assets.mkdir()
        source = Path(__file__).resolve().parents[1] / 'evaluation/real'
        for name in ('gold.json', 'profiles.json', 'bids.csv', 'manifest.json', 'measurement-summary.json'):
            shutil.copyfile(source/name, self.dataset/name)
        shutil.copyfile(EVIDENCE, self.assets/'evidence.json')

    def test_common_history_consistent_with_separate_region_and_expiry(self):
        frozen = {n: (self.dataset/n).read_bytes() for n in ('profiles.json','bids.csv','manifest.json')}
        previous = json.loads((self.dataset/'gold.json').read_text())
        with redirect_stdout(io.StringIO()): label(self.dataset, self.assets)
        report = json.loads((self.dataset/'recommendation-review.json').read_text())
        self.assertEqual(len(report['cases']), 60)
        for number in ('R26BK01753530','R26BK01757019'):
            rows = [r for r in report['cases'] if r['bid_no']==number]
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r['included_in_gold'] for r in rows))
        jeju = [r for r in report['cases'] if r['bid_no']=='R26BK01760198']
        self.assertTrue(all(r['topically_related'] for r in jeju))
        self.assertEqual([r['profile_id'] for r in jeju if r['included_in_gold']], ['jeju_campus'])
        gist = [r for r in report['cases'] if r['bid_no']=='R26BK01663676']
        self.assertTrue(all('재생 시각 이전 마감' in r['exclusion_reasons'] for r in gist))
        gold = json.loads((self.dataset/'gold.json').read_text())
        self.assertEqual(gold['scores'], previous['scores'])
        self.assertEqual(gold['checklists'], previous['checklists'])
        self.assertTrue(all(g['review']['status']=='pending' for g in gold['recommendations']))
        self.assertTrue(all(r['sources'] and not r['human_verified'] for r in report['cases']))
        for name, data in frozen.items(): self.assertEqual((self.dataset/name).read_bytes(), data)

    def test_changed_replay_or_profile_requires_new_review(self):
        path = self.dataset/'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['now'] = '2026-11-01T16:00:00+09:00'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, '재생 시각'):
            label(self.dataset, self.assets)
        manifest['now'] = '2026-10-07T16:00:00+09:00'
        path.write_text(json.dumps(manifest))
        path = self.dataset/'profiles.json'
        profiles = json.loads(path.read_text()); profiles[0]['keywords'] = ['의료']
        path.write_text(json.dumps(profiles))
        with self.assertRaisesRegex(ValueError, '프로필 관심'):
            label(self.dataset, self.assets)
