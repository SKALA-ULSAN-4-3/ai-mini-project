// 새 흐름의 가짜 백엔드.
//  - handlePipeline: 아직 서버에 없는 API (1번 검색·적재·작업, 4번 선택·승인)
//  - handleBidData : 이미 서버에 있는 API (3번 추리기·점수·체크리스트, 2번 요약·채점표·질의)
// 둘 다 null 을 돌려주면 "mock에 없는 주소"입니다.
import { BIDS, FAIL_NO } from './mockData'
import { addDays, iso } from '../utils'

const jobs = {}
let seq = 0
const loadDocs = () => JSON.parse(localStorage.getItem('mock_docs') || '{}') // { 공고번호: 준비 완료 시각 }
const STEP = 700 // 공고 한 건당 가짜 처리 시간(ms)

function startJob(kind, bids) {
  const id = `J-${++seq}`
  jobs[id] = { kind, start: Date.now(), bids }
  if (kind === 'documents') {
    const docs = loadDocs()
    bids.forEach((b, i) => { docs[b.bid_no] = Date.now() + (i + 1) * STEP })
    localStorage.setItem('mock_docs', JSON.stringify(docs))
  }
  return id
}

// ---- 1번 · 4번 (서버에 아직 없는 API) ----
export function handlePipeline({ config, url, method, body, ok, fail }) {
  // 실제 1번 API 는 32자리 16진수 search_id 를 돌려줍니다.
  if (url === '/search-bids' && method === 'post') return ok(config, { search_id: 'a1b2c3d4'.repeat(4), items: [], cached: false })

  if (['/fetch-notices', '/fetch-documents'].includes(url) && method === 'post') {
    const kind = url === '/fetch-notices' ? 'notices' : 'documents'
    return ok(config, { job_id: startJob(kind, body.bids || []), status: 'queued', total: (body.bids || []).length }, 202)
  }
  const jm = url.match(/^\/jobs\/([^/]+)$/)
  if (jm && method === 'get') {
    const j = jobs[jm[1]]
    if (!j) throw fail(config, 404, '작업 없음')
    const done = Math.min(j.bids.length, Math.floor((Date.now() - j.start) / STEP))
    const bids = j.bids.map((b, i) => {
      const bad = j.kind === 'notices' && b.bid_no === FAIL_NO
      if (i >= done) return { bid_no: b.bid_no, bid_order: b.revision, status: i === done ? 'running' : 'queued', error: null }
      return { bid_no: b.bid_no, bid_order: b.revision, status: bad ? 'failed' : 'completed', error: bad ? '확인 필요: 첨부 변환에 실패했습니다.' : null }
    })
    return ok(config, { status: done >= j.bids.length ? (bids.every((x) => x.status === 'failed') ? 'failed' : bids.some((x) => x.status === 'failed') ? 'partial_failed' : 'completed') : 'running', done, total: j.bids.length, bids })
  }
  // 4번 선택·승인 (가짜): 브라우저 localStorage에 계정별로 보관
  if (['/me/selections', '/me/approvals', '/me/pipeline'].includes(url)) {
    const key = 'mock_pipeline'
    const rows = JSON.parse(localStorage.getItem(key) || '[]')
    if (method === 'get') return ok(config, rows)
    let row = rows.find((r) => r.bid_no === body.bid_no && r.revision === body.revision)
    if (url === '/me/selections') {
      if (!row) { row = { ...body, status: 'selected', selected_at: new Date().toISOString(), approved_at: null }; rows.push(row) }
    } else {
      if (!row) throw fail(config, 409, '선택하지 않은 공고는 승인할 수 없습니다.')
      if (row.status !== 'approved') { row.status = 'approved'; row.approved_at = new Date().toISOString() }
    }
    localStorage.setItem(key, JSON.stringify(rows))
    return ok(config, row)
  }
  return null
}

// ---- 2번 · 3번 (서버에 이미 있는 API를 흉내) ----
const pub = ({ bid_no, revision, title, agency, published_at, budget, deadline, regions, unknown, distance, needs_review, reason }) => ({
  bid_no, revision, title, agency, published_at, budget, deadline, regions, unknown, distance, needs_review, reason,
})

