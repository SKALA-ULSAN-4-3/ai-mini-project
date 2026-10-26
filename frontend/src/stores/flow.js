import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { searchBids } from '../api/flow'

// 화면을 오가도 유지해야 하는 "작업 진행 상태" 보관소. 새로고침해도 남도록 sessionStorage에 저장합니다.
export const useFlowStore = defineStore('flow', () => {
  const saved = JSON.parse(sessionStorage.getItem('flow') || '{}')
  const searchId = ref(saved.searchId || '')
  const period = ref(saved.period || null) // 마지막 검색 조건
  const candidates = ref(saved.candidates || []) // ② 추린 공고
  const excluded = ref(saved.excluded || []) // ② 조건에 맞지 않아 제외된 공고
  const readyKeys = ref(saved.readyKeys || []) // ③ 공고문 준비가 끝난 공고
  const summaries = ref(saved.summaries || []) // ④ 요약 결과
  const selected = ref(saved.selected || []) // ⑤ 선택한 공고
  const approved = ref(saved.approved || []) // ⑧ 승인한 공고

  watch([searchId, period, candidates, excluded, readyKeys, summaries, selected, approved], () => {
    sessionStorage.setItem('flow', JSON.stringify({
      searchId: searchId.value, period: period.value, candidates: candidates.value, excluded: excluded.value,
      readyKeys: readyKeys.value, summaries: summaries.value, selected: selected.value, approved: approved.value,
    }))
  }, { deep: true })

  function resetFrom(step) {
    // 새로 검색하면 뒤 단계 결과는 비웁니다.
    if (step <= 3) { readyKeys.value = [] }
    if (step <= 4) { summaries.value = [] }
    if (step <= 5) { selected.value = []; approved.value = [] }
  }
  function reset() {
    searchId.value = ''; period.value = null; candidates.value = []; excluded.value = []
    resetFrom(0)
  }
  async function prepareWithSearchRecovery(prepare, bids) {
    try {
      return await prepare(searchId.value, bids)
    } catch (error) {
      // 서버 재시작으로 검색 파일이 사라진 경우만 복원한다. 다른 404·통신 오류는 재요청하지 않는다.
      if (error.response?.status !== 404 || error.response?.data?.detail !== '검색 결과가 없습니다.') throw error
      const savedPeriod = period.value
      const queries = Array.isArray(savedPeriod?.search_queries)
        ? savedPeriod.search_queries
        : String(savedPeriod?.queries || '').split(',').map((query) => query.trim()).filter(Boolean)
      if (!savedPeriod?.from || !savedPeriod?.to || !queries.length) {
        error.recoveryMessage = '서버의 검색 기록이 만료됐습니다. 공고 검색에서 다시 검색해 주세요.'
        throw error
      }
      // /search-bids는 DB 캐시를 먼저 조회하고 새 로컬 스냅샷과 search_id를 발급한다.
      const restored = await searchBids({ from: savedPeriod.from, to: savedPeriod.to,
        queries, limit: savedPeriod.limit ?? 20 })
      if (!restored.search_id) {
        error.recoveryMessage = '검색 기록을 복원하지 못했습니다. 공고 검색에서 다시 검색해 주세요.'
        throw error
      }
      searchId.value = restored.search_id
      period.value = { ...savedPeriod, search_queries: queries, limit: savedPeriod.limit ?? 20,
        deadline_from: restored.deadline_from || savedPeriod.from,
        deadline_to: restored.deadline_to || savedPeriod.to }
      // 복원해도 작업을 만들 수 없으면 오류를 그대로 전달한다. 반복 복원은 하지 않는다.
      return await prepare(searchId.value, bids)
    }
  }
  return { searchId, period, candidates, excluded, readyKeys, summaries, selected, approved,
    resetFrom, reset, prepareWithSearchRecovery }
})
