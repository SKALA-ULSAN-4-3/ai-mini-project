<script setup>
import { ref, computed } from 'vue'
import { useFlowStore } from '../stores/flow'
import { searchBids, fetchCandidates, fetchNotices, recheckBids, isOk } from '../api/flow'
import { errorMessage } from '../api/client'
import { addDays, iso, won, dday, keyOf, ymd, unknownLabel } from '../utils'
import JobProgress from '../components/JobProgress.vue'
import ProfileSummary from '../components/ProfileSummary.vue'
import RecheckBadge from '../components/RecheckBadge.vue'

const flow = useFlowStore()

// ① 검색 조건
const today = iso(new Date())
const to = ref(flow.period?.to >= today ? flow.period.to : iso(addDays(new Date(), 30)))
const from = ref(flow.period?.from <= today ? flow.period.from : today)
const queries = ref(flow.period?.queries || '')
const queryList = computed(() => queries.value.split(',').map((s) => s.trim()).filter(Boolean))
const loading = ref(false)
const error = ref('')
const searchNotice = ref('')
const noProfile = ref(false)
const searchFinished = ref(false)
const searchCount = ref(0)
const progressExcluded = ref([])

// ② 추린 공고 중 공고문을 받을 공고 (최대 20건)
const checked = ref(flow.candidates.filter((b) => !b.notice_only).slice(0, 20).map(keyOf))
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

