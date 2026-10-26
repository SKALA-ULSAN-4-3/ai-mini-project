<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchScoringTable, fetchScore, fetchAgentScore } from '../api/flow'
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

// ---- X2 채점 에이전트: 고정 경로 결과와 나란히 비교 ----
const agent = ref(null)
const agentLoading = ref(false)
const agentError = ref('')
const AGENT_STATUS = { complete: '모든 항목 처리 완료', needs_input: '프로필 정보가 더 필요합니다', max_tool_calls: '도구 호출 한도에 도달했습니다' }

async function runAgent() {
  if (agentLoading.value) return // 채점 중에는 다시 누를 수 없음
  agentLoading.value = true; agentError.value = ''
  try {
    agent.value = await fetchAgentScore(props.bid)
  } catch (e) {
    agentError.value = e.response?.status === 404
      ? '이 서버에서는 에이전트 채점을 사용할 수 없습니다. (서버에서 켜져 있지 않음)'
      : errorMessage(e, { 409: '제안요청서가 아직 준비되지 않았습니다.' })
  } finally {
    agentLoading.value = false
  }
}
const show = (v) => (typeof v === 'number' ? `${v}점` : v || '-')
const same = (a, b) => a === b
// 서버가 보내는 질문 속 영어 항목 이름을 한글로 바꿔 보여 줍니다.
const FIELD_KO = { credit_rating: '신용등급', track_records: '수행 실적', certs: '인증', licenses: '면허', region: '소재지', company_size: '기업 규모', industry: '업종', owned_docs: '보유 서류', budget_min: '희망 금액(최소)', budget_max: '희망 금액(최대)', keywords: '관심 키워드' }
const ko = (q) => Object.entries(FIELD_KO).reduce((t, [k, v]) => t.replaceAll(k, v), String(q))
</script>

<template>
  <div>
    <p v-if="loading" class="sub">채점표를 불러오는 중… (몇 초 걸릴 수 있어요)</p>
    <div v-if="waiting" class="notice">
      제안요청서 준비 중입니다. 잠시 후 다시 확인해 주세요.
      <button type="button" class="small" :disabled="loading" @click="load">{{ loading ? '확인 중…' : '다시 확인' }}</button>
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
        <span v-for="q in score.questions" :key="q" style="display: block">{{ ko(q) }}</span>
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

    <!-- X2: 에이전트로 채점 -->
    <div v-if="table" class="kv" style="margin-top: 14px">
      <button type="button" class="small" :disabled="agentLoading" @click="runAgent">
        {{ agent ? '에이전트로 다시 채점' : '에이전트로 채점' }}
      </button>
      <span class="meta" style="margin-left: 8px">AI가 도구를 골라 항목별로 계산합니다. 점수 계산은 코드가 하고, 결과는 위 고정 경로와 비교합니다.</span>
      <p v-if="agentLoading" class="sub">에이전트가 채점하는 중… (7~10초 넘게 걸릴 수 있어요)</p>
      <p v-if="agentError" class="error">{{ agentError }}</p>

      <template v-if="agent">
        <p class="notice">{{ AGENT_STATUS[agent.status] || agent.status }}. 점수는 참고용이며 최종 판단은 담당자가 합니다.</p>
        <table>
          <thead><tr><th>항목</th><th>고정 경로</th><th>에이전트</th><th>비교</th></tr></thead>
          <tbody>
            <tr v-for="it in agent.items" :key="it.id">
              <td>{{ it.item }}</td>
              <td>{{ show(score.items.find((x) => x.id === it.id)?.expected) }}</td>
              <td>{{ show(it.expected) }}</td>
              <td>
                <span v-if="same(score.items.find((x) => x.id === it.id)?.expected, it.expected)" class="badge ok">일치</span>
                <span v-else class="badge warn">다름</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="agent.questions?.length" class="notice">
          에이전트가 되묻습니다:
          <span v-for="q in agent.questions" :key="q" style="display: block">{{ ko(q) }}</span>
          <router-link to="/profile">회사 프로필에서 입력</router-link> 후
          <button type="button" class="small" :disabled="agentLoading" @click="runAgent">다시 채점</button>
        </p>
        <p class="src">
          응답 시간 {{ Math.round((agent.latency_ms || 0) / 100) / 10 }}초 · 도구 호출 {{ agent.tool_calls?.length || 0 }}회 · 모델 호출 {{ agent.model_calls }}회
          <template v-if="agent.token_usage"> · 토큰 입력 {{ agent.token_usage.input_tokens }} / 출력 {{ agent.token_usage.output_tokens }}</template>
        </p>
      </template>
    </div>
  </div>
</template>
