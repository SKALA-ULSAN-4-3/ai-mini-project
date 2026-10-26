import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

// 화면을 오가도 유지해야 하는 "작업 진행 상태" 보관소. 새로고침해도 남도록 sessionStorage에 저장합니다.
export const useFlowStore = defineStore('flow', () => {
  const saved = JSON.parse(sessionStorage.getItem('flow') || '{}')
  const searchId = ref(saved.searchId || '')
  const documentsJobId = ref(saved.documentsJobId || '')
  const period = ref(saved.period || null) // 마지막 검색 조건
  const candidates = ref(saved.candidates || []) // ② 추린 공고
  const excluded = ref(saved.excluded || []) // ② 조건에 맞지 않아 제외된 공고
  const readyKeys = ref(saved.readyKeys || []) // ③ 공고문 준비가 끝난 공고
  const summaries = ref(saved.summaries || []) // ④ 요약 결과
  const selected = ref(saved.selected || []) // ⑤ 선택한 공고
  const approved = ref(saved.approved || []) // ⑧ 승인한 공고

  watch([searchId, documentsJobId, period, candidates, excluded, readyKeys, summaries, selected, approved], () => {
    sessionStorage.setItem('flow', JSON.stringify({
      searchId: searchId.value, documentsJobId: documentsJobId.value, period: period.value, candidates: candidates.value, excluded: excluded.value,
      readyKeys: readyKeys.value, summaries: summaries.value, selected: selected.value, approved: approved.value,
    }))
  }, { deep: true })

  function resetFrom(step) {
    // 새로 검색하면 뒤 단계 결과는 비웁니다.
    if (step <= 3) { readyKeys.value = [] }
    if (step <= 4) { summaries.value = [] }
    if (step <= 5) { selected.value = []; approved.value = []; documentsJobId.value = '' }
  }
  function reset() {
    searchId.value = ''; period.value = null; candidates.value = []; excluded.value = []
    resetFrom(0)
  }
  return { searchId, documentsJobId, period, candidates, excluded, readyKeys, summaries, selected, approved, resetFrom, reset }
})
