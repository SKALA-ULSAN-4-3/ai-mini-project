import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import LoginView from '../views/LoginView.vue'
import SignupView from '../views/SignupView.vue'
import ProfileView from '../views/ProfileView.vue'
import SearchView from '../views/SearchView.vue'
import SummariesView from '../views/SummariesView.vue'
import ReviewView from '../views/ReviewView.vue'
import QaView from '../views/QaView.vue'

const need = { requiresAuth: true } // 로그인한 사람만 들어올 수 있는 화면

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', component: LoginView },
    { path: '/signup', component: SignupView },
    { path: '/profile', component: ProfileView, meta: need },
    { path: '/search', component: SearchView, meta: need }, // ① ② ③
    { path: '/summaries', component: SummariesView, meta: need }, // ④ ⑤
    { path: '/review', component: ReviewView, meta: need }, // ⑦ ⑧ ⑨
    { path: '/qa', component: QaView, meta: need },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isLoggedIn) return '/login'
})

export default router
