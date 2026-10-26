<script setup>
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useFlowStore } from '../stores/flow'
import { askQuestion, transcribe, synthesize } from '../api/flow'
import { errorMessage } from '../api/client'
import SourceList from '../components/SourceList.vue'

// /qa?bid=공고번호&rev=차수 로 들어오면 그 공고에 대한 질문이 됩니다.
const q = useRoute().query
const flow = useFlowStore()
const bid = ref(q.bid ? { bid_no: q.bid, revision: String(q.rev || '000') } : null)

// 질문할 공고: 어떤 공고에 묻는지 칸 위에 보여 주고, 요약·선택한 공고 중에서 바꿀 수도 있게 합니다.
const bidKey = computed(() => (bid.value ? bid.value.bid_no + '|' + bid.value.revision : ''))
const titleFor = (b) => {
  const hit = [...flow.selected, ...flow.summaries, ...flow.candidates].find((x) => x.bid_no === b.bid_no)
  return hit?.title || hit?.summary?.title?.value || b.bid_no
}
const bidOptions = computed(() => {
  const map = new Map()
  for (const b of [...flow.selected, ...flow.summaries, ...(bid.value ? [bid.value] : [])]) {
    const key = b.bid_no + '|' + b.revision
    if (!map.has(key)) map.set(key, { key, bid_no: b.bid_no, revision: String(b.revision), title: titleFor(b) })
  }
  return [...map.values()]
})
const currentTitle = computed(() => (bid.value ? titleFor(bid.value) : ''))
function pickBid(key) {
  const o = bidOptions.value.find((x) => x.key === key)
  bid.value = o ? { bid_no: o.bid_no, revision: o.revision } : null
  messages.value = [] // 공고를 바꾸면 이전 대화는 지웁니다.
  error.value = ''; voiceNotice.value = ''
}

const question = ref('')
const messages = ref([])
const loading = ref(false)
const error = ref('')
const chatEl = ref(null)

// 새 메시지가 오면 대화 칸을 맨 아래로 내립니다.
watch(messages, () => nextTick(() => { if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight }), { deep: true })

// 서버가 알려 준 이유(detail)를 이해하기 쉬운 문장으로 바꿉니다.
function qaError(e) {
  const detail = e.response?.data?.detail
  const text = typeof detail === 'string' ? detail.replace(/^[^\w가-힣]+/, '') : ''
  if (/로딩되지|적재되지/.test(text)) {
    return '서버에 이 공고의 문서가 없습니다. 서버가 다시 시작되면 받아 둔 문서가 지워져요. 검색 화면에서 공고문을 다시 준비한 뒤 질문해 주세요.'
  }
  if (text && e.response?.status >= 400 && e.response?.status < 500) return '서버 안내: ' + text
  return errorMessage(e, { 401: '로그인이 필요합니다. 다시 로그인해 주세요.' })
}

