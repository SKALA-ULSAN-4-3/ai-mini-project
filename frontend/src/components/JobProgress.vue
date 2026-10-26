<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getJob, isFinished } from '../api/flow'
import { errorMessage } from '../api/client'

// 오래 걸리는 작업의 진행률을 1.5초마다 물어봐서(폴링) 보여주는 부품
const props = defineProps({ jobId: String, label: { type: String, default: '준비 중' } })
const emit = defineEmits(['done'])

const job = ref({ status: 'running', done: 0, total: 0, bids: [] })
const error = ref('')
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
    <p v-if="error" class="error">{{ error }}</p>
  </div>
</template>
