<script setup>
import { ref } from 'vue'
import { useFlowStore } from '../stores/flow'
import { saveApprovals } from '../api/flow'
import { errorMessage } from '../api/client'
import { keyOf } from '../utils'
import ReviewCard from '../components/ReviewCard.vue'
import ChecklistCard from '../components/ChecklistCard.vue'

const flow = useFlowStore()
const picked = ref(flow.approved.map(keyOf))
const error = ref('')
const saving = ref(false)

// ⑧ 승인 (여러 건 가능). AI는 추천만 하고 결정은 사람이 합니다.
async function approve() {
  error.value = ''
  const bids = flow.selected.filter((b) => picked.value.includes(keyOf(b)))
  if (!bids.length) { error.value = '승인할 공고를 한 건 이상 선택해 주세요.'; return }
  saving.value = true
  try {
    await saveApprovals(bids)
    flow.approved = bids
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="card">
    <h1>채점표 검토 · 승인</h1>
    <p class="sub">예상 점수를 확인하고, 입찰을 준비할 공고를 승인하세요.</p>

    <p v-if="!flow.selected.length" class="notice">
      선택한 공고가 없습니다. <router-link to="/summaries">공고 요약</router-link>에서 공고를 선택해 주세요.
    </p>

    <div v-for="b in flow.selected" :key="keyOf(b)" class="item">
      <label class="check" style="margin: 0 0 8px">
        <input v-model="picked" type="checkbox" :value="keyOf(b)" />
        <strong>{{ b.title }}</strong> <span class="meta">{{ b.bid_no }}-{{ b.revision }}</span>
      </label>
      <ReviewCard :bid="b" />
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <button v-if="flow.selected.length" class="primary" type="button" :disabled="saving" @click="approve">
      {{ saving ? '저장 중…' : `선택한 ${picked.length}건 승인` }}
    </button>

    <template v-if="flow.approved.length">
      <h2 style="font-size: 1.1rem; margin-top: 28px">준비 체크리스트</h2>
      <div v-for="b in flow.approved" :key="keyOf(b)" class="item">
        <strong>{{ b.title }}</strong>
        <ChecklistCard :bid="b" />
      </div>
    </template>
  </div>
</template>
