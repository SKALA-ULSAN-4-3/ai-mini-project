<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getJob, isFinished } from '../api/flow'
import { errorMessage } from '../api/client'

// 직전 조회가 끝난 뒤 다음 조회를 예약해 느린 서버에 요청이 겹치지 않게 한다.
const props = defineProps({ jobId: String, label: { type: String, default: '준비 중' } })
const emit = defineEmits(['done'])
const job = ref({ status: 'running', done: 0, total: 0, bids: [] })
const error = ref('')
const checking = ref(false)
const slow = ref(false)
const stages = { queued: '작업 대기', running: '처리 중', checking_attachments: '최신 첨부 목록 확인',
  downloading: '첨부파일 다운로드', converting: '문서 변환·텍스트 추출', indexing: '검색 인덱스 적재',
  completed: '완료', partial_failed: '일부 실패', failed: '실패' }
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
    if (isFinished(next.status)) emit('done', next)
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
  <div class="notice">
    <p style="margin: 0 0 6px">{{ label }}… {{ job.done }} / {{ job.total }}건</p>
    <progress :value="job.done" :max="job.total || 1"></progress>
    <template v-if="job.mode === 'documents' && isFinished(job.status)">
      <p v-for="b in job.bids" :key="b.bid_no">
        {{ b.bid_no }}:
        {{ b.download_complete === true ? '첨부 다운로드 완료' : b.download_complete === false ? '첨부 다운로드 미완료' : '첨부 다운로드 상태 미확인' }}
        · {{ b.rfp_ready === true ? '제안요청서 준비 완료' : '제안요청서 미준비' }}
        <a v-if="b.rfp_ready !== true && b.detail_url" :href="b.detail_url" target="_blank" rel="noopener noreferrer">공고 상세에서 첨부 확인</a>
      </p>
    </template>
    <p v-for="b in job.bids.filter((x) => ['failed', 'partial_failed'].includes(x.status))" :key="b.bid_no" class="error">
      {{ b.bid_no }}: {{ b.error || '실패했습니다.' }}
    </p>
    <p v-if="!isFinished(job.status)" v-for="b in job.bids" :key="b.bid_no" class="meta">
      {{ b.bid_no }}: {{ stages[b.status] || b.status }}
    </p>
    <p v-if="slow && !isFinished(job.status)" class="notice">같은 단계에서 2분 이상 처리 중입니다. 아래 단계와 작업번호를 확인해 주세요. 아직 실패로 확정된 것은 아닙니다.</p>
    <p v-if="job.error" class="error">{{ job.error }}</p>
    <p v-if="error" class="error">진행 상태를 확인하지 못했습니다. {{ error }} 서버 작업이 취소된 것은 아닙니다.</p>
    <button v-if="error" type="button" :disabled="checking" @click="poll">진행 상태 다시 확인</button>
    <small>작업번호: {{ jobId }}</small>
  </div>
</template>
