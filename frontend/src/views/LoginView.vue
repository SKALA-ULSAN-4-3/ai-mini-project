<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { errorMessage } from '../api/client'

const router = useRouter()
const auth = useAuthStore()

// ref(): 화면 입력칸과 연결되는 "값 상자". 값은 .value 로 꺼냅니다.
const businessNumber = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function onSubmit() {
  if (loading.value) return
  error.value = ''
  // 숫자가 아닌 글자(하이픈, 공백)를 모두 제거
  const number = businessNumber.value.replace(/\D/g, '')

  if (number.length !== 10) {
    error.value = '사업자등록번호는 숫자 10자리입니다.'
    return
  }
  if (!password.value) {
    error.value = '비밀번호를 입력해 주세요.'
    return
  }

  loading.value = true
  try {
    await auth.login(number, password.value)
    router.push('/search')
  } catch (e) {
    error.value = errorMessage(e, { 401: '사업자등록번호 또는 비밀번호가 올바르지 않습니다.' })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card narrow">
    <h1>로그인</h1>
    <p class="sub">사업자등록번호로 로그인합니다.</p>

    <form @submit.prevent="onSubmit">
      <label for="bn">사업자등록번호 <span class="hint">하이픈 없이 10자리</span></label>
      <input id="bn" v-model="businessNumber" inputmode="numeric" autocomplete="username" />

      <label for="pw">비밀번호</label>
      <input id="pw" v-model="password" type="password" autocomplete="current-password" />

      <p v-if="loading" class="meta" style="margin-top: 10px">서버가 잠들어 있으면 첫 요청에 30~60초 걸릴 수 있어요.</p>
      <p v-if="error" class="error">{{ error }}</p>
      <button class="primary" :disabled="loading">{{ loading ? '로그인 중…' : '로그인' }}</button>
    </form>

    <p class="foot">계정이 없나요? <router-link to="/signup">회원가입</router-link></p>
  </div>
</template>