async function send(fromVoice = false) {
  const text = question.value.trim()
  if (!text || loading.value) return
  messages.value.push({ role: 'user', text })
  question.value = ''; error.value = ''; loading.value = true
  try {
    const r = await askQuestion(text, bid.value)
    messages.value.push({ role: 'bot', ...r })
    if (fromVoice === true) speak(r) // 음성으로 물었으면 음성으로도 답합니다.
  } catch (e) {
    // 답을 못 받은 질문은 대화에서 빼고 입력칸에 되돌려 놓아, 서버가 복구된 뒤 그대로 다시 보낼 수 있게 합니다.
    messages.value.pop()
    question.value = text
    error.value = qaError(e)
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
let cancelled = false // 취소 버튼으로 끝낸 녹음은 글자 변환·전송을 하지 않음
let stream = null
let audio = null

// 담당자 확인이 필요한 답에는 음성에서도 같은 안내를 붙입니다.
const spokenText = (m) => [m.response, m.handoff ? '문서에 없는 내용입니다. 발주기관에 문의해 주세요.' : '', m.needs_review ? '담당자 확인이 필요합니다.' : ''].filter(Boolean).join(' ')

async function toggleMic() {
  error.value = ''; voiceNotice.value = ''
  if (recording.value) { recorder?.stop(); return }
  if (transcribing.value || loading.value) return // 처리 중에는 새로 녹음하지 않음
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
    stopWave()
    stream?.getTracks().forEach((t) => t.stop())
    if (cancelled) {
      cancelled = false
      voiceNotice.value = '녹음을 취소했어요. 질문은 전송되지 않았어요.'
      return
    }
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
  cancelled = false
  recorder.start()
  recording.value = true
  startWave(stream)
}

// 녹음을 버리고 끝냅니다. (말하다 실수했을 때)
function cancelRecording() {
  if (!recording.value) return
  cancelled = true
  recorder?.stop()
}

// ---- 말하는 동안 목소리 높낮이(주파수별 크기)를 막대로 보여 주기 ----
const WAVE_BARS = 28
const levels = ref(Array(WAVE_BARS).fill(4))
let audioCtx = null
let analyser = null
let rafId = 0
function startWave(s) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return
    audioCtx = new Ctx()
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.7
    audioCtx.createMediaStreamSource(s).connect(analyser)
    const data = new Uint8Array(analyser.frequencyBinCount)
    const usable = Math.min(data.length, 24) // 사람 목소리가 모여 있는 낮은 주파수 쪽만 사용
    const per = usable / WAVE_BARS
    const draw = () => {
      analyser.getByteFrequencyData(data)
      // 왼쪽 막대 = 낮은 소리, 오른쪽 막대 = 높은 소리. 크게 말할수록 막대가 길어집니다.
      levels.value = Array.from({ length: WAVE_BARS }, (_, i) => {
        const a = Math.floor(i * per)
        const b = Math.max(a + 1, Math.floor((i + 1) * per))
        let sum = 0
        for (let k = a; k < b; k++) sum += data[k]
        return Math.max(4, Math.min(100, Math.round(((sum / (b - a)) / 255) * 100 * 1.6)))
      })
      rafId = requestAnimationFrame(draw)
    }
    draw()
  } catch {
    // 파형을 못 그려도 녹음과 질문은 계속됩니다.
  }
}
function stopWave() {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
  try { audioCtx?.close() } catch { /* 이미 닫힘 */ }
  audioCtx = null; analyser = null
  levels.value = Array(WAVE_BARS).fill(4)
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
onBeforeUnmount(() => { stopSpeaking(); stopWave(); stream?.getTracks().forEach((t) => t.stop()) })
</script>

<template>
  <div class="card">
    <h1>공고 Q&A</h1>

    <div class="qa-target" :class="{ empty: !bid }">
      <span class="qa-target-label">대상 공고</span>
      <div class="qa-target-main">
        <template v-if="bid">
          <strong>{{ currentTitle }}</strong>
          <span class="meta">{{ bid.bid_no }}-{{ bid.revision }}</span>
        </template>
        <strong v-else>공고를 고르면 그 공고에 대해 질문할 수 있어요</strong>
      </div>
      <select v-if="bidOptions.length" :value="bidKey" aria-label="질문할 공고" @change="pickBid($event.target.value)">
        <option value="">공고 선택 없이 질문</option>
        <option v-for="o in bidOptions" :key="o.key" :value="o.key">{{ o.title }} ({{ o.bid_no }}-{{ o.revision }})</option>
      </select>
      <router-link v-else to="/summaries" class="back">요약·선택에서 공고 고르기 →</router-link>
    </div>

    <div ref="chatEl" class="chat">
      <p v-if="!messages.length && !loading && !transcribing" class="chat-empty">
        예: 마감 일시는? 예산은? 제출 서류는?<br />아래 입력칸에 쓰거나 말하기 버튼으로 물어보세요.
      </p>
      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <template v-if="m.role === 'user'">{{ m.text }}</template>
        <template v-else>
          <p>{{ m.response }}</p>
          <p v-if="m.handoff" class="notice">문서에 없는 내용입니다. 발주기관에 문의해 주세요.</p>
          <span v-if="m.needs_review" class="badge warn">담당자 확인 필요</span>
          <SourceList :sources="m.sources || []" />
          <p v-if="m.latency_ms" class="src">응답 시간 {{ m.latency_ms }}ms</p>
          <button type="button" class="small" @click="speak(m)">답변 듣기</button>
        </template>
      </div>
      <p v-if="transcribing" class="sub">음성을 글자로 바꾸는 중…</p>
      <p v-if="loading" class="sub">답변을 찾는 중…</p>
    </div>

    <p v-if="voiceNotice" class="meta">{{ voiceNotice }}</p>
    <div v-if="recording" class="rec-box" role="status">
      <div class="wave" aria-hidden="true"><i v-for="(h, i) in levels" :key="i" :style="{ height: h + '%' }"></i></div>
      <p><span class="rec-dot"></span>녹음 중입니다. 질문을 말한 뒤 <strong>끝내기</strong>를 누르면 질문이 전송돼요. 취소하면 버려져요.</p>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <form class="ask" @submit.prevent="send(false)">
      <input v-model="question" placeholder="질문을 입력하거나 마이크로 말하세요" aria-label="질문" />
      <button type="button" class="small" :class="{ rec: recording }" :disabled="loading || transcribing" :aria-label="recording ? '녹음 끝내기' : '음성으로 질문하기'" @click="toggleMic">
        {{ recording ? '끝내기' : '말하기' }}
      </button>
      <button v-if="recording" type="button" class="small" aria-label="녹음 취소" @click="cancelRecording">취소</button>
      <button class="primary" :disabled="loading || transcribing">보내기</button>
      <button v-if="speaking" type="button" class="small" @click="stopSpeaking">읽기 멈춤</button>
    </form>
  </div>
</template>
