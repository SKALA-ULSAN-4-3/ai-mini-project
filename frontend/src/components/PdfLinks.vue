<script setup>
import { ref, onMounted } from 'vue'
import client from '../api/client'

// 요약 카드 안에서 "저장된 원문 PDF"와 나라장터 원문 주소를 보여주는 부품 (4번 GET /api/bids/{bid_no}/documents)
const props = defineProps({ bid: Object })
const docs = ref([])
const state = ref('loading') // loading | ok | error

onMounted(async () => {
  try {
    const { data } = await client.get(`/bids/${props.bid.bid_no}/documents`, { params: { revision: props.bid.revision } })
    docs.value = Array.isArray(data) ? data : []
    state.value = 'ok'
  } catch (e) {
    state.value = 'error' // 아직 PDF 가 올라오지 않았거나 서버 연결이 안 되면 조용히 "없음"으로 표시
  }
})

const mb = (n) => (Number(n || 0) / 1048576).toFixed(1)
// http(s) 주소만 링크로 만듭니다.
const safe = (u) => (/^https?:\/\//.test(u || '') ? u : null)
</script>

<template>
  <div class="kv">
    <strong>원문 PDF</strong>
    <p v-if="state === 'loading'" class="meta">불러오는 중…</p>
    <p v-else-if="!docs.length" class="meta">저장된 원문 PDF가 없습니다.</p>
    <p v-for="d in docs" :key="d.id || d.file_name" class="meta">
      <a v-if="safe(d.download_url)" :href="safe(d.download_url)" target="_blank" rel="noopener">{{ d.file_name }}</a>
      <span v-else>{{ d.file_name }}</span>
      ({{ mb(d.size_bytes) }}MB)
      <a v-if="safe(d.source_url)" :href="safe(d.source_url)" target="_blank" rel="noopener"> · 나라장터 원문</a>
    </p>
    <p v-if="docs.length" class="src">내려받기 링크는 1시간 동안만 유효해요.</p>
  </div>
</template>
