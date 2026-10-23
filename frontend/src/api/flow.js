// 새 흐름(검색 → 요약 → 채점 → 승인 → 체크리스트)의 API 호출 모음.
// 실제 서버 코드(2번 RAG · 3번 공고 로직)를 읽고 응답 모양을 맞췄습니다.
// ★ 1번(/search-bids, /fetch-notices, /fetch-documents, /jobs)과 4번(/me/...)은 아직 서버에 없어서
//   가이드 문서 기준의 "가정"입니다. 담당자의 실제 응답과 다르면 이 파일만 고치세요.
import { rag } from './client'

export const SUMMARY_LABELS = {
  title: '사업명', agency: '발주기관', period: '사업 기간', budget: '사업 예산',
  contract_method: '계약 방법', evaluation_ratio: '평가 비율(기술:가격)', eligibility: '입찰 참가자격',
  joint_and_subcontract: '공동수급·하도급', schedule: '주요 일정', main_tasks: '주요 과업',
}
// 상태값: 요약(2번)은 ok / error, 작업(1번)은 queued → running → completed / partial_failed / failed
// partial_failed = 일부 첨부만 실패 (받은 문서로는 계속 진행 가능, 실패 내용은 안내)
export const isOk = (s) => ['ok', 'completed', 'partial_failed'].includes(s)
export const isFailed = (s) => ['failed', 'error'].includes(s)
export const isFinished = (s) => ['completed', 'partial_failed', 'failed'].includes(s)

// 차수는 문자열로 다룹니다(앞의 0 유지). 1번은 bid_order, 2번 이후는 revision 이라 둘 다 받습니다.
const rev = (b) => String(b.revision ?? b.bid_order ?? '000')
const refs = (bids) => bids.map((b) => ({ bid_no: b.bid_no, revision: b.revision }))
// 1번 API 에는 두 이름을 모두 보내 둡니다. (아직 어느 쪽을 받는지 확정 전)
const pipelineRefs = (bids) => bids.map((b) => ({ bid_no: b.bid_no, revision: b.revision, bid_order: b.revision }))

// 3번 /bids 의 공고 한 건을 화면에서 쓰는 모양으로 맞춥니다.
export function toBid(b) {
  return {
    bid_no: b.bid_no, revision: rev(b),
    title: b.title || '(공고명 없음)', agency: b.agency || '',
    notice_date: b.published_at || '', deadline: b.deadline || '',
    budget: b.budget ?? null, regions: b.regions || [],
    unknown: b.unknown || [], // 확인하지 못한 조건들 (제외하지 않고 "미확인"으로 표시)
    reason: b.reason || '',
  }
}

// ① 검색 (1번 — 아직 서버에 없음)
export async function searchBids({ from, to, queries, limit = 20 }) {
  return (await rag.post('/search-bids', { from, to, queries, limit })).data
}
// ② 추린 공고 (3번): { bids, excluded, candidate_count, needs_review }
// search_id 는 3번이 1번의 새 검색 결과를 읽도록 바뀌면 필요해질 값이라 미리 함께 보냅니다. (지금 서버는 무시)
export async function fetchCandidates(from, to, searchId) {
  const d = (await rag.get('/bids', { params: { from, to, limit: 20, search_id: searchId } })).data
  return { bids: (d.bids || []).map(toBid), excluded: d.excluded || [] }
}
// ③ 공고문 준비 / ⑤ 제안요청서 준비: 작업 번호(job_id)를 돌려줌 (1번 — 아직 서버에 없음)
export async function fetchNotices(searchId, bids) {
  return (await rag.post('/fetch-notices', { search_id: searchId, bids: pipelineRefs(bids) })).data.job_id
}
export async function fetchDocuments(searchId, bids) {
  return (await rag.post('/fetch-documents', { search_id: searchId, bids: pipelineRefs(bids) })).data.job_id
}
export async function getJob(id) {
  const d = (await rag.get(`/jobs/${id}`)).data
  return { ...d, bids: (d.bids || []).map((b) => ({ ...b, revision: rev(b) })) }
}
// ④ 요약 여러 건 (2번): results[{status:'ok'|'error', summary, missing, ... | code, detail}]
export async function fetchSummaries(bids) {
  const d = (await rag.post('/bids/summaries', { bids: refs(bids) })).data
  return (d.results || []).map((r, i) => ({ ...r, bid_no: r.bid_no ?? bids[i]?.bid_no, revision: rev({ ...bids[i], ...r }) }))
}
// ⑤⑧ 선택·승인 저장 (4번 — 아직 서버에 없음)
export async function saveSelections(searchId, bids) {
  return (await rag.post('/me/selections', { search_id: searchId, bids: refs(bids) })).data
}
export async function saveApprovals(bids) {
  return (await rag.post('/me/approvals', { bids: refs(bids) })).data
}
// ⑦ 채점표(2번) · 예상 점수(3번) / ⑨ 체크리스트(3번). 3번 경로는 revision 이 필수입니다.
export async function fetchScoringTable(b) {
  return (await rag.get(`/bids/${b.bid_no}/scoring-table`, { params: { revision: b.revision } })).data
}
export async function fetchScore(b) {
  return (await rag.get(`/bids/${b.bid_no}/score`, { params: { revision: b.revision } })).data
}
export async function fetchChecklist(b) {
  return (await rag.get(`/bids/${b.bid_no}/checklist`, { params: { revision: b.revision } })).data
}
// Q&A (2번): 요청은 prompt, 응답은 response (sources 는 문자열 목록)
export async function askQuestion(prompt, bid) {
  const body = { prompt, source: 'pdf' }
  if (bid?.bid_no) { body.bid_no = bid.bid_no; body.revision = bid.revision }
  return (await rag.post('/rag-query', body)).data
}
