<script setup>
import { ref, computed, nextTick, onUnmounted } from 'vue'
import { useFlowStore } from '../stores/flow'
import { searchBids, fetchCandidates, fetchNotices, recheckBids, isOk } from '../api/flow'
import { errorMessage } from '../api/client'
import { addDays, iso, won, dday, keyOf, ymd, unknownLabel } from '../utils'
import JobProgress from '../components/JobProgress.vue'
import ProfileSummary from '../components/ProfileSummary.vue'
import RecheckBadge from '../components/RecheckBadge.vue'

const flow = useFlowStore()

// ① 검색 조건
const to = ref(flow.period?.to || iso(new Date()))
const monthStart = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1) } // 이번 달 1일
const from = ref(flow.period?.from || iso(monthStart()))
const queries = ref(flow.period?.queries || '')
const queryList = computed(() => queries.value.split(',').map((s) => s.trim()).filter(Boolean))
const loading = ref(false)
const error = ref('')
const noProfile = ref(false)
// 검색 조건 칸: 결과가 있으면 한 줄 요약으로 접어 두고, 필요할 때만 펼칩니다. (결과가 나왔는데 또 검색을 누르는 실수를 막음)
const formOpen = ref(!flow.candidates.length)
const resultsTop = ref(null)

// ② 추린 공고 중 공고문을 받을 공고 (최대 20건)
const checked = ref(flow.candidates.slice(0, 20).map(keyOf))
const jobId = ref('')
const noticeJob = ref(null)

// 프로필 키워드: 처음 열었을 때 검색어가 비어 있으면 채워 주고, 칩을 누르면 검색어에 추가
function onProfile(p) {
  if (!queries.value.trim() && p.keywords?.length) queries.value = p.keywords.join(', ')
}
function addKeyword(k) {
  const list = [...queryList.value]
  if (!list.includes(k)) list.push(k)
  queries.value = list.join(', ')
}

// 검색 진행 표시: 서버는 퍼센트를 알려 주지 않으므로 "단계"와 경과 시간으로 보여 줍니다.
// 게이지는 단계 안에서 천천히 차오르다가, 다음 단계로 넘어가는 실제 신호(응답 도착)가 오면 그 위치로 올라갑니다.
const STAGE_LABELS = [
  '나라장터에서 공고 목록 조회',
  '회사 프로필 조건으로 공고 추리기',
  '결과 정리',
]
const stage = ref(0) // 1~3: 지금 하는 단계
const pct = ref(0)
const elapsed = ref(0)
let progressTimer = null
const STAGE_CAP = { 1: 55, 2: 92, 3: 99 } // 단계 안에서 게이지가 올라갈 수 있는 한계
const STAGE_START = { 1: 3, 2: 58, 3: 95 } // 단계가 시작될 때 게이지 위치

function setStage(n) {
  stage.value = n
  pct.value = Math.max(pct.value, STAGE_START[n])
}
function startProgress() {
  stopProgress()
  elapsed.value = 0
  pct.value = 0
  setStage(1)
  const t0 = Date.now()
  progressTimer = setInterval(() => {
    elapsed.value = Math.floor((Date.now() - t0) / 1000)
    const cap = STAGE_CAP[stage.value]
    pct.value = Math.min(cap, pct.value + (cap - pct.value) * 0.03 + 0.05) // 한계에 가까워질수록 천천히
  }, 400)
}
function stopProgress() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
}
onUnmounted(stopProgress)