async function search() {
  error.value = ''; noProfile.value = false
  searchNotice.value = ''
  const list = queries.value.split(',').map((s) => s.trim()).filter(Boolean)
  if (!list.length) { error.value = '검색어를 한 개 이상 입력해 주세요.'; return }
  if (from.value > to.value) { error.value = '시작일이 종료일보다 늦을 수 없습니다.'; return }
  if (from.value > today) { error.value = '게시 시작일은 오늘 이전 또는 오늘이어야 합니다.'; return }
  if (to.value < today) { error.value = '마감 종료일은 오늘 이후 또는 오늘이어야 합니다.'; return }
  loading.value = true
  searchFinished.value = false
  progressExcluded.value = []
  jobId.value = ''; noticeJob.value = null
  try {
    // ① 나라장터 검색 (1번 API)
    const d = await searchBids({ from: from.value, to: to.value, queries: list, limit: 100 })
    searchCount.value = (d.items || []).length
    progressExcluded.value = d.progress_excluded || []
    if (d.page_limit_reached) {
      searchNotice.value = '조회 한도에 도달해 일부 공고가 누락될 수 있습니다. 검색어를 더 구체적으로 입력해 주세요.'
    }
    flow.resetFrom(3)
    flow.searchId = d.search_id
    flow.period = { from: from.value, to: to.value, queries: queries.value,
      deadline_from: d.deadline_from || from.value, deadline_to: d.deadline_to || to.value }
    // ② 회사 프로필에 맞게 추리기 (3번 API). 여기서 404 는 "저장된 프로필이 없음"입니다.
    try {
      const r = await fetchCandidates(flow.period.deadline_from, flow.period.deadline_to, d.search_id)
      flow.candidates = r.bids
      flow.excluded = r.excluded
      searchFinished.value = true
      checked.value = flow.candidates.filter((b) => !b.notice_only).slice(0, 20).map(keyOf)
    } catch (e) {
      if (e.response?.status === 404) noProfile.value = true
      else throw e
    }
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

// ③ 공고문 준비 시작
async function prepare() {
  error.value = ''; noticeJob.value = null
  const bids = flow.candidates.filter((b) => checked.value.includes(keyOf(b))).slice(0, 20)
  if (!bids.length) { error.value = '공고를 한 건 이상 선택해 주세요.'; return }
  try {
    jobId.value = await fetchNotices(flow.searchId, bids)
  } catch (e) {
    error.value = errorMessage(e)
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
    const rows = await recheckBids(flow.period.deadline_from || flow.period.from,
      flow.period.deadline_to || flow.period.to, flow.searchId, done)
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
    <p class="sub">게시 시작일부터 오늘까지 게시된 공고 중, 마감일이 오늘~마감 종료일에 포함되는 공고를 검색합니다. 공고문만 있는 공고는 추천 순위를 낮추고 기본 선택에서 제외합니다.</p>

    <form @submit.prevent="search">
      <div class="row">
        <div><label for="from">게시 시작일</label><input id="from" v-model="from" type="date" :max="today" /></div>
        <div><label for="to">마감 종료일</label><input id="to" v-model="to" type="date" :min="today" /></div>
      </div>
      <label for="q">검색어 <span class="hint">쉼표로 구분 · 예: 챗봇, 모바일 앱</span></label>
      <input id="q" v-model="queries" />
      <button class="primary" :disabled="loading">{{ loading ? '검색 중…' : '공고 검색' }}</button>
    </form>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="searchNotice" class="notice">{{ searchNotice }}</p>
    <p v-if="searchFinished && !loading && !flow.candidates.length" class="notice" role="status">
      {{ searchCount ? `검색된 공고 ${searchCount}건이 회사 조건에 맞지 않아 추천 공고가 없습니다. 아래 제외 사유를 확인해 주세요.` : '선택한 게시기간·마감기간·검색어에 맞는 추천 공고가 없습니다. 아래 진행 상태 확인 결과를 확인하거나 검색 조건을 조정해 주세요.' }}
    </p>
    <details v-if="!loading && progressExcluded.length" style="margin-top: 14px">
      <summary>입찰 진행 상태로 제외된 공고 {{ progressExcluded.length }}건</summary>
      <p v-for="b in progressExcluded" :key="b.bid_no + b.bid_order" class="meta">{{ b.bid_no }}: {{ b.label }} · {{ b.reason }}</p>
    </details>
    <details v-if="searchFinished && !loading && flow.excluded.length" style="margin-top: 14px">
      <summary>회사 조건에 맞지 않아 제외된 공고 {{ flow.excluded.length }}건</summary>
      <p v-for="e in flow.excluded" :key="e.bid_no + e.revision" class="meta">{{ e.bid_no }}-{{ e.revision }}: {{ (e.reasons || []).join(', ') }}</p>
    </details>
    <p v-if="noProfile" class="notice">
      저장된 회사 프로필이 없습니다. <router-link to="/profile">프로필을 먼저 입력</router-link>해 주세요.
    </p>

    <template v-if="flow.candidates.length">
      <h2 style="font-size: 1.1rem; margin-top: 26px">추린 공고 {{ flow.candidates.length }}건</h2>
      <p class="sub">공고문을 받아 요약할 공고를 고르세요. (최대 20건)</p>
      <label v-for="b in flow.candidates" :key="keyOf(b)" class="item" style="cursor: pointer">
        <input v-model="checked" type="checkbox" :value="keyOf(b)" style="width: auto; margin-right: 8px" />
        <strong>{{ b.title }}</strong>
        <p class="meta">{{ b.agency }} · {{ won(b.budget) }} · <span v-if="dday(b.deadline) !== '미확인'">마감 {{ ymd(b.deadline) }} ({{ dday(b.deadline) }})</span><span v-else>기한 미확인</span></p>
        <p v-for="warning in b.warnings" :key="warning" class="notice">{{ warning }}</p>
        <p v-if="b.region_restriction" class="meta">{{ b.region_restriction.summary }}</p>
        <p v-if="b.industry_restriction" class="meta">{{ b.industry_restriction.summary }}</p>
        <p v-if="b.industry_restriction?.note" class="meta">{{ b.industry_restriction.note }}</p>
        <p v-if="b.unknown.length" class="chips">
          <span v-for="u in b.unknown" :key="u" class="badge warn">미확인: {{ unknownLabel(u) }}</span>
        </p>
        <p v-if="b.reason" class="meta">추천 이유: {{ b.reason }}</p>
        <RecheckBadge :recheck="b.recheck" />
      </label>

      <button class="primary" type="button" :disabled="!!jobId && !noticeJob" @click="prepare">
        선택한 {{ checked.length }}건 공고문 준비
      </button>
    </template>

    <JobProgress v-if="jobId" :key="jobId" :job-id="jobId" label="공고문을 받는 중" @done="onDone" />
    <div v-if="noticeJob">
      <p v-if="flow.readyKeys.length" class="ok">공고문 {{ flow.readyKeys.length }}건 준비 완료.</p>
      <p v-if="recheckError" class="notice">{{ recheckError }}</p>
      <p v-if="flow.candidates.some((b) => b.recheck?.status === 'disqualified')" class="notice">
        공고문을 보니 부적격일 수 있는 공고가 있습니다. 위 목록의 이유를 확인해 주세요. (자동으로 지우지 않았습니다)
      </p>
      <router-link v-if="flow.readyKeys.length" to="/summaries" class="back">요약 보러 가기 →</router-link>
      <p v-else class="error">준비된 공고가 없습니다. 다른 공고를 선택해 다시 시도해 주세요.</p>
    </div>
  </div>
  <ProfileSummary :active="queryList" @loaded="onProfile" @pick="addKeyword" />
  </div>
</template>
