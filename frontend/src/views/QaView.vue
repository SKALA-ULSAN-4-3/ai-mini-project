<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { onBeforeUnmount } from 'vue'
import { askQuestion, transcribe, synthesize } from '../api/flow'
import { errorMessage } from '../api/client'
import SourceList from '../components/SourceList.vue'

// /qa?bid=공고번호&rev=차수 로 들어오면 그 공고에 대한 질문이 됩니다.
const q = useRoute().query
const bid = q.bid ? { bid_no: q.bid, revision: String(q.rev || '000') } : null

const question = ref('')
const messages = ref([])
const loading = ref(false)
const error = ref('')

async function send(fromVoice = false) {
  const text = question.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', text })
  question.value = ''; error.value = ''; loading.value = true
  try {
    const r = await askQuestion(text, bid)
    messages.value.push({ role: 'bot', ...r })
    if (fromVoice === true) speak(r) // 음성으로 물었으면 음성으로도 답합니다.
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

// ---- X3 음성 질의: 마이크 녹음 → 텍스트(STT) → /rag-query → 답변 읽어 주기(TTS) ----
const recording = ref(false)
const transcribing = ref(false)
const speaking = ref(false)
const voiceNotice = ref('')
let recorder = null
let stream = null
let audio = null

// 담당자 확인이 필요한 답에는 음성에서도 같은 안내를 붙입니다.
const spokenText = (m) => [m.response, m.handoff ? '문서에 없는 내용입니다. 발주기관에 문의해 주세요.' : '', m.needs_review ? '담당자 확인이 필요합니다.' : ''].filter(Boolean).join(' ')

async function toggleMic() {
  error.value = ''; voiceNotice.value = ''
  if (recording.value) { recorder?.stop(); return }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    error.value = '이 브라우저는 음성 녹음을 지원하지 않습니다. 크롬을 사용해 주세요.'
    return
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch {
    error.value = '마이크를 사용할 수 없습니다. 브라우저 주소창에서 마이크 권한을 허용해 주세요.'
    return
  }
  const chunks = []
  recorder = new MediaRecorder(stream)
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data)
  recorder.onstop = async () => {
    recording.value = false
    stream?.getTracks().forEach((t) => t.stop())
    transcribing.value = true
    try {
      question.value = await transcribe(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
      voiceNotice.value = `인식된 질문: "${question.value}"`
      await send(true)
    } catch (e) {
      error.value = errorMessage(e, { 401: '로그인이 필요합니다.', 404: '이 서버에서는 음성 질의를 사용할 수 없습니다.' })
    } finally {
      transcribing.value = false
    }
  }
  recorder.start()
  recording.value = true
}

// 서버 음성(TTS)을 먼저 쓰고, 안 되면 브라우저의 읽어 주기 기능으로 대신합니다.
async function speak(m) {
  stopSpeaking()
  speaking.value = true
  try {
    const blob = await synthesize(spokenText(m))
    audio = new Audio(URL.createObjectURL(blob))
    audio.onended = () => { speaking.value = false }
    await audio.play()
  } catch {
    if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(spokenText(m))
      u.lang = 'ko-KR'
      u.onend = () => { speaking.value = false }
      window.speechSynthesis.speak(u)
    } else {
      speaking.value = false
    }
  }
}
function stopSpeaking() {
  audio?.pause(); audio = null
  window.speechSynthesis?.cancel()
  speaking.value = false
}
onBeforeUnmount(() => { stopSpeaking(); stream?.getTracks().forEach((t) => t.stop()) })
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
          <button type="button" class="small" @click="speak(m)">🔊 답변 듣기</button>
        </template>
      </div>
      <p v-if="transcribing" class="sub">음성을 글자로 바꾸는 중…</p>
      <p v-if="loading" class="sub">답변을 찾는 중…</p>
    </div>

    <p v-if="voiceNotice" class="meta">{{ voiceNotice }}</p>
    <p v-if="recording" class="notice">● 녹음 중입니다. 질문을 말한 뒤 마이크 버튼을 다시 눌러 끝내세요.</p>
    <p v-if="error" class="error">{{ error }}</p>
    <form class="ask" @submit.prevent="send(false)">
      <input v-model="question" placeholder="질문을 입력하거나 마이크로 말하세요" aria-label="질문" />
      <button type="button" :class="recording ? 'primary' : ''" :disabled="loading || transcribing" :aria-label="recording ? '녹음 끝내기' : '음성으로 질문하기'" @click="toggleMic">
        {{ recording ? '■ 끝내기' : '🎤 말하기' }}
      </button>
      <button class="primary" :disabled="loading || transcribing">보내기</button>
      <button v-if="speaking" type="button" @click="stopSpeaking">읽기 멈춤</button>
    </form>
  </div>
</template>
