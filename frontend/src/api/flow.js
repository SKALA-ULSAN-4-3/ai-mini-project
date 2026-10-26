// 새 흐름(검색 → 요약 → 채점 → 승인 → 체크리스트)의 API 호출 모음.
// 실제 서버 코드(2번 RAG · 3번 공고 로직)를 읽고 응답 모양을 맞췄습니다.
// ★ 1번(/search-bids, /fetch-notices, /fetch-documents, /jobs)과 4번(/me/...)은 아직 서버에 없어서
//   가이드 문서 기준의 "가정"입니다. 담당자의 실제 응답과 다르면 이 파일만 고치세요.
import client, { rag } from './client'

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
    notice_only: b.notice_only === true,
    warnings: b.warnings || [],
    region_restriction: b.region_restriction || null,
    industry_restriction: b.industry_restriction || null,
    recheck: b.recheck || null, // ③' 공고문 적재 후 재확인 결과 { status, reasons, unknown }
  }
}

// ① 검색 (1번 — 아직 서버에 없음)
export async function searchBids({ from, to, queries, limit = 100 }) {
  return (await rag.post('/search-bids', { from, to, queries, limit })).data
}
// ② 추린 공고 (3번): { bids, excluded, candidate_count, needs_review }
// search_id 는 3번이 1번의 새 검색 결과를 읽도록 바뀌면 필요해질 값이라 미리 함께 보냅니다. (지금 서버는 무시)
export async function fetchCandidates(from, to, searchId) {
  const d = (await rag.get('/bids', { params: { from, to, limit: 20, search_id: searchId } })).data
  return { bids: (d.bids || []).map(toBid), excluded: d.excluded || [] }
}
// ③' 공고문 준비가 끝난 뒤 재확인 (3번): 본문까지 보고 부적격인 공고를 표시합니다. (삭제하지 않고 표시만)
// 응답: { bids:[{...공고, recheck:{status: confirmed|disqualified|unknown|not_evaluated, reasons, unknown}}], disqualified, not_evaluated }
export async function recheckBids(from, to, searchId, bids) {
  const body = { from, to, bids: refs(bids).slice(0, 20), search_id: searchId }
  const d = (await rag.post('/bids/recheck', body)).data
  return (d.bids || []).map(toBid)
}
// ③ 공고문 준비 / ⑤ 제안요청서 준비: 작업 번호(job_id)를 돌려줌 (1번 — 아직 서버에 없음)
export async function fetchNotices(searchId, bids) {
  return (await rag.post('/fetch-notices', { search_id: searchId, bids: pipelineRefs(bids) }, { timeout: 30000 })).data.job_id
}
export async function fetchDocuments(searchId, bids) {
  return (await rag.post('/fetch-documents', { search_id: searchId, bids: pipelineRefs(bids) }, { timeout: 30000 })).data.job_id
}
export async function getJob(id) {
  const d = (await rag.get(`/jobs/${id}`, { timeout: 15000 })).data
  return { ...d, bids: (d.bids || []).map((b) => ({ ...b, revision: rev(b) })) }
}
// ④ 요약 여러 건 (2번): results[{status:'ok'|'error', summary, missing, ... | code, detail}]
export async function fetchSummaries(bids) {
  const d = (await rag.post('/bids/summaries', { bids: refs(bids) })).data
  return (d.results || []).map((r, i) => ({ ...r, bid_no: r.bid_no ?? bids[i]?.bid_no, revision: rev({ ...bids[i], ...r }) }))
}
// ⑤⑧ 선택·승인 (4번 Java: POST /api/me/selections, /api/me/approvals, GET /api/me/pipeline)
//   서버는 공고 1건씩 받고({bid_no, revision}, 차수는 "000" 같은 문자열 그대로), 누적 저장합니다. 승인은 선택 저장 뒤에만 가능(아니면 409).
export async function saveSelections(bids) {
  for (const b of bids) await client.post('/me/selections', { bid_no: b.bid_no, revision: String(b.revision) }, { timeout: 30000 })
}
export async function saveApprovals(bids) {
  for (const b of bids) await client.post('/me/approvals', { bid_no: b.bid_no, revision: String(b.revision) }, { timeout: 30000 })
}
// 로그인 직후: 서버에 저장된 선택·승인 목록 [{bid_no, revision, status:'selected'|'approved', ...}]
export async function fetchPipeline() {
  return (await client.get('/me/pipeline')).data || []
}

// ④ 요약 저장 (4번 Java: PUT /api/bids/{bid_no}/summary). 로그인한 회사 계정에 저장되고, 같은 공고·차수는 덮어씁니다.
// 요청: 2번이 만든 요약 결과를 그대로 { revision, summary, missing, needs_review, handoff, latency_ms }
export async function saveSummary(r) {
  const body = { revision: r.revision, summary: r.summary, missing: r.missing || [], needs_review: !!r.needs_review, handoff: !!r.handoff }
  if (typeof r.latency_ms === 'number') body.latency_ms = r.latency_ms
  return (await client.put(`/bids/${encodeURIComponent(r.bid_no)}/summary`, body)).data
}
// 성공한 요약만 저장하고, 실패한 건수를 돌려줍니다. (저장 실패가 화면 흐름을 막지 않도록 예외는 던지지 않습니다)
export async function saveSummaries(results) {
  const targets = results.filter((r) => r.status === 'ok' && r.summary && typeof r.summary === 'object')
  const settled = await Promise.allSettled(targets.map(saveSummary))
  return { total: targets.length, failed: settled.filter((x) => x.status === 'rejected').length }
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

// X2 채점 에이전트 (3번): POST /agent/score {bid_no, revision}. 서버에 켜져 있지 않으면 404.
// 응답: 고정 경로 점수와 같은 items 에 status(complete|needs_input|…), questions, tool_calls, latency_ms, token_usage 가 더해집니다.
export async function fetchAgentScore(b) {
  return (await rag.post('/agent/score', { bid_no: b.bid_no, revision: String(b.revision) }, { timeout: 90000 })).data
}

// X3 음성 질의 (2번): 음성→텍스트 POST /stt (multipart, 필드 audio) → {text}, 텍스트→음성 POST /tts {text} → 오디오.
//   ※ 요청·응답 형식은 아직 서버와 확정 전인 가정입니다. 확정되면 이 두 함수만 고치면 됩니다.
export async function transcribe(blob) {
  const fd = new FormData()
  fd.append('audio', blob, 'question.webm')
  return (await rag.post('/stt', fd)).data.text
}
export async function synthesize(text) {
  return (await rag.post('/tts', { text }, { responseType: 'blob' })).data
}
