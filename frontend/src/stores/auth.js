import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '../api/client'
import { fetchPipeline } from '../api/flow'
import { useFlowStore } from './flow'

// 로그인 상태를 모든 화면이 함께 쓰도록 모아 둔 보관소
export const useAuthStore = defineStore('auth', () => {
  // 새로고침해도 유지되도록 sessionStorage 에서 먼저 꺼내 봅니다.
  const token = ref(sessionStorage.getItem('token') || '')
  const isLoggedIn = computed(() => token.value !== '')

  async function login(businessNumber, password) {
    const res = await client.post('/login', {
      business_registration_number: businessNumber,
      password,
    })
    token.value = res.data.access_token
    sessionStorage.setItem('token', token.value)
    await restoreFlow()
  }

  // 로그인할 때마다: 이전 계정이 남긴 화면 상태를 비우고, 서버(DB)에 저장된 내 선택·승인 목록으로 복원합니다.
  async function restoreFlow() {
    const flow = useFlowStore()
    flow.reset()
    try {
      const rows = await fetchPipeline()
      // 공고 제목은 서버에 저장되지 않아 공고번호로 대신 표시합니다.
      flow.selected = rows.map((r) => ({ bid_no: r.bid_no, revision: r.revision, title: r.bid_no }))
      flow.approved = flow.selected.filter((b) => rows.find((r) => r.bid_no === b.bid_no && r.revision === b.revision)?.status === 'approved')
    } catch (e) {
      console.warn('[선택·승인 복원 실패] 로그인은 계속 진행합니다.', e?.message)
    }
  }

  function logout() {
    token.value = ''
    sessionStorage.removeItem('token')
  }

  return { token, isLoggedIn, login, logout }
})
