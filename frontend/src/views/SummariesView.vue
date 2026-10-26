<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useFlowStore } from '../stores/flow'
import { fetchSummaries, saveSummaries, fetchDocuments, saveSelections, SUMMARY_LABELS, isFailed, isOk } from '../api/flow'
import { errorMessage } from '../api/client'
import { keyOf, dday } from '../utils'
import RecheckBadge from '../components/RecheckBadge.vue'
import SourceList from '../components/SourceList.vue'
import JobProgress from '../components/JobProgress.vue'
import PdfLinks from '../components/PdfLinks.vue'

const flow = useFlowStore()
const loading = ref(false)
const error = ref('')
const checked = ref(flow.selected.map(keyOf))
const jobId = ref('')
const opened = reactive({}) // 펼친 카드만 원문 PDF 목록을 불러옵니다.
const docsJob = ref(null)
const saveNotice = ref('') // 요약을 내 계정(DB)에 저장한 결과 안내
const changedRevisions = ref([]) // 정정공고로 차수가 바뀐 공고번호

const meta = (r) => flow.candidates.find((b) => keyOf(b) === keyOf(r)) || {}
const failed = (r) => !!r.status && isFailed(r.status)

// 마감일 색: 3일 이내 빨강, 7일 이내 주황, 그 외 초록, 마감·미확인은 회색
const ddayTone = (deadline) => {
  const t = dday(deadline)
  if (t === '미확인') return 'na'
  if (t === '마감') return 'over'
  const n = t === 'D-day' ? 0 : Number(/^D-(\d+)$/.exec(t)?.[1])
  return n <= 3 ? 'hot' : n <= 7 ? 'warn' : 'ok'
}
// 위쪽 요약 숫자
const kpi = computed(() => ({
  done: flow.summaries.filter((r) => !failed(r)).length,
  soon: flow.summaries.filter((r) => ['hot', 'warn'].includes(ddayTone(meta(r).deadline))).length,
  review: flow.summaries.filter((r) => r.needs_review || r.handoff).length,
}))
// 전체 선택·해제 (요약에 실패한 공고는 제외)
const selectAll = () => { checked.value = flow.summaries.filter((r) => !failed(r)).map(keyOf) }
const clearAll = () => { checked.value = [] }

