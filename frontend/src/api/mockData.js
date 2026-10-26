// 가짜 공고 데이터 (화면 테스트용 가상값). 실제 서버(2번 RAG · 3번 공고 로직)와 같은 응답 모양입니다.
import { addDays, iso, won } from '../utils'

const now = new Date()
const day = (n) => iso(addDays(now, n))

function make(no, title, agency, budget, noticeOff, deadlineOff, unknown) {
  const revision = '000'
  const deadline = `${day(deadlineOff)}T14:00:00+09:00`
  const ref = (filename, page) => ({ bid_no: no, revision, filename, page, collected_at: day(0) })
  const item = (value, file, page) => ({ value, source: `${file} p.${page}`, source_refs: [ref(file, page)] })
  return {
    bid_no: no, revision, title, agency, budget, deadline, published_at: day(noticeOff),
    regions: [], unknown, distance: 0.8, needs_review: true,
    reason: '명시된 규칙에서 불일치 없음; 공고별 최소 L2 거리 순',
    // 요약: 팀이 확정한 10개 항목 구조
    summary: {
      title: item(title, '입찰공고문.pdf', 1),
      agency: item(agency, '입찰공고문.pdf', 1),
      period: item('계약일로부터 8개월', '제안요청서.pdf', 6),
      budget: item(`추정가격 ${won(budget)} (부가세 포함)`, '입찰공고문.pdf', 1),
      contract_method: item('협상에 의한 계약', '입찰공고문.pdf', 2),
      evaluation_ratio: item('기술 90 : 가격 10', '제안요청서.pdf', 24),
      eligibility: item('소프트웨어사업자(컴퓨터 관련 서비스사업) 등록 업체', '입찰공고문.pdf', 2),
      joint_and_subcontract: item('공동수급 허용, 하도급 제한', '입찰공고문.pdf', 3),
      schedule: item(`제안서 제출 마감 ${day(deadlineOff)} 14:00`, '입찰공고문.pdf', 1),
      main_tasks: item('시스템 설계·구축, 시험 운영, 사용자 교육', '제안요청서.pdf', 8),
    },
    // 2번 /scoring-table: 평탄한 항목 목록 + 합계 검증
    scoringTable: {
      bid_no: no, revision, total_max_score: 100, declared_total: 100, consistent: true,
      pass_rule: '기술평가 85점 이상 협상적격', pass_rule_source: '제안요청서.pdf p.24',
      needs_review: true, handoff: false, latency_ms: 6400,
      items: [
        { section: '정량 평가', item: '수행 실적', max_score: 10, eval_type: '정량', criteria: '최근 3년 유사 실적 금액 기준', source: '제안요청서.pdf p.24', source_refs: [ref('제안요청서.pdf', 24)], source_verified: true },
        { section: '정량 평가', item: '신용등급', max_score: 10, eval_type: '정량', criteria: '신용평가등급별 배점', source: '제안요청서.pdf p.24', source_refs: [ref('제안요청서.pdf', 24)], source_verified: true },
        { section: '정성 평가', item: '기술 제안', max_score: 70, eval_type: '정성', criteria: '제안 내용의 우수성', source: '제안요청서.pdf p.25', source_refs: [ref('제안요청서.pdf', 25)], source_verified: true },
        { section: '가격 평가', item: '입찰가격', max_score: 10, eval_type: '가격', criteria: '입찰가격 평가 산식', source: '제안요청서.pdf p.26', source_refs: [ref('제안요청서.pdf', 26)], source_verified: true },
      ],
    },
    // 3번 /checklist 의 documents · schedule 원본 (d_day · owned 는 요청 때 계산)
    docs: ['사업자등록증 사본', '중소기업확인서', '소프트웨어사업자 신고확인서', '제안서', '가격 제안서', '청렴서약서'],
    schedule: [
      { event: '제안 설명회', off: deadlineOff - 7 },
      { event: '질의 마감', off: deadlineOff - 5 },
      { event: '제안서 제출 마감', off: deadlineOff },
    ],
  }
}

export const FAIL_NO = 'R26BK01235222' // 공고문 준비가 실패하는 가짜 공고
export const BIDS = [
  make('R26BK01234567', 'AI 민원 챗봇 구축 용역', '울산광역시청', 180000000, -5, 12, []),
  make('R26BK01234890', '공공 모바일 앱 고도화 사업', '한국지역정보개발원', 320000000, -12, 20, []),
  make('R26BK01235011', '통합 웹 포털 재구축', '서울특별시교육청', 450000000, -20, 30, ['industries 제한 미확인']),
  make('R26BK01235120', '지능형 고객응대 시스템 개발', '경기도청', 260000000, -8, 15, []),
  make('R26BK01235222', '데이터 분석 플랫폼 구축', '한국데이터진흥원', 390000000, -15, 25, []),
  make('R26BK01235333', '스마트 안내 앱 개발 용역', '부산광역시청', 150000000, -3, 10, ['금액 비교 정보 미확인']),
]
