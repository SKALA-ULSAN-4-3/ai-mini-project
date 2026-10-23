import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import client from '../api/client'

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
  }

  function logout() {
    token.value = ''
    sessionStorage.removeItem('token')
  }

  return { token, isLoggedIn, login, logout }
})