async function search() {
  if (loading.value) return // 이미 검색 중이면 무시 (연타·엔터 중복 방지)
  error.value = ''; noProfile.value = false
  const list = queries.value.split(',').map((s) => s.trim()).filter(Boolean)
  if (!list.length) { error.value = '검색어를 한 개 이상 입력해 주세요.'; return }
  if (from.value > to.value) { error.value = '시작일이 종료일보다 늦을 수 없습니다.'; return }
  loading.value = true
  startProgress()
  jobId.value = ''; noticeJob.value = null
  try {
    // ① 나라장터 검색 (1번 API)
    const d = await searchBids({ from: from.value, to: to.value, queries: list, limit: 20 })
    setStage(2)
    flow.resetFrom(3)
    flow.searchId = d.search_id
    flow.period = { from: from.value, to: to.value, queries: queries.value }
    // ② 회사 프로필에 맞게 추리기 (3번 API). 여기서 404 는 "저장된 프로필이 없음"입니다.
    try {
      const r = await fetchCandidates(from.value, to.value, d.search_id)
      flow.candidates = r.bids
      flow.excluded = r.excluded
      setStage(3)
      checked.value = flow.candidates.slice(0, 20).map(keyOf)
      if (flow.candidates.length) {
        formOpen.value = false // 검색이 끝나면 조건 칸을 접고 결과 목록을 바로 보여 줌
        nextTick(() => resultsTop.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }))
      }
    } catch (e) {
      if (e.response?.status === 404) noProfile.value = true
      else throw e
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    stopProgress()
    loading.value = false
  }
}

// ③ 공고문 준비 시작
// 전체 선택·해제: 한 번에 받을 수 있는 건수(최대 20건) 안에서, 공고문만 있는 공고는 뺀 앞쪽부터 고릅니다.
// 마감일 색: 3일 이내 빨강, 7일 이내 주황, 그 외 초록, 마감·미확인은 회색
const ddayTone = (deadline) => {
  const t = dday(deadline)
  if (t === '미확인') return 'na'
  if (t === '마감') return 'over'
  const n = t === 'D-day' ? 0 : Number(/^D-(\d+)$/.exec(t)?.[1])
  return n <= 3 ? 'hot' : n <= 7 ? 'warn' : 'ok'
}
// 결과 위쪽 요약 숫자
const kpi = computed(() => ({
  total: flow.candidates.length,
  soon: flow.candidates.filter((b) => ['hot', 'warn'].includes(ddayTone(b.deadline))).length,
  review: flow.candidates.filter((b) => b.unknown?.length || b.warnings?.length || b.recheck?.status === 'disqualified').length,
}))
const MAX_PICK = 20
const selectAll = () => { checked.value = flow.candidates.filter((b) => !b.notice_only).slice(0, MAX_PICK).map(keyOf) }
const clearAll = () => { checked.value = [] }
const allPicked = computed(() => {
  const want = Math.min(MAX_PICK, flow.candidates.filter((b) => !b.notice_only).length)
  return want > 0 && checked.value.length === want
})
// 행의 빈 곳을 눌러도 선택이 바뀌게 합니다. (링크·버튼·체크칸을 누른 경우는 제외)
function toggleRow(b, e) {
  if (e.target.closest('a, button, input, summary, label')) return
  const k = keyOf(b)
  checked.value = checked.value.includes(k) ? checked.value.filter((x) => x !== k) : [...checked.value, k]
}
// 공고문 준비가 끝나 요약으로 갈 수 있는 상태: 이때는 "요약 보러 가기"를 눈에 띄는 버튼으로 둡니다.
const ready = computed(() => !!noticeJob.value && flow.readyKeys.length > 0)
const preparing = ref(false) // 요청을 보내는 동안 true: 버튼을 누르는 즉시 막아 같은 요청이 여러 번 가지 않게 함
async function prepare() {
  if (preparing.value) return
  preparing.value = true // 가장 먼저 잠급니다. (await 앞에서 바로 잠가야 연타가 막힘)
  error.value = ''; noticeJob.value = null
  const bids = flow.candidates.filter((b) => checked.value.includes(keyOf(b))).slice(0, 20)
  if (!bids.length) { error.value = '공고를 한 건 이상 선택해 주세요.'; preparing.value = false; return }
  try {
    jobId.value = await fetchNotices(flow.searchId, bids)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    preparing.value = false
  }
}
const recheckError = ref('')
async function onDone(job) {
  noticeJob.value = job
  flow.readyKeys = job.bids.filter((b) => isOk(b.status)).map(keyOf)
  flow.resetFrom(4)
  // ③' 공고문이 적재됐으니 본문까지 보고 다시 확인 (부적격은 지우지 않고 표시만)
  recheckError.value = ''
  const done = flow.candidates.filter((b) => flow.readyKeys.includes(keyOf(b)))
  if (!done.length) return
  try {
    const rows = await recheckBids(flow.period.from, flow.period.to, flow.searchId, done)
    const byKey = Object.fromEntries(rows.map((r) => [keyOf(r), r.recheck]))
    flow.candidates = flow.candidates.map((b) => (byKey[keyOf(b)] ? { ...b, recheck: byKey[keyOf(b)] } : b))
  } catch (e) {
    recheckError.value = '재확인에 실패해 ②에서 추린 결과 그대로 표시합니다. (' + errorMessage(e) + ')'
  }
}
</script>

