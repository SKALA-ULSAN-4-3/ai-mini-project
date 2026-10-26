<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getJob, isFinished } from '../api/flow'
import { errorMessage } from '../api/client'

// 오래 걸리는 작업의 진행률을 1.5초마다 물어봐서(폴링) 보여주는 부품
const props = defineProps({ jobId: String, label: { type: String, default: '준비 중' } })
const emit = defineEmits(['done'])

const job = ref({ status: 'running', done: 0, total: 0, bids: [] })
const error = ref('')
const stages = { queued: '작업 대기', running: '처리 중', checking_attachments: '최신 첨부 목록 확인',
  waiting_document: '기존 문서 작업 대기', restoring_database: 'DB 자료 복원', saving_database: 'DB 저장',
  waiting_for_notice_job: '기존 공고문 준비 결과 대기', waiting_index: '전처리 완료 · 인덱스 저장 대기',
  downloading: '첨부파일 다운로드', converting: '문서 변환·텍스트 추출', indexing: '검색 인덱스 적재',
  completed: '완료', partial_failed: '일부 실패', failed: '실패' }
// 진행 중에는 "지금 처리 중인 공고 1건"만 보여 줍니다. (20건이어도 화면을 덮지 않게)
const running = computed(() => !isFinished(job.value.status))
const current = computed(() => {
  const bids = job.value.bids || []
  return bids.find((b) => !isFinished(b.status) && !['queued', 'waiting_index'].includes(b.status))
    || bids.find((b) => b.status === 'waiting_index') || bids.find((b) => b.status === 'queued')
})
const failedBids = computed(() => (job.value.bids || []).filter((b) => ['failed', 'partial_failed'].includes(b.status)))
const processedCount = computed(() => job.value.processed_count ?? job.value.done ?? 0)
const preparedCount = computed(() => job.value.prepared_count ?? 0)
const indexedCount = computed(() => job.value.indexed_count ?? 0)
const pct = computed(() => Math.round((processedCount.value / (job.value.total || 1)) * 100))
let timer = null

async function poll() {
  try {
    job.value = await getJob(props.jobId)
    if (isFinished(job.value.status)) {
      clearInterval(timer)
      emit('done', job.value)
    }
  } catch (e) {
    clearInterval(timer)
    error.value = errorMessage(e)
  }
}
onMounted(() => { poll(); timer = setInterval(poll, 1500) })
onUnmounted(() => clearInterval(timer)) // 화면을 떠나면 물어보기를 멈춤
</script>

<template>
  <div class="job-progress">
    <div class="jp-head">
      <strong>{{ label }}</strong>
      <span class="jp-count">문서 처리 {{ processedCount }} / {{ job.total }}건 · {{ running ? pct + '%' : '끝' }}</span>
    </div>
    <progress :value="processedCount" :max="job.total || 1" aria-label="문서 처리 진행률"></progress>
    <p class="jp-now">전처리 완료 {{ preparedCount }}건 · 인덱스 반영 {{ indexedCount }}건 · 처리 종료 {{ job.done }}건</p>
    <p v-if="running && job.waiting_index_count" class="jp-now">
      {{ job.waiting_index_count }}건은 전처리를 마쳤습니다. 남은 공고의 문서 처리 후 인덱스를 한 번에 저장합니다.
    </p>
    <p v-if="running && job.index_batch?.status === 'running'" class="jp-now">준비된 문서를 검색 인덱스에 저장하는 중입니다.</p>
    <p v-if="running && current" class="jp-now">지금: {{ current.bid_no }} · {{ stages[current.status] || current.status }}</p>
    <p v-else-if="running" class="jp-now">{{ stages[job.status] || '처리 중' }}</p>
    <p v-if="!running && failedBids.length" class="error">실패 {{ failedBids.length }}건: {{ failedBids[0].bid_no }} {{ failedBids[0].error || '실패했습니다.' }}<span v-if="failedBids.length > 1"> 외 {{ failedBids.length - 1 }}건</span></p>
    <details v-if="job.bids?.length" class="jp-detail">
      <summary>공고별 처리 상태 {{ job.bids.length }}건 보기</summary>
      <details v-for="bid in job.bids" :key="bid.bid_no + '-' + bid.revision">
        <summary>{{ bid.bid_no }} · {{ stages[bid.status] || bid.status }}</summary>
        <p>생성 청크 {{ bid.generated_chunks ?? bid.indexed_chunks ?? 0 }}개 · 인덱스 반영 {{ bid.indexed_chunks || 0 }}개</p>
        <p v-for="file in bid.files || []" :key="file.url">
          {{ file.file_name }} · 생성 {{ file.generated_chunks ?? file.indexed_chunks ?? 0 }}개 · 반영 {{ file.indexed_chunks || 0 }}개
        </p>
      </details>
      <p v-for="b in failedBids" :key="'f' + b.bid_no" class="error">{{ b.bid_no }}: {{ b.error || '실패했습니다.' }}</p>
    </details>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="job.error" class="error">{{ job.error }}</p>
  </div>
</template>
