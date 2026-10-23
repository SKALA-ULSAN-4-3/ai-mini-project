<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { askQuestion } from '../api/flow'
import { errorMessage } from '../api/client'
import SourceList from '../components/SourceList.vue'

// /qa?bid=공고번호&rev=차수 로 들어오면 그 공고에 대한 질문이 됩니다.
const q = useRoute().query
const bid = q.bid ? { bid_no: q.bid, revision: String(q.rev || '000') } : null

const question = ref('')
const messages = ref([])
const loading = ref(false)
const error = ref('')

async function send() {
  const text = question.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', text })
  question.value = ''; error.value = ''; loading.value = true
  try {
    const r = await askQuestion(text, bid)
    messages.value.push({ role: 'bot', ...r })
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card">
    <h1>공고 Q&A</h1>
    <p class="sub">
      <template v-if="bid">대상 공고: {{ bid.bid_no }}-{{ bid.revision }}. </template>
      <template v-else>공고 요약 화면의 "이 공고에 질문하기"로 들어오면 그 공고에 대해 물을 수 있어요. </template>
      예: 마감 일시는? 예산은? 제출 서류는?
    </p>

    <div class="chat">
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <template v-if="m.role === 'user'">{{ m.text }}</template>
        <template v-else>
          <p>{{ m.response }}</p>
          <p v-if="m.handoff" class="notice">문서에 없는 내용입니다. 발주기관에 문의해 주세요.</p>
          <span v-if="m.needs_review" class="badge warn">담당자 확인 필요</span>
          <SourceList :sources="m.sources || []" />
          <p v-if="m.latency_ms" class="src">응답 시간 {{ m.latency_ms }}ms</p>
        </template>
      </div>
      <p v-if="loading" class="sub">답변을 찾는 중…</p>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <form class="ask" @submit.prevent="send">
      <input v-model="question" placeholder="질문을 입력하세요" aria-label="질문" />
      <button class="primary" :disabled="loading">보내기</button>
    </form>
  </div>
</template>
