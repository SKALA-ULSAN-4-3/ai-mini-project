<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useFlowStore } from '../stores/flow'
import { fetchSummaries, saveSelections, fetchDocuments, SUMMARY_LABELS, isFailed, isOk } from '../api/flow'
import { errorMessage } from '../api/client'
import { keyOf } from '../utils'
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
const changedRevisions = ref([]) // 정정공고로 차수가 바뀐 공고번호

const meta = (r) => flow.candidates.find((b) => keyOf(b) === keyOf(r)) || {}
const failed = (r) => !!r.status && isFailed(r.status)

// ④ 화면이 열리면 공고문이 준비된 공고를 한 번에 요약 (동시 처리라 수십 초 걸릴 수 있음)
onMounted(async () => {
  if (flow.summaries.length || !flow.readyKeys.length) return
  loading.value = true
  try {
    const bids = flow.candidates.filter((b) => flow.readyKeys.includes(keyOf(b)))
    flow.summaries = await fetchSummaries(bids)
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
      return !j || isOk(j.status)
    })
    .map((s) => {
      const j = job.bids.find((b) => b.bid_no === s.bid_no)
      if (j && j.revision !== s.revision) { changedRevisions.value.push(s.bid_no); return { ...s, revision: j.revision } }
      return s
    })
}

// ⑤ 선택한 공고의 제안요청서 준비
async function prepare() {
  error.value = ''; docsJob.value = null
  const picked = flow.summaries.filter((r) => checked.value.includes(keyOf(r)))
  if (!picked.length) { error.value = '공고를 한 건 이상 선택해 주세요.'; return }
  try {
    await saveSelections(flow.searchId, picked)
    flow.selected = picked.map((r) => ({
      bid_no: r.bid_no, revision: r.revision, title: meta(r).title || r.summary?.title?.value || r.bid_no,
    }))
    flow.approved = []
    jobId.value = await fetchDocuments(flow.searchId, picked)
  } catch (e) {
    error.value = errorMessage(e)
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
    <p v-if="error" class="error">{{ error }}</p>

    <div v-for="r in flow.summaries" :key="keyOf(r)" class="item">
      <label style="display: flex; gap: 8px; align-items: flex-start; margin: 0; cursor: pointer">
        <input v-model="checked" type="checkbox" :value="keyOf(r)" :disabled="failed(r)" style="width: auto; margin-top: 6px" />
        <span>
          <strong>{{ meta(r).title || r.summary?.title?.value || r.bid_no }}</strong>
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

    <button v-if="flow.summaries.length" class="primary" type="button" :disabled="!!jobId && !docsJob" @click="prepare">
      선택한 {{ checked.length }}건 제안요청서 준비
    </button>
    <JobProgress v-if="jobId" :key="jobId" :job-id="jobId" label="제안요청서를 받는 중" @done="onDocsDone" />
    <p v-if="changedRevisions.length" class="notice">정정공고로 차수가 바뀐 공고가 있어 최신 차수로 바꿨습니다: {{ changedRevisions.join(', ') }}</p>
    <router-link v-if="docsJob && flow.selected.length" to="/review" class="back">채점표 보러 가기 →</router-link>
    <p v-else-if="docsJob" class="error">제안요청서를 준비한 공고가 없습니다. 다시 시도해 주세요.</p>
  </div>
</template>
