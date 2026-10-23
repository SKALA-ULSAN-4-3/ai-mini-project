<script setup>
// ③' 재확인 결과 표시. 부적격이어도 목록에서 지우지 않고 "이유"와 함께 알려 줍니다.
defineProps({ recheck: Object })
const LABEL = {
  confirmed: ['적격 확인(최종 확정 아님)', 'badge'],
  disqualified: ['부적격 가능', 'badge danger'],
  unknown: ['재확인 미확인', 'badge warn'],
  not_evaluated: ['재확인 전(공고문 미적재)', 'badge warn'],
}
</script>

<template>
  <p v-if="recheck" class="chips" style="margin: 4px 0">
    <span :class="(LABEL[recheck.status] || LABEL.unknown)[1]">{{ (LABEL[recheck.status] || LABEL.unknown)[0] }}</span>
    <span v-for="r in recheck.reasons || []" :key="r" class="meta">{{ r }}</span>
  </p>
</template>
