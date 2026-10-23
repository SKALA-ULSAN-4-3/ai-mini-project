<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchScoringTable, fetchScore } from '../api/flow'
import { errorMessage } from '../api/client'
import SourceList from './SourceList.vue'

// ⑦ 공고 한 건의 채점표(2번) + 예상 점수(3번). 총점은 표시하지 않습니다.
const props = defineProps({ bid: Object })
const table = ref(null)
const score = ref({ items: [], needs_review: true, missing_fields: [], questions: [] })
const loading = ref(true)
const waiting = ref(false)
const error = ref('')

// 3번 항목 상태 → 화면 문구
const STATUS = { calculated: '계산됨', manual: '담당자 판단', missing_profile: '프로필 정보 부족' }

// 채점표 항목을 평가부문(section)별로 묶기
const sections = computed(() => {
  const map = {}
  for (const it of table.value?.items || []) (map[it.section || '기타'] ||= []).push(it)
  return Object.entries(map).map(([name, items]) => ({ name, items }))
})
const unverified = computed(() => (table.value?.items || []).some((it) => it.source_verified === false))

async function load() {
  loading.value = true; waiting.value = false; error.value = ''
  try {
    const [t, s] = await Promise.all([fetchScoringTable(props.bid), fetchScore(props.bid)])
    table.value = t
    score.value = s
  } catch (e) {
    // 409 = 제안요청서가 아직 준비되지 않음
    if (e.response?.status === 409) waiting.value = true
    else error.value = errorMessage(e, { 400: '차수를 지정해야 합니다.', 404: '공고·차수를 찾을 수 없습니다.' })
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div>
    <p v-if="loading" class="sub">채점표를 불러오는 중… (몇 초 걸릴 수 있어요)</p>
    <div v-if="waiting" class="notice">
      제안요청서 준비 중입니다. 잠시 후 다시 확인해 주세요.
      <button type="button" class="small" @click="load">다시 확인</button>
    </div>
    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="table">
      <span v-if="unverified" class="badge warn">출처 확인 필요</span>
      <span v-if="table.consistent === false" class="badge warn">배점 합계 불일치 — 원문 확인 필요</span>
      <div v-for="sec in sections" :key="sec.name" class="kv">
        <strong>{{ sec.name }}</strong>
        <p v-for="it in sec.items" :key="it.item" class="meta">
          {{ it.item }} · {{ it.max_score }}점<span v-if="it.eval_type"> · {{ it.eval_type }}</span>
          <span v-if="it.source_verified === false" class="badge warn" style="margin-left: 6px">출처 확인 필요</span>
        </p>
      </div>
      <p v-if="table.pass_rule" class="meta">협상적격 기준: {{ table.pass_rule }}</p>
      <p v-if="table.handoff" class="notice">채점표를 문서에서 찾지 못했습니다. 발주기관에 문의해 주세요.</p>
    </template>

    <template v-if="score.items.length">
      <p v-if="score.needs_review" class="notice">모든 점수는 참고용입니다. 총점은 낙찰 가능성으로 오해되기 쉬워 항목별로만 표시합니다.</p>
      <p v-if="score.questions?.length" class="notice">
        <span v-for="q in score.questions" :key="q" style="display: block">{{ q }}</span>
        <router-link to="/profile">회사 프로필에서 입력하기</router-link>
      </p>
      <table>
        <thead><tr><th>항목</th><th>배점</th><th>예상</th><th>근거</th></tr></thead>
        <tbody>
          <tr v-for="it in score.items" :key="it.id || it.item">
            <td>{{ it.item }}</td>
            <td>{{ it.max }}</td>
            <td>
              <span v-if="typeof it.expected === 'number'">{{ it.expected }}점 <span class="meta">({{ STATUS[it.status] || '예상' }})</span></span>
              <span v-else class="badge warn">{{ STATUS[it.status] || it.expected }}</span>
            </td>
            <td>
              <span v-if="it.reason" class="meta" style="display: block">{{ it.reason }}</span>
              <SourceList :sources="it.sources || []" />
            </td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