<template>
  <div class="layout">
  <div class="card">
    <h1>공고 검색</h1>
    <p class="sub">기간과 검색어로 나라장터 공고를 찾고, 우리 회사에 맞는 공고만 추립니다.</p>

    <div v-if="!formOpen" class="search-summary">
      <div class="ss-text">
        <strong>검색 조건</strong>
        <span>기간 {{ from }} ~ {{ to }}</span>
        <span>검색어 {{ queryList.join(', ') }}</span>
      </div>
      <button type="button" class="small" @click="formOpen = true">조건 바꿔 다시 검색</button>
    </div>

    <form v-show="formOpen" @submit.prevent="search">
      <div class="row">
        <div><label for="from">시작일</label><input id="from" v-model="from" type="date" /></div>
        <div><label for="to">종료일</label><input id="to" v-model="to" type="date" /></div>
      </div>
      <label for="q">검색어 <span class="hint">쉼표로 구분 · 예: 챗봇, 모바일 앱</span></label>
      <input id="q" v-model="queries" />
      <button class="primary" :disabled="loading">{{ loading ? '검색 중…' : '공고 검색' }}</button>
    </form>

    <div v-if="loading" class="search-progress" role="status" aria-live="polite">
      <div class="sp-head">
        <strong>공고를 찾는 중입니다</strong>
        <span class="sp-time">{{ elapsed }}초 경과</span>
      </div>
      <p class="sp-cond">기간 {{ from }} ~ {{ to }} · 검색어 {{ queryList.join(', ') }}</p>
      <ol class="sp-steps">
        <li v-for="(label, i) in STAGE_LABELS" :key="label" :class="{ done: stage > i + 1, now: stage === i + 1 }">
          <span class="sp-mark">{{ stage > i + 1 ? '✓' : i + 1 }}</span>
          <span>{{ label }}<template v-if="stage === i + 1">…</template></span>
        </li>
      </ol>
      <div class="sp-bar"><i :style="{ width: Math.round(pct) + '%' }"></i></div>
      <p class="sp-note">
        진행률은 단계 기준의 예상치예요.
        <template v-if="elapsed >= 20">서버가 잠들어 있으면 처음 한 번은 1분 가까이 걸릴 수 있어요.</template>
      </p>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="noProfile" class="notice">
      저장된 회사 프로필이 없습니다. <router-link to="/profile">프로필을 먼저 입력</router-link>해 주세요.
    </p>

    <template v-if="flow.candidates.length">
      <div ref="resultsTop" class="kpis">
        <div class="kpi"><span class="kpi-label">추린 공고</span><b class="kpi-num">{{ kpi.total }}<small>건</small></b></div>
        <div class="kpi hot"><span class="kpi-label">마감 임박 (7일 이내)</span><b class="kpi-num">{{ kpi.soon }}<small>건</small></b></div>
        <div class="kpi warn"><span class="kpi-label">확인 필요</span><b class="kpi-num">{{ kpi.review }}<small>건</small></b></div>
        <div class="kpi accent"><span class="kpi-label">내가 선택</span><b class="kpi-num">{{ checked.length }}<small>건</small></b></div>
      </div>
      <h2 style="font-size: 1.1rem; margin-top: 6px; scroll-margin-top: 16px">추린 공고 {{ flow.candidates.length }}건</h2>
      <p class="sub">공고문을 받아 요약할 공고를 고르세요. (최대 20건)</p>
      <div class="pick-bar">
        <span class="pick-count" :class="{ over: checked.length > 20 }">선택 {{ checked.length }}건<template v-if="checked.length > 20"> · 20건까지만 준비돼요</template></span>
      </div>
      <div class="table-wrap">
        <table class="bid-table">
          <thead>
            <tr>
              <th class="c-check"><input type="checkbox" aria-label="전체 선택" :checked="allPicked" @change="$event.target.checked ? selectAll() : clearAll()" /></th>
              <th>공고명</th>
              <th>발주기관</th>
              <th class="num">금액</th>
              <th>마감일</th>
              <th>구분</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in flow.candidates" :key="keyOf(b)" :class="{ on: checked.includes(keyOf(b)) }" @click="toggleRow(b, $event)">
              <td class="c-check"><input v-model="checked" type="checkbox" :value="keyOf(b)" :aria-label="b.title + ' 선택'" /></td>
              <td class="c-title">
                <strong>{{ b.title }}</strong>
                <span class="sub-line">{{ b.bid_no }}-{{ b.revision }}</span>
                <span v-if="b.reason" class="sub-line">추천 이유: {{ b.reason }}</span>
                <span v-if="b.unknown.length" class="chips">
                  <span v-for="u in b.unknown" :key="u" class="badge warn">미확인: {{ unknownLabel(u) }}</span>
                </span>
                <RecheckBadge :recheck="b.recheck" />
              </td>
              <td>{{ b.agency }}</td>
              <td class="num">{{ won(b.budget) }}</td>
              <td class="nowrap">
                <template v-if="dday(b.deadline) !== '미확인'">{{ ymd(b.deadline) }}<span class="dday" :class="ddayTone(b.deadline)">{{ dday(b.deadline) }}</span></template>
                <span v-else class="meta">기한 미확인</span>
              </td>
              <td class="nowrap"><span class="badge" :class="{ neutral: b.notice_only }">{{ b.notice_only ? '공고문만' : '선택 가능' }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>

      <details v-if="flow.excluded.length" style="margin-top: 14px">
        <summary style="cursor: pointer">조건에 맞지 않아 제외된 공고 {{ flow.excluded.length }}건</summary>
        <p v-for="e in flow.excluded" :key="e.bid_no + e.revision" class="meta">{{ e.bid_no }}-{{ e.revision }}: {{ (e.reasons || []).join(', ') }}</p>
      </details>

      <div class="action-bar">
        <span><strong>{{ checked.length }}건</strong> 선택됨<span class="meta"> · 한 번에 최대 20건</span></span>
        <router-link v-if="ready" to="/summaries" class="cta">요약 보러 가기 →</router-link>
        <button v-else class="primary" type="button" :disabled="preparing || (!!jobId && !noticeJob)" @click="prepare">
          {{ preparing ? '요청 중…' : `선택한 ${checked.length}건 공고문 준비` }}
        </button>
        <div v-if="jobId || noticeJob" class="action-status">
          <JobProgress v-if="jobId" :key="jobId" :job-id="jobId" label="공고문을 받는 중" @done="onDone" />
          <div v-if="noticeJob">
            <p v-if="flow.readyKeys.length" class="ok">공고문 {{ flow.readyKeys.length }}건 준비 완료.</p>
            <p v-if="recheckError" class="notice">{{ recheckError }}</p>
            <p v-if="flow.candidates.some((b) => b.recheck?.status === 'disqualified')" class="notice">
              공고문을 보니 부적격일 수 있는 공고가 있습니다. 위 목록의 이유를 확인해 주세요. (자동으로 지우지 않았습니다)
            </p>
            <p v-if="!flow.readyKeys.length" class="error">준비된 공고가 없습니다. 다른 공고를 선택해 다시 시도해 주세요.</p>
          </div>
          <button v-if="ready" class="small" type="button" :disabled="preparing" @click="prepare">
            {{ preparing ? '요청 중…' : `선택한 ${checked.length}건 공고문 다시 준비` }}
          </button>
        </div>
      </div>
    </template>

  </div>
  <Teleport defer to="#side-slot"><ProfileSummary :active="queryList" @loaded="onProfile" @pick="addKeyword" /></Teleport>
  </div>
</template>
