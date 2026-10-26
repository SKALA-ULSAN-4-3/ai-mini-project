<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getJob, isFinished, fetchJobFiles, downloadJobFile } from '../api/flow'
import { errorMessage } from '../api/client'

// 직전 조회가 끝난 뒤 다음 조회를 예약해 느린 서버에 요청이 겹치지 않게 한다.
const props = defineProps({ jobId: String, label: { type: String, default: '준비 중' } })
const emit = defineEmits(['done', 'retry-db'])
const job = ref({ status: 'running', done: 0, total: 0, bids: [] })
const error = ref('')
const checking = ref(false)
const slow = ref(false)
const files = ref([])
const fileError = ref('')
async function download(file) {
  try { await downloadJobFile(props.jobId, file) }
  catch (e) { fileError.value = errorMessage(e) }
}
const displayLabel = computed(() => job.value.mode === 'db_retry' ? 'DB 저장만 다시 시도하는 중' : props.label)
const stages = { restoring_database: 'DB 저장 자료 확인·복원', saving_database: 'DB 파일 저장', checking_bid_progress: '선택 공고의 개찰·재입찰 상태 확인', waiting_document: '같은 공고의 문서 준비 완료 대기', queued: '작업 대기', running: '처리 중', checking_attachments: '최신 첨부 목록 확인',
  downloading: '첨부파일 다운로드', converting: '문서 변환·텍스트 추출', indexing: '검색 인덱스 적재',
  completed: '완료', partial_failed: '일부 실패', failed: '실패' }
// 진행 중에는 "지금 처리 중인 공고 1건"만 보여 줍니다. (20건이어도 화면을 덮지 않게)
const running = computed(() => !isFinished(job.value.status))
const current = computed(() => (job.value.bids || []).find((b) => !isFinished(b.status)))
const failedBids = computed(() => (job.value.bids || []).filter((b) => ['failed', 'partial_failed'].includes(b.status)))
const pct = computed(() => Math.round(((job.value.done || 0) / (job.value.total || 1)) * 100))
const preparedCount = computed(() => (job.value.bids || []).filter((b) => b.preparation_status === 'ready').length)
const dbSavedCount = computed(() => (job.value.bids || []).filter((b) => ['saved', 'reused'].includes(b.db_sync?.status)).length)
const dbFailedBids = computed(() => (job.value.bids || []).filter((b) => b.preparation_status === 'ready'
  && ['failed', 'not_configured'].includes(b.db_sync?.status)))
let timer = null
let stopped = false
let lastState = ''
let lastChange = Date.now()

async function poll() {
  if (stopped || checking.value) return
  clearTimeout(timer)
  checking.value = true
  error.value = ''
  try {
    const next = await getJob(props.jobId)
    if (stopped) return
    job.value = next
    const state = JSON.stringify([next.status, next.done, next.bids.map((b) => [b.bid_no, b.status])])
    if (state !== lastState) { lastState = state; lastChange = Date.now() }
    slow.value = Date.now() - lastChange >= 120000
    if (isFinished(next.status)) {
      emit('done', next)
      if (next.mode === 'documents') {
        try { files.value = await fetchJobFiles(props.jobId) }
        catch (e) { fileError.value = errorMessage(e) }
      }
    }
    else timer = setTimeout(poll, 1500)
  } catch (e) {
    if (!stopped) error.value = errorMessage(e)
  } finally {
    checking.value = false
  }
}
onMounted(poll)
onUnmounted(() => { stopped = true; clearTimeout(timer) })
</script>