// ④ 화면이 열리면 공고문이 준비된 공고를 한 번에 요약 (동시 처리라 수십 초 걸릴 수 있음)
onMounted(async () => {
  if (flow.summaries.length || !flow.readyKeys.length) return
  loading.value = true
  try {
    const bids = flow.candidates.filter((b) => flow.readyKeys.includes(keyOf(b)))
    flow.summaries = await fetchSummaries(bids)
    // 요약 결과를 내 계정(DB)에 저장. 실패해도 화면 사용은 계속할 수 있습니다.
    const r = await saveSummaries(flow.summaries)
    if (r.total) saveNotice.value = r.failed ? `요약 ${r.total}건 중 ${r.failed}건은 저장하지 못했습니다. (화면에서는 계속 볼 수 있어요)` : `요약 ${r.total}건을 내 계정에 저장했습니다.`
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
})

// ⑤-2 제안요청서 준비가 끝나면: 정정공고로 바뀐 최신 차수를 반영하고, 실패한 공고는 제외합니다.
function onDocsDone(job) {
  docsJob.value = job
  changedRevisions.value = []
  flow.selected = flow.selected
    .filter((s) => {
      const j = job.bids.find((b) => b.bid_no === s.bid_no)
      return j && isOk(j.status) && j.rfp_ready === true
    })
    .map((s) => {
      const j = job.bids.find((b) => b.bid_no === s.bid_no)
      if (j && j.revision !== s.revision) { changedRevisions.value.push(s.bid_no); return { ...s, revision: j.revision } }
      return s
    })
}

// ⑤ 선택한 공고의 제안요청서 준비
const preparing = ref(false) // 요청을 보내는 동안 true: 연타해도 같은 요청이 한 번만 가게 막음
async function prepare() {
  if (preparing.value) return
  preparing.value = true // await 앞에서 가장 먼저 잠급니다.
  error.value = ''; docsJob.value = null
  const picked = flow.summaries.filter((r) => checked.value.includes(keyOf(r)))
  if (!picked.length) { error.value = '공고를 한 건 이상 선택해 주세요.'; preparing.value = false; return }
  try {
    flow.selected = picked.map((r) => ({
      bid_no: r.bid_no, revision: r.revision, title: meta(r).title || r.summary?.title?.value || r.bid_no,
    }))
    flow.approved = []
    await saveSelections(picked) // 내 계정(DB)에 선택 저장 (공고별 1건씩)
    jobId.value = await fetchDocuments(flow.searchId, picked)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    preparing.value = false
  }
}
</script>

<template>
  <div class="card">
    <h1>공고 요약</h1>
    <p class="sub">준비할 공고를 고르세요. 선택한 공고만 제안요청서를 받아 채점표를 만듭니다.</p>

    <p v-if="!flow.readyKeys.length" class="notice">
      준비된 공고문이 없습니다. <router-link to="/search">공고 검색</router-link>에서 먼저 공고문을 준비해 주세요.
    </p>
    <p v-if="loading" class="sub">요약을 만드는 중… (수십 초 걸릴 수 있어요)</p>
    <p v-if="saveNotice" :class="saveNotice.includes('못했') ? 'notice' : 'ok'">{{ saveNotice }}</p>
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="flow.summaries.length">
      <div class="kpis">
        <div class="kpi"><span class="kpi-label">요약 완료</span><b class="kpi-num">{{ kpi.done }}<small>건</small></b></div>
        <div class="kpi hot"><span class="kpi-label">마감 임박 (7일 이내)</span><b class="kpi-num">{{ kpi.soon }}<small>건</small></b></div>
        <div class="kpi warn"><span class="kpi-label">담당자 확인 필요</span><b class="kpi-num">{{ kpi.review }}<small>건</small></b></div>
        <div class="kpi accent"><span class="kpi-label">내가 선택</span><b class="kpi-num">{{ checked.length }}<small>건</small></b></div>
      </div>
      <div class="pick-bar">
        <span class="pick-count">준비할 공고를 고르세요</span>
        <span class="pick-actions">
          <button type="button" class="small" @click="selectAll">전체 선택</button>
          <button type="button" class="small" :disabled="!checked.length" @click="clearAll">전체 해제</button>
        </span>
      </div>
    </template>

    <div v-for="r in flow.summaries" :key="keyOf(r)" class="item">
      <label style="display: flex; gap: 8px; align-items: flex-start; margin: 0; cursor: pointer">
        <input v-model="checked" type="checkbox" :value="keyOf(r)" :disabled="failed(r)" style="width: auto; margin-top: 6px" />
        <span>
          <strong>{{ meta(r).title || r.summary?.title?.value || r.bid_no }}</strong>
          <span v-if="meta(r).deadline" class="dday" :class="ddayTone(meta(r).deadline)">{{ dday(meta(r).deadline) }}</span>
          <RecheckBadge :recheck="meta(r).recheck" />
          <span class="meta" style="display: block; font-weight: 400">{{ r.bid_no }}-{{ r.revision }} · {{ meta(r).agency }}</span>
        </span>
      </label>

      <p v-if="failed(r)" class="error">이 공고는 요약하지 못했습니다. {{ r.detail || r.error || '' }}</p>
      <details v-else @toggle="opened[keyOf(r)] = $event.target.open">
        <summary style="cursor: pointer; margin-top: 6px">요약 보기</summary>
        <div v-for="(label, k) in SUMMARY_LABELS" :key="k" class="kv">
          <template v-if="r.summary?.[k]">
            <strong>{{ label }}</strong>
            {{ r.summary[k].value }}
            <SourceList :sources="r.summary[k].source_refs || (r.summary[k].source ? [r.summary[k].source] : [])" />
          </template>
          <template v-else-if="r.missing?.includes(k)">
            <strong>{{ label }}</strong><span class="meta">문서에서 찾지 못했습니다.</span>
          </template>
        </div>
        <span v-if="r.needs_review" class="badge warn">담당자 확인 필요</span>
        <p v-if="r.handoff" class="notice">일부 내용은 문서에 없습니다. 발주기관에 문의해 주세요.</p>
        <PdfLinks v-if="opened[keyOf(r)]" :bid="r" />
        <router-link :to="{ path: '/qa', query: { bid: r.bid_no, rev: r.revision } }" class="back">이 공고에 질문하기</router-link>
      </details>
    </div>

    <div v-if="flow.summaries.length" class="action-bar">
      <span><strong>{{ checked.length }}건</strong> 선택됨<span class="meta"> · 선택한 공고만 채점표를 만들어요</span></span>
      <button class="primary" type="button" :disabled="preparing || (!!jobId && !docsJob)" @click="prepare">
        {{ preparing ? '요청 중…' : `선택한 ${checked.length}건 제안요청서 준비` }}
      </button>
    </div>
    <JobProgress v-if="jobId" :key="jobId" :job-id="jobId" label="제안요청서를 받는 중" @done="onDocsDone" />
    <p v-if="changedRevisions.length" class="notice">정정공고로 차수가 바뀐 공고가 있어 최신 차수로 바꿨습니다: {{ changedRevisions.join(', ') }}</p>
    <router-link v-if="docsJob && flow.selected.length" to="/review" class="back">채점표 보러 가기 →</router-link>
    <p v-else-if="docsJob" class="error">제안요청서를 준비한 공고가 없습니다. 다시 시도해 주세요.</p>
  </div>
</template>
