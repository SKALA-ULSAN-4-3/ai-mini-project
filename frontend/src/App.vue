<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useFlowStore } from './stores/flow'

const auth = useAuthStore()
const flow = useFlowStore()
const router = useRouter()

function onLogout() {
  flow.reset() // 이전 작업 내용 지우기
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <header class="topbar">
    <strong class="brand">입찰 공고 도우미</strong>
    <nav v-if="auth.isLoggedIn" class="menu">
      <router-link to="/search">공고 검색</router-link>
      <router-link to="/summaries">요약</router-link>
      <router-link to="/review">검토·승인</router-link>
      <router-link to="/qa">Q&A</router-link>
      <router-link to="/profile">회사 프로필</router-link>
    </nav>
    <span v-else class="menu"></span>
    <button v-if="auth.isLoggedIn" class="link" @click="onLogout">로그아웃</button>
  </header>
  <main class="page">
    <router-view />
  </main>
</template>