<template>
  <div class="job-progress">
    <div class="jp-head">
      <strong>{{ displayLabel }}</strong>
      <span class="jp-count">{{ job.done }} / {{ job.total }}건 · {{ running ? pct + '%' : '끝' }}</span>
    </div>
    <progress :value="job.done" :max="job.total || 1"></progress>
    <p v-if="running && current" class="jp-now">지금: {{ current.bid_no }} · {{ stages[current.status] || current.status }}</p>
    <p v-else-if="running" class="jp-now">{{ stages[job.status] || '처리 중' }}</p>
    <p v-if="!running && failedBids.length" class="error">실패 {{ failedBids.length }}건: {{ failedBids[0].bid_no }} {{ failedBids[0].error || '실패했습니다.' }}<span v-if="failedBids.length > 1"> 외 {{ failedBids.length - 1 }}건</span></p>
    <details v-if="!running && job.bids?.length" class="jp-detail">
      <summary>공고별 결과 {{ job.bids.length }}건 보기</summary>
      <template v-if="job.mode === 'documents'">
        <p v-for="b in job.bids" :key="b.bid_no" class="meta">
          {{ b.bid_no }}:
          {{ b.download_complete === true ? '첨부 다운로드 완료' : b.download_complete === false ? '첨부 다운로드 미완료' : '첨부 다운로드 상태 미확인' }}
          · {{ b.rfp_ready === true ? '제안요청서 준비 완료' : '제안요청서 미준비' }}
          <a v-if="b.rfp_ready !== true && b.detail_url" :href="b.detail_url" target="_blank" rel="noopener noreferrer">공고 상세에서 첨부 확인</a>
        </p>
      </template>
      <p v-for="b in job.bids.filter((row) => row.progress_check)" :key="'progress-' + b.bid_no" class="meta">
        {{ b.bid_no }} 진행 상태: {{ b.progress_check.label }}<span v-if="b.progress_check.reason"> · {{ b.progress_check.reason }}</span>
        <span v-if="b.progress_check.deadline"> · 확인된 마감 {{ b.progress_check.deadline }}</span>
      </p>
      <p v-for="b in failedBids" :key="'f' + b.bid_no" class="error">{{ b.bid_no }}: {{ b.error || '실패했습니다.' }}</p>
      <template v-for="bid in job.bids" :key="'conversion-' + bid.bid_no">
        <p v-for="file in bid.conversion_progress || []" :key="file.file_name" class="meta">
          {{ file.file_name }} · {{ file.status === 'retrying' ? '시간 초과 후 재시도' : file.status === 'converted' || file.status === 'existing' ? '변환 완료' : file.status === 'converting' ? '변환 중' : '확인 필요' }}
          <span v-if="file.attempt">({{ file.attempt }}/{{ file.max_attempts }}회 · 시도당 {{ file.timeout_seconds }}초)</span>
        </p>
      </template>
      <p v-for="bid in job.bids" :key="'db-' + bid.bid_no" :class="['failed', 'not_configured'].includes(bid.db_sync?.status) ? 'error' : 'meta'">
        {{ bid.bid_no }} DB 저장: {{ bid.db_sync?.status === 'not_configured' ? '설정 없음 — 로컬 저장만 완료' : bid.db_sync?.status === 'failed' ? '일부 미완료 — 파일별 오류 확인 필요' : bid.db_sync?.status === 'saved' ? '저장·재사용 완료' : '저장 상태 미확인' }}
        <span v-if="bid.db_sync?.auth_failed"> · 파이프라인 SERVICE_API_KEY와 Java SERVICE_API_KEY 설정을 확인하세요.</span>
      </p>
      <p v-for="bid in job.bids.filter((row) => row.rfp_cache?.status && !['not_requested', 'reused', 'saved', 'miss', 'not_configured'].includes(row.rfp_cache.status))" :key="'rfp-cache-' + bid.bid_no" class="error">
        {{ bid.bid_no }} 제안요청서 캐시: {{ bid.rfp_cache.error || bid.rfp_cache.reason || '저장·조회 실패' }}
      </p>
      <p v-for="bid in job.bids.filter((row) => ['reused', 'saved'].includes(row.rfp_cache?.status))" :key="'rfp-cache-ok-' + bid.bid_no" class="meta">
        {{ bid.bid_no }} 제안요청서 처리 결과 DB {{ bid.rfp_cache.status === 'reused' ? '캐시 재사용' : '저장 완료' }}
      </p>
      <template v-for="bid in job.bids" :key="'db-files-' + bid.bid_no">
        <p v-for="file in (bid.db_sync?.files || []).filter((row) => row.status === 'failed')" :key="file.kind + file.file_name" class="error">DB 미저장: {{ file.file_name }} ({{ file.kind === 'converted' ? '변환본' : '원본' }})</p>
      </template>
      <template v-for="bid in job.bids" :key="'db-errors-' + bid.bid_no">
        <p v-for="(message, index) in bid.db_sync?.errors || []" :key="index" class="error">{{ bid.bid_no }} DB 오류: {{ message }}</p>
      </template>
    </details>
    <div v-if="!running && ['notices', 'documents', 'db_retry'].includes(job.mode)" class="jp-detail">
      <p>공고문 준비 완료 {{ preparedCount }}건 · DB 저장 성공 {{ dbSavedCount }}건 · DB 저장 실패 {{ dbFailedBids.length }}건</p>
      <button v-if="dbFailedBids.length" type="button" class="small" @click="emit('retry-db', job)">DB 저장만 다시 시도</button>
    </div>
    <p v-if="slow && running" class="notice">같은 단계에서 2분 이상 처리 중입니다. 서버가 느리거나 멈췄을 수 있습니다. 아직 실패로 확정된 것은 아닙니다.</p>
    <p v-if="job.error" class="error">{{ job.error }}</p>
    <p v-if="error" class="error">진행 상태를 확인하지 못했습니다. {{ error }} 서버 작업이 취소된 것은 아닙니다.</p>
    <button v-if="error" type="button" class="small" :disabled="checking" @click="poll">진행 상태 다시 확인</button>
    <details v-if="files.length" class="jp-detail">
      <summary>선택한 공고의 원본·변환 파일 {{ files.length }}건</summary>
      <p v-for="file in files" :key="file.file_id" class="meta">
        {{ file.file_name }} · {{ file.kind === 'converted' ? '변환 PDF' : '원본' }}
        <button type="button" class="small" @click="download(file)">다운로드</button>
      </p>
    </details>
    <p v-if="fileError" class="error">{{ fileError }}</p>
    <small class="jp-id">작업번호: {{ jobId }}</small>
  </div>
</template>
