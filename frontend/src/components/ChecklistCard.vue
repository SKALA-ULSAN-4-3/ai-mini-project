<script setup>
import { ref, onMounted } from 'vue'
import { fetchChecklist } from '../api/flow'
import { errorMessage } from '../api/client'
import { ddayText, ymd } from '../utils'
import SourceList from './SourceList.vue'

// ⑨ 승인한 공고 한 건의 제출서류 · 일정 (3번 /checklist: documents · schedule)
const props = defineProps({ bid: Object })
const data = ref({ documents: [], schedule: [], needs_review: false, quality_warnings: [] })
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    data.value = await fetchChecklist(props.bid)
  } catch (e) {
    error.value = errorMessage(e, { 404: '이 공고의 제출서류 정보를 찾을 수 없습니다.' })
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div>
    <p v-if="loading" class="sub">불러오는 중…</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="data.needs_review" class="notice">일부 항목은 담당자 확인이 필요합니다. (보유 서류 미입력, 마감일 미확인 등)</p>

    <p v-for="w in data.quality_warnings || []" :key="w" class="notice">원문 대조 경고: {{ w }}</p>

    <div v-for="c in data.documents" :key="c.id" style="margin: 8px 0">
      <span>{{ c.owned === true ? '✔' : '☐' }} {{ c.doc }}</span>
      <span v-if="c.owned === true" class="badge" style="margin-left: 8px">보유</span>
      <span v-else-if="c.owned === null" class="badge warn" style="margin-left: 8px">보유 여부 미확인</span>
      <span v-if="c.needs_review" class="badge warn" style="margin-left: 8px">담당자 확인 필요</span>
      <p class="meta">
        제출 기한 {{ ymd(c.due) }} ({{ ddayText(c.d_day) }})
        <span v-if="c.notes?.length"> · {{ c.notes.join(' · ') }}</span>
      </p>
      <SourceList :sources="c.sources || []" />
    </div>

    <strong v-if="data.schedule.length" style="display: block; margin-top: 14px">일정</strong>
    <p v-for="s in data.schedule" :key="s.id" style="margin: 6px 0">
      {{ s.event }} · {{ ymd(s.due) }} <span class="badge">{{ ddayText(s.d_day) }}</span>
      <span v-if="s.needs_review" class="badge warn">담당자 확인 필요</span>
      <span v-if="s.notes?.length" class="meta"> {{ s.notes.join(' · ') }}</span>
    </p>
  </div>
</template>
