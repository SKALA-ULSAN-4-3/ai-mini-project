<script setup>
import { computed } from 'vue'
// 출처(파일명 p.쪽수 · 공고번호-차수 · 수집일)를 보여주는 부품. 팀 응답의 필드 이름(filename/collected_at)도 받습니다.
const props = defineProps({ sources: { type: Array, default: () => [] } })
const list = computed(() =>
  props.sources.map((s) =>
    typeof s === 'string'
      ? { text: s }
      : { file: s.file ?? s.filename, page: s.page, bid_no: s.bid_no, revision: s.revision, collected: s.collected ?? s.collected_at }
  )
)
</script>

<template>
  <p v-if="list.length" class="src">
    <span v-for="(s, i) in list" :key="i">
      출처: <template v-if="s.text">{{ s.text }}</template><template v-else>{{ s.file }} p.{{ s.page }}</template>
      <template v-if="s.bid_no"> · {{ s.bid_no }}<template v-if="s.revision">-{{ s.revision }}</template></template>
      <template v-if="s.collected"> · 수집 {{ s.collected }}</template>
    </span>
  </p>
</template>