export function handleBidData({ config, url, method, body, profile, ok, fail }) {
  const params = config.params || {}
  const find = (no) => BIDS.find((b) => b.bid_no === no)

  // ② 추리기 (프로필이 없으면 404). 실제 응답: { bids, excluded, candidate_count, needs_review }
  if (url === '/bids' && method === 'get') {
    if (!profile) throw fail(config, 404, '프로필 없음')
    const { from, to } = params
    const list = BIDS.filter((b) => (!from || b.published_at >= from) && (!to || b.published_at <= to))
    return ok(config, { bids: list.map(pub), excluded: [], candidate_count: list.length, needs_review: true })
  }

  // ③' 공고문 적재 후 재확인: 모두 confirmed, 첫 공고만 일부 조건 미확인으로 흉내
  if (url === '/bids/recheck' && method === 'post') {
    const rows = (body.bids || []).map((r) => {
      const b = find(r.bid_no)
      if (!b) return { ...r, recheck: { status: 'not_evaluated', reasons: ['적재된 공고 목록에 없습니다.'] }, needs_review: true }
      return { ...pub(b), recheck: { status: 'confirmed', reasons: [], unknown: b.unknown || [] }, needs_review: true }
    })
    return ok(config, { bids: rows, needs_review: true, stage: 'after_notice', disqualified: [], not_evaluated: rows.filter((r) => r.recheck.status === 'not_evaluated').map((r) => r.bid_no) })
  }

  // ④ 요약 여러 건. 실패한 건은 { status: 'error', code, detail }
  if (url === '/bids/summaries' && method === 'post') {
    const results = (body.bids || []).map((r) => {
      const b = find(r.bid_no)
      if (!b || b.bid_no === FAIL_NO) return { bid_no: r.bid_no, revision: r.revision, status: 'error', code: 404, detail: '공고문이 없습니다.' }
      let summary = b.summary
      let missing = []
      if (b.bid_no === BIDS[1].bid_no) { // 일부 항목을 못 찾은 경우를 흉내
        const { joint_and_subcontract, ...rest } = b.summary
        summary = rest
        missing = ['joint_and_subcontract']
      }
      return { status: 'ok', bid_no: b.bid_no, revision: b.revision, summary, missing, needs_review: false, handoff: missing.length > 0, latency_ms: 900, documents: 'notice_only' }
    })
    return ok(config, { results, ok: results.filter((r) => r.status === 'ok').length, failed: results.filter((r) => r.status !== 'ok').length })
  }

  if (/^\/bids\/[^/]+\/documents$/.test(url) && method === 'get') return ok(config, [])

  const m = url.match(/^\/bids\/([^/]+)\/(summary|scoring-table|score|checklist)$/)
  if (m && method === 'get') {
    const b = find(m[1])
    if (!b) throw fail(config, 404, '해당 공고·차수의 데이터가 없습니다.')
    if (m[2] !== 'summary' && !params.revision) throw fail(config, 400, 'revision 필요')
    if (m[2] === 'summary') return ok(config, { bid_no: b.bid_no, revision: b.revision, summary: b.summary, missing: [], needs_review: false, handoff: false, latency_ms: 900 })
    // 제안요청서가 아직 준비되지 않았으면 409
    if (['scoring-table', 'score'].includes(m[2]) && !(loadDocs()[b.bid_no] <= Date.now())) throw fail(config, 409, '제안요청서가 아직 준비되지 않았습니다.')
    if (m[2] === 'scoring-table') return ok(config, b.scoringTable)

    if (m[2] === 'score') {
      const src = b.scoringTable.items.map((it) => it.source_refs[0])
      const hasCredit = !!profile?.credit_rating // 신용등급이 있으면 계산, 없으면 "프로필 정보 부족"
      const items = [
        { id: 'item01', item: '수행 실적', max: 10, expected: 8, status: 'calculated', needs_review: true, sources: [src[0]], basis: b.scoringTable.items[0].criteria, reason: '원문 기준에 따라 코드로 계산한 예상 점수', missing_fields: [] },
        hasCredit
          ? { id: 'item02', item: '신용등급', max: 10, expected: 10, status: 'calculated', needs_review: true, sources: [src[1]], basis: b.scoringTable.items[1].criteria, reason: '원문 기준에 따라 코드로 계산한 예상 점수', missing_fields: [] }
          : { id: 'item02', item: '신용등급', max: 10, expected: '담당자 판단', status: 'missing_profile', needs_review: true, sources: [src[1]], basis: b.scoringTable.items[1].criteria, reason: '점수 계산에 필요한 프로필 정보 부족', missing_fields: ['credit_rating'] },
        { id: 'item03', item: '기술 제안', max: 70, expected: '담당자 판단', status: 'manual', needs_review: true, sources: [src[2]], basis: b.scoringTable.items[2].criteria, reason: '정성·가격 항목은 담당자 판단', missing_fields: [] },
        { id: 'item04', item: '입찰가격', max: 10, expected: '담당자 판단', status: 'manual', needs_review: true, sources: [src[3]], basis: b.scoringTable.items[3].criteria, reason: '정성·가격 항목은 담당자 판단', missing_fields: [] },
      ]
      const missing = hasCredit ? [] : ['credit_rating']
      return ok(config, { bid_no: b.bid_no, revision: b.revision, items, needs_review: true, missing_fields: missing, questions: missing.map((f) => `${f} 정보를 입력해 주세요.`) })
    }

    // checklist: 프로필의 보유 서류에 있으면 owned, 모르면(null) null
    const owned = profile?.owned_docs
    const ref = (page) => ({ bid_no: b.bid_no, revision: b.revision, filename: '제안요청서.pdf', page, collected_at: iso(now()) })
    const dd = (off) => ({ due: `${iso(addDays(now(), off))}T14:00:00+09:00`, d_day: off, remaining_seconds: Math.max(0, off) * 86400, status: off <= 0 ? 'expired' : 'upcoming' })
    const dueOff = Math.round((new Date(b.deadline) - now()) / 86400000)
    return ok(config, {
      bid_no: b.bid_no, revision: b.revision, needs_review: owned == null,
      documents: b.docs.map((doc, i) => ({ id: `doc${String(i + 1).padStart(2, '0')}`, doc, sources: [ref(30 + (i % 2))], notes: ['나라장터 전자제출'], ...dd(dueOff), owned: owned == null ? null : owned.includes(doc), submitted: false, needs_review: owned == null })),
      schedule: b.schedule.map((s, i) => ({ id: `evt${String(i + 1).padStart(2, '0')}`, event: s.event, sources: [ref(5)], notes: [], ...dd(s.off + (dueOff - b.schedule[2].off)), needs_review: false })),
    })
  }

  // X2 채점 에이전트 (가짜): 고정 경로 점수에 도구 호출 기록을 붙입니다. 신용등급이 없으면 되묻기(needs_input).
  if (url === '/agent/score' && method === 'post') {
    const res = handleBidData({ config: { ...config, params: { revision: body.revision } }, url: `/bids/${body.bid_no}/score`, method: 'get', body: {}, profile, ok, fail })
    const d = res.data
    const needs = d.missing_fields.length > 0
    const calls = d.items.map((it) => ({ name: it.status === 'manual' ? 'mark_manual' : it.status === 'calculated' ? 'calc_score' : 'get_profile', status: it.status }))
    return ok(config, { ...d, status: needs ? 'needs_input' : 'complete', unresolved_items: [], tool_calls: [{ name: 'get_scoring_table' }, ...calls], model_calls: calls.length + 1, latency_ms: 7500, token_usage: { input_tokens: 4200, output_tokens: 380, complete: true }, cost: null })
  }
  // X3 음성 (가짜): STT 는 정해진 질문 문장을 돌려주고, TTS 는 없는 것으로 처리해 브라우저 읽기 기능으로 대신합니다.
  if (url === '/stt' && method === 'post') return ok(config, { text: '이 공고의 마감 일시는 언제인가요?' })
  if (url === '/tts' && method === 'post') throw fail(config, 404, 'mock 에는 음성 합성이 없습니다.')

  // Q&A: 키워드로 답을 고르는 흉내 (요청 prompt, 응답 response, 출처는 문자열 목록)
  if (url === '/rag-query' && method === 'post') {
    const q = body.prompt || ''
    const b = find(body.bid_no)
    const reply = (response, extra = {}) => ok(config, { prompt: q, response, sources: [], needs_review: false, handoff: false, latency_ms: 420, ...extra })
    if (/낙찰|확률|몇 점/.test(q)) return reply('이 질문의 답은 문서에 없습니다.', { handoff: true })
    if (!b) return reply('어느 공고에 대한 질문인지 알려 주세요. 공고 요약 화면에서 "이 공고에 질문하기"를 눌러 주세요.')
    if (/마감/.test(q)) return reply(`제안서 제출 마감은 ${b.deadline.slice(0, 10)} 14:00입니다.`, { sources: ['입찰공고문.pdf p.1'] })
    if (/예산|추정가격/.test(q)) return reply(b.summary.budget.value, { sources: ['입찰공고문.pdf p.1'] })
    if (/서류|제출/.test(q)) return reply(`제출서류: ${b.docs.join(', ')}`, { sources: ['제안요청서.pdf p.30'] })
    if (/자격|면허/.test(q)) return reply(b.summary.eligibility.value, { sources: ['입찰공고문.pdf p.2'], needs_review: true })
    return reply('문서에서 찾을 수 없습니다.', { handoff: true })
  }
  return null
}
const now = () => new Date()
