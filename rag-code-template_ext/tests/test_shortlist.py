"""② 목록 기반 추리기와 ③' 재확인 검증. 외부 패키지·네트워크 불필요."""

import copy
import unittest

from bid_logic import lexical_similarity, recheck_after_ingest, shortlist_bids
from bid_logic.common import RequestError

NOW = "2026-10-23T10:00:00+09:00"


def row(bid_no, title, **extra):
    base = {"bidNtceNo": bid_no, "bidNtceOrd": "000", "bidNtceNm": title,
            "bidClseDt": "2026-11-01 18:00", "asignBdgtAmt": "120,000,000"}
    return {**base, **extra}


class ShortlistTest(unittest.TestCase):
    def setUp(self):
        self.profile = {"region": "서울", "keywords": ["웹 구축", "홈페이지"],
                        "budget_min": 100000000, "budget_max": 500000000}
        self.rows = [row("A", "공공기관 홈페이지 구축"), row("B", "AI 챗봇 서비스 구축")]

    def shortlist(self, rows=None, **kwargs):
        kwargs.setdefault("now", NOW)
        return shortlist_bids(self.rows if rows is None else rows, self.profile, **kwargs)

    # ---------------- 제외 규칙 3가지 ----------------

    def test_expired_deadline_excluded(self):
        result = self.shortlist([row("C", "마감 지난 공고", bidClseDt="2026-10-01 18:00")])
        self.assertFalse(result["bids"])
        self.assertEqual(result["excluded"][0]["reasons"], ["입찰이 마감되었습니다."])

    def test_deadline_equal_now_is_expired(self):
        result = self.shortlist([row("C", "정각 마감", bidClseDt="2026-10-23 10:00")])
        self.assertFalse(result["bids"])

    def test_budget_out_of_range_excluded(self):
        over = self.shortlist([row("D", "예산 초과", asignBdgtAmt="9,000,000,000")])
        under = self.shortlist([row("E", "예산 미만", asignBdgtAmt="1,000,000")])
        self.assertEqual(over["excluded"][0]["reasons"], ["희망 최대 금액 초과"])
        self.assertEqual(under["excluded"][0]["reasons"], ["희망 최소 금액 미만"])

    def test_budget_boundaries_included(self):
        for amount in ("100000000", "500000000"):
            with self.subTest(amount=amount):
                self.assertEqual(len(self.shortlist([row("F", "경계", asignBdgtAmt=amount)])["bids"]), 1)

    def test_region_mismatch_excluded(self):
        result = self.shortlist([row("G", "부산 공고", jntcontrctDutyRgnNm1="부산광역시")])
        self.assertEqual(result["excluded"][0]["reasons"], ["지역 제한 조건 불일치"])

    def test_region_match_kept(self):
        result = self.shortlist([row("H", "서울 공고", jntcontrctDutyRgnNm1="서울특별시")])
        self.assertEqual(len(result["bids"]), 1)

    # ---------------- 업종 제한은 제외하지 않는다 ----------------

    def test_industry_limit_is_unknown_not_excluded(self):
        result = self.shortlist([row("I", "업종 제한 공고", indstrytyLmtYn="Y")])
        self.assertEqual(len(result["bids"]), 1, "업종 제한 Y는 제외하면 안 된다")
        self.assertIn("업종 제한 있음, 대상 업종 미확인", result["bids"][0]["unknown"])
        self.assertFalse(result["excluded"])

    def test_region_basis_only_is_unknown_not_excluded(self):
        # 제한이 있다는 신호뿐이고 어느 지역인지는 목록에 없다.
        result = self.shortlist([row("J", "기준만", rgnLmtBidLocplcJdgmBssNm="법인등기부상 본점소재지")])
        self.assertEqual(len(result["bids"]), 1)
        self.assertIn("지역 제한 대상 지역 미확인", result["bids"][0]["unknown"])

    def test_unknown_profile_region_does_not_exclude(self):
        del self.profile["region"]
        result = self.shortlist([row("K", "부산 공고", jntcontrctDutyRgnNm1="부산광역시")])
        self.assertEqual(len(result["bids"]), 1)
        self.assertIn("프로필 region 미확인", result["bids"][0]["unknown"])

    # ---------------- 미확인 처리 ----------------

    def test_missing_deadline_is_unknown(self):
        for value in ("", "2026-11-01"):  # 날짜만 있는 마감은 시각을 만들지 않는다
            with self.subTest(value=value):
                result = self.shortlist([row("L", "마감 미상", bidClseDt=value)])
                self.assertEqual(len(result["bids"]), 1)
                self.assertIn("입찰마감 일시 미확인", result["bids"][0]["unknown"])

    def test_missing_budget_is_unknown(self):
        result = self.shortlist([{"bidNtceNo": "M", "bidNtceOrd": "000", "bidNtceNm": "예산 미상",
                                  "bidClseDt": "2026-11-01 18:00"}])
        self.assertEqual(len(result["bids"]), 1)
        self.assertIn("금액 비교 정보 미확인", result["bids"][0]["unknown"])

    def test_negative_budget_rejected(self):
        with self.assertRaises(ValueError):
            self.shortlist([row("N", "음수", asignBdgtAmt="-5")])

    # ---------------- 입력 계약 ----------------

    def test_accepts_normalized_and_raw_names(self):
        normalized = {"bid_no": "O", "revision": "001", "title": "정규화 이름",
                      "deadline": "2026-11-01T18:00:00+09:00", "budget": "120000000"}
        result = self.shortlist([normalized])
        self.assertEqual((result["bids"][0]["bid_no"], result["bids"][0]["revision"]), ("O", "001"))

    def test_revision_leading_zero_preserved(self):
        self.assertEqual(self.shortlist([row("P", "차수", bidNtceOrd="000")])["bids"][0]["revision"], "000")

    def test_missing_identity_or_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            self.shortlist([{"bidNtceNm": "번호 없음"}])
        with self.assertRaises(ValueError):
            self.shortlist([row("Q", "중복"), row("Q", "중복")])

    def test_invalid_profile_budget_is_request_error(self):
        self.profile.update(budget_min=5, budget_max=1)
        with self.assertRaises(RequestError):
            self.shortlist()
        self.profile.update(budget_min=-1, budget_max=10)
        with self.assertRaises(RequestError):
            self.shortlist()

    def test_invalid_limit_is_request_error(self):
        for limit in (0, -1, True, "5", 21):
            with self.subTest(limit=limit), self.assertRaises(RequestError):
                self.shortlist(limit=limit)

    def test_deadline_preserves_timezone_seconds_and_fraction(self):
        for deadline, expected in (("2026-10-23T09:30:00Z", "2026-10-23T18:30:00+09:00"),
                                   ("2026-10-23T10:00:30+09:00", "2026-10-23T10:00:30+09:00"),
                                   ("2026-10-23T10:00:00.500+09:00", "2026-10-23T10:00:00.500000+09:00")):
            with self.subTest(deadline=deadline):
                result = self.shortlist([row("UTC", "시간", bidClseDt=deadline)])
                self.assertEqual(result["bids"][0]["deadline"], expected)
        self.assertFalse(self.shortlist([row("SEC", "시간", bidClseDt="2026-10-23T10:00:30+09:00")],
                                         now="2026-10-23T10:00:30+09:00")["bids"])

    def test_malformed_deadline_not_silently_truncated(self):
        result = self.shortlist([row("BAD", "시간", bidClseDt="2026-11-01 18:00garbage")])
        self.assertIsNone(result["bids"][0]["deadline"])

    def test_deadline_period_boundaries_and_unknown(self):
        rows = [row(str(i), "웹", bidNtceDt="2026-08-01", bidClseDt=stamp) for i, stamp in enumerate(
            ("2026-10-01 00:00:00", "2026-10-31 23:59:59", "2026-09-30 12:00:00", ""))]
        result = self.shortlist(rows, start="2026-10-01", end="2026-10-31", now="2026-09-30T00:00:00+09:00")
        self.assertEqual({b["bid_no"] for b in result["bids"]}, {"0", "1"})
        self.assertEqual([b["status"] for b in result["excluded"]], ["excluded", "unknown"])

    def test_deadline_period_ignores_publication_date_and_uses_seoul_timezone(self):
        rows = [row('IN', '웹', bidNtceDt='', bidClseDt='2026-10-31T15:00:00Z'),
                row('OUT', '웹', bidNtceDt='2026-11-01', bidClseDt='2026-10-31T14:59:59Z')]
        result = self.shortlist(rows, start='2026-11-01', end='2026-11-01')
        self.assertEqual([b['bid_no'] for b in result['bids']], ['IN'])

    def test_notice_only_ranks_below_rfp_even_with_higher_similarity(self):
        notice = [{'file_name': '공고문.pdf', 'kinds': ['notice']}]
        rfp = [{'file_name': '제안요청서.pdf', 'kinds': ['rfp']}]
        result = self.shortlist([row('A', '웹', attachments=notice), row('B', '웹', attachments=rfp)],
                                similarity=lambda q, titles: [1, 0])
        self.assertEqual([b['bid_no'] for b in result['bids']], ['B', 'A'])
        fallback = result['bids'][1]
        self.assertTrue(fallback['notice_only'])
        self.assertEqual(fallback['recommendation_priority'], 'low')
        self.assertIn('해당 공고는 공고문만 있다', fallback['warnings'][0])
        self.assertEqual(self.shortlist([row('A', '웹', attachments=notice), row('B', '웹', attachments=rfp)],
                                        limit=1)['bids'][0]['bid_no'], 'B')

    def test_missing_or_unclassified_attachments_are_not_notice_only(self):
        for attachments in (None, [], [{'file_name': '첨부.zip', 'kinds': ['other']}],
                            [{'file_name': '공고문.pdf'}]):
            with self.subTest(attachments=attachments):
                result = self.shortlist([row('A', '웹', attachments=attachments)])
                self.assertFalse(result['bids'][0]['notice_only'])

    def test_eorder_lookup_failure_does_not_claim_notice_only_or_lose_warning(self):
        result = self.shortlist([row('A', '웹', notice_only=False,
                                     attachment_lookup_status='unavailable', warnings=['제안요청정보 조회 실패'],
                                     attachments=[{'file_name': '공고문.pdf', 'kinds': ['notice']}])])
        self.assertFalse(result['bids'][0]['notice_only'])
        self.assertEqual(result['bids'][0]['warnings'], ['제안요청정보 조회 실패'])

    # ---------------- 순위 ----------------

    def test_title_similarity_orders_results(self):
        result = self.shortlist()
        self.assertEqual([b["bid_no"] for b in result["bids"]], ["A", "B"])
        self.assertGreater(result["bids"][0]["score"], result["bids"][1]["score"])
        self.assertEqual(result["ranking_kind"], "lexical")

    def test_limit_defaults_to_twenty_and_caps(self):
        rows = [row(f"B{i:02d}", f"웹 구축 {i}") for i in range(25)]
        self.assertEqual(len(self.shortlist(rows)["bids"]), 20)
        self.assertEqual(self.shortlist(rows)["candidate_count"], 25)
        self.assertEqual(len(self.shortlist(rows, limit=5)["bids"]), 5)

    def test_injected_similarity_used_and_labeled(self):
        seen = {}

        def similarity(query, titles):
            seen["query"], seen["titles"] = query, titles
            return [0.1, 0.9]  # B가 더 유사하다고 주장

        result = self.shortlist(similarity=similarity)
        self.assertEqual(result["ranking_kind"], "injected")
        self.assertEqual([b["bid_no"] for b in result["bids"]], ["B", "A"])
        self.assertIn("웹 구축", seen["query"])
        self.assertEqual(seen["titles"], ["공공기관 홈페이지 구축", "AI 챗봇 서비스 구축"])

    def test_bad_similarity_output_rejected(self):
        for bad in ([0.1], "high", [0.1, float("nan")]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.shortlist(similarity=lambda q, t: bad)

    def test_no_keywords_means_no_ranking_claim(self):
        del self.profile["keywords"]
        result = self.shortlist()
        self.assertEqual(result["ranking_kind"], "none")
        self.assertTrue(all(b["score"] is None for b in result["bids"]))
        self.assertIn("프로필 키워드 미확인", result["bids"][0]["unknown"])
        self.assertEqual([b["bid_no"] for b in result["bids"]], ["A", "B"])  # 공고번호 순

    def test_lexical_similarity_cannot_separate_substring_match(self):
        # 가이드가 지적한 오매칭. 어휘 점수만으로는 걸러지지 않음을 기록해 둔다.
        scores = lexical_similarity("시스템", ["설치류 수면 시 글림프시스템 연구용역"])
        self.assertGreater(scores[0], 0)

    def test_every_result_needs_review(self):
        result = self.shortlist()
        self.assertTrue(result["needs_review"])
        self.assertTrue(all(b["needs_review"] for b in result["bids"]))
        self.assertEqual(result["stage"], "list_only")


class RecheckTest(unittest.TestCase):
    """③' 공고문 적재 후 기존 recommend_bids로 다시 거른다."""

    def setUp(self):
        self.profile = {"region": "서울", "keywords": ["웹"], "licenses": ["SW"],
                        "budget_min": 0, "budget_max": 500000000}
        self.shortlisted = [{"bid_no": "A", "revision": "000", "title": "웹 구축"},
                            {"bid_no": "B", "revision": "000", "title": "앱 구축"},
                            {"bid_no": "Z", "revision": "000", "title": "적재 안 됨"}]
        self.bids = [
            {"bid_no": "A", "revision": "000", "published_at": "2026-10-15",
             "deadline": "2026-11-01T18:00:00+09:00", "budget": "120000000",
             "regions": [], "industries": [], "licenses": [], "company_sizes": [], "certs": []},
            {"bid_no": "B", "revision": "000", "published_at": "2026-10-15",
             "deadline": "2026-11-01T18:00:00+09:00", "budget": "120000000",
             "regions": ["부산"], "industries": [], "licenses": [], "company_sizes": [], "certs": []},
        ]

    def recheck(self, **kwargs):
        kwargs.setdefault("now", NOW)
        kwargs.setdefault("hits", [])
        return recheck_after_ingest(copy.deepcopy(self.shortlisted), self.bids, self.profile,
                                    "2026-10-01", "2026-11-30", **kwargs)

    def test_marks_disqualified_confirmed_and_missing(self):
        result = self.recheck()
        status = {b["bid_no"]: b["recheck"]["status"] for b in result["bids"]}
        self.assertEqual(status, {"A": "confirmed", "B": "disqualified", "Z": "not_evaluated"})
        self.assertEqual(result["disqualified"], ["B"])
        self.assertEqual(result["not_evaluated"], ["Z"])

    def test_disqualified_carries_reason(self):
        row_b = next(b for b in self.recheck()["bids"] if b["bid_no"] == "B")
        self.assertEqual(row_b["recheck"]["reasons"], ["regions 조건 불일치"])

    def test_keeps_original_fields_and_review_flag(self):
        row_a = next(b for b in self.recheck()["bids"] if b["bid_no"] == "A")
        self.assertEqual(row_a["title"], "웹 구축")
        self.assertTrue(row_a["needs_review"])
        self.assertEqual(self.recheck()["stage"], "after_notice")

    def test_unknown_published_date_does_not_block_deadline_recheck(self):
        self.bids[0]["published_at"] = None
        row_a = next(b for b in self.recheck()["bids"] if b["bid_no"] == "A")
        self.assertEqual(row_a["recheck"]["status"], "confirmed")

    def test_recheck_excludes_deadline_outside_selected_period(self):
        self.bids[0]['deadline'] = '2026-12-01T00:00:00+09:00'
        row_a = next(b for b in self.recheck()['bids'] if b['bid_no'] == 'A')
        self.assertEqual(row_a['recheck']['status'], 'disqualified')
        self.assertIn('입찰마감일이 선택 기간 밖입니다.', row_a['recheck']['reasons'])

    def test_limit_covers_all_shortlisted(self):
        # 기본 limit(5)으로 잘려서 통과 공고가 부적격으로 보이면 안 된다.
        self.shortlisted = [{"bid_no": f"B{i:02d}", "revision": "000"} for i in range(8)]
        self.bids = [{"bid_no": f"B{i:02d}", "revision": "000", "published_at": "2026-10-15",
                      "deadline": "2026-11-01T18:00:00+09:00", "budget": "120000000",
                      "regions": [], "industries": [], "licenses": [],
                      "company_sizes": [], "certs": []} for i in range(8)]
        result = self.recheck()
        self.assertTrue(all(b["recheck"]["status"] == "confirmed" for b in result["bids"]))

    def test_unselected_high_rank_and_explicit_limit_cannot_hide_target(self):
        self.shortlisted = [self.shortlisted[0]]
        other = {**self.bids[0], "bid_no": "OTHER"}
        self.bids.append(other)
        result = self.recheck(limit=1, hits=[{"bid_no": "OTHER", "revision": "000", "distance": 0},
                                            {"bid_no": "A", "revision": "000", "distance": 1}])
        self.assertEqual(result["bids"][0]["recheck"]["status"], "confirmed")

    def test_duplicate_recheck_keys_rejected(self):
        self.shortlisted.append(self.shortlisted[0])
        with self.assertRaises(RequestError):
            self.recheck()


if __name__ == "__main__":
    unittest.main()
