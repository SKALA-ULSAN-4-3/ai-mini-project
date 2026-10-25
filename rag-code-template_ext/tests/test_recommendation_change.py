import unittest
from bid_logic.evaluate_recommendation_change import evaluate

class RecommendationChangeTest(unittest.TestCase):
    def test_expired_notice_excluded_without_changing_gold(self):
        for case in evaluate()['cases']:
            no = 'R26BK01663676'
            self.assertIn(no, [r[0] for r in case['before']['returned']])
            self.assertNotIn(no, [r[0] for r in case['after']['returned']])
            excluded = next(r for r in case['after']['excluded'] if r['bid_no']==no)
            self.assertIn('입찰이 마감되었습니다.', excluded['reasons'])
            self.assertGreaterEqual(case['after']['precision_at_5'], case['before']['precision_at_5'])
