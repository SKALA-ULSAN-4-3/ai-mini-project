<script setup>
import { ref, computed, watchEffect } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from './stores/auth'
import { useFlowStore } from './stores/flow'

const auth = useAuthStore()
const flow = useFlowStore()
const router = useRouter()
const route = useRoute()

// 화면마다 위쪽에 보여 줄 문구: [작은 제목, 제목, 설명]
const HERO = {
  '/login': ['AI BID ASSISTANT', '공공 입찰,\n읽는 시간은 줄이고 판단에 집중하세요', '공고 검색부터 준비 체크리스트까지, 모든 답에 공고문 출처를 붙입니다.'],
  '/signup': ['AI BID ASSISTANT', '우리 회사에 맞는 공고를\n가장 먼저 만나 보세요', '사업자등록번호로 가입하고 회사 프로필을 등록합니다.'],
  '/profile': ['COMPANY PROFILE', '회사 프로필', '업종·지역·금액·보유 서류를 등록하면 공고를 더 정확하게 추립니다.'],
  '/search': ['STEP 1 · SEARCH', '우리 회사에 맞는 공고 찾기', '기간과 검색어로 나라장터 공고를 찾아 관련 공고 20건으로 추립니다.'],
  '/summaries': ['STEP 2 · SUMMARY', '공고 요약과 선택', '공고문을 항목별로 요약하고, 준비할 공고를 고릅니다.'],
  '/review': ['STEP 3 · REVIEW', '채점표 검토와 승인', '항목별 예상 점수를 확인하고 입찰을 준비할 공고를 승인합니다.'],
  '/qa': ['STEP 4 · Q&A', '공고에 대해 물어보세요', '문서에서 찾은 답과 출처(파일명 p.쪽)를 함께 보여 줍니다.'],
}
// 오른쪽 도움말 카드 (화면마다 다른 안내)
const HELP = {
  '/search': ['기간은 최근 한 달이 기본이에요. 길게 잡을수록 오래 걸려요.', '검색어는 쉼표로 여러 개 넣을 수 있어요.', '회사 프로필이 있어야 우리 회사에 맞게 추려져요.'],
  '/profile': ['업종·지역·금액은 공고를 추리는 기준이에요.', '보유 서류는 체크리스트에서 자동으로 체크돼요.', '개인정보는 받지 않아요.'],
  '/summaries': ['항목마다 출처(파일명 p.쪽)가 붙어 있어요.', '"출처 확인 필요" 배지가 있으면 원문을 꼭 확인하세요.', '준비할 공고를 체크하고 "제안요청서 준비"를 누르세요.'],
  '/review': ['총점은 낙찰 가능성으로 오해되기 쉬워 항목별로만 보여 줘요.', '정성·가격 항목은 "담당자 판단"으로 남겨 둡니다.', '"에이전트로 채점"으로 두 방식의 결과를 비교할 수 있어요.'],
  '/qa': ['문서에 없는 질문은 "문서에 없음"으로 안내해요.', '자격 관련 답은 "담당자 확인 필요"가 붙어요.', '말하기 버튼으로 음성 질문도 할 수 있어요.'],
}
const FEATURES = [
  ['01', '모든 답에 공고문 출처', '파일명과 쪽수를 함께 보여 줘서, 담당자가 원문을 바로 열어 확인할 수 있습니다.'],
  ['02', '항목별 예상 점수', '총점 대신 계산 가능한 항목만 보여 주고, 정성·가격 항목은 담당자 판단으로 남깁니다.'],
  ['03', '결정은 사람이', 'AI는 추천만 합니다. 선택·승인·자격 판단은 담당자가 하고, 문서에 없는 질문은 문의로 안내합니다.'],
]
const hero = computed(() => HERO[route.path] || null)
const help = computed(() => HELP[route.path] || null)
const wide = computed(() => ['/login', '/signup'].includes(route.path)) // 로그인·가입: 큰 배너 화면
const inShell = computed(() => auth.isLoggedIn && !wide.value) // 로그인한 뒤: 왼쪽 메뉴가 있는 업무 화면

// 위쪽 단계 표시
const STEPS = [
  { to: '/search', label: '공고 검색' },
  { to: '/summaries', label: '요약·선택' },
  { to: '/review', label: '검토·승인' },
  { to: '/qa', label: 'Q&A' },
]
// 오른쪽 진행 현황 (다섯 단계 중 몇 단계에 결과가 있는지)
const STAGES = computed(() => [
  { label: '추린 공고', n: flow.candidates.length },
  { label: '공고문 준비', n: flow.readyKeys.length },
  { label: '요약', n: flow.summaries.length },
  { label: '선택', n: flow.selected.length },
  { label: '승인', n: flow.approved.length },
])
const progressPct = computed(() => Math.round((STAGES.value.filter((x) => x.n > 0).length / STAGES.value.length) * 100))
const pageClass = computed(() => 'p-' + (route.path.replace('/', '') || 'home'))
const stepIndex = computed(() => STEPS.findIndex((s) => s.to === route.path))

// 다크 모드: 사용자가 고른 값을 이 브라우저에 기억합니다. (고른 적이 없으면 라이트)
const theme = ref('light')
try { theme.value = localStorage.getItem('theme') === 'dark' ? 'dark' : 'light' } catch { /* 저장소를 못 쓰면 라이트 */ }
watchEffect(() => {
  document.documentElement.dataset.theme = theme.value
  try { localStorage.setItem('theme', theme.value) } catch { /* 무시 */ }
})
const toggleTheme = () => { theme.value = theme.value === 'dark' ? 'light' : 'dark' }
const themeLabel = computed(() => (theme.value === 'dark' ? '라이트 모드로 보기' : '다크 모드로 보기'))

function onLogout() {
  flow.reset() // 이전 작업 내용 지우기
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <!-- 로그인한 뒤: 왼쪽 메뉴 + 위쪽 단계 표시 + 오른쪽 도움말 -->
  <div v-if="inShell" class="shell">
    <aside class="side">
      <strong class="side-brand">입찰 공고 도우미</strong>
      <p class="side-label">업무 흐름</p>
      <nav class="side-nav">
        <router-link v-for="(s, i) in STEPS" :key="s.to" :to="s.to"><span class="side-num">{{ i + 1 }}</span>{{ s.label }}</router-link>
      </nav>
      <p class="side-label">설정</p>
      <nav class="side-nav">
        <router-link to="/profile"><span class="side-num">●</span>회사 프로필</router-link>
      </nav>
      <button class="side-theme icon-btn" type="button" :aria-label="themeLabel" :title="themeLabel" @click="toggleTheme">
        <svg v-if="theme === 'dark'" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
      </button>
      <button class="side-logout" @click="onLogout">로그아웃</button>
    </aside>

    <div class="main">
      <header class="head">
        <div class="head-title">
          <p class="eyebrow">{{ hero ? hero[0] : '' }}</p>
          <h2>{{ hero ? hero[1] : '' }}</h2>
          <p class="head-desc">{{ hero ? hero[2] : '' }}</p>
        </div>
        <ol v-if="stepIndex >= 0" class="stepper">
          <li v-for="(s, i) in STEPS" :key="s.to" :class="{ on: i === stepIndex, done: i < stepIndex }">
            <span class="step-dot">{{ i < stepIndex ? '✓' : i + 1 }}</span>{{ s.label }}
          </li>
        </ol>
      </header>

      <main class="body">
        <div class="body-grid" :class="{ 'no-help': !hero }">
          <div class="body-main" :class="pageClass"><router-view /></div>
          <aside v-if="hero" class="side-panel">
            <section class="status">
              <h3>진행 현황</h3>
              <ul class="status-list">
                <li v-for="x in STAGES" :key="x.label" :class="{ on: x.n > 0 }">
                  <span class="status-dot"></span>
                  <span class="status-name">{{ x.label }}</span>
                  <b>{{ x.n }}건</b>
                </li>
              </ul>
              <div class="status-bar"><i :style="{ width: progressPct + '%' }"></i></div>
              <p class="status-note">{{ progressPct }}% 진행 · 승인까지 마치면 체크리스트가 열려요.</p>
            </section>
            <section v-if="help" class="help">
              <h3>이렇게 써 보세요</h3>
              <ul>
                <li v-for="t in help" :key="t">{{ t }}</li>
              </ul>
              <div class="help-art">
                <svg viewBox="0 0 220 120" role="img" aria-label="공고문 카드에 출처가 붙은 모습">
                  <rect x="30" y="14" width="150" height="96" rx="10" fill="#3a3a42"/>
                  <rect x="44" y="26" width="150" height="96" rx="10" fill="#ffffff"/>
                  <rect x="58" y="40" width="70" height="8" rx="4" fill="#25252b"/>
                  <rect x="58" y="58" width="120" height="6" rx="3" fill="#dddde6"/>
                  <rect x="58" y="72" width="104" height="10" rx="3" fill="#e4defe"/>
                  <rect x="58" y="92" width="42" height="16" rx="8" fill="#5b3df5"/>
                  <text x="79" y="103.5" text-anchor="middle" font-size="9" font-weight="700" fill="#fff" font-family="sans-serif">p.12</text>
                  <circle cx="186" cy="30" r="14" fill="#5b3df5"/>
                  <path d="M179 30 l5 5 l9 -10" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </div>
            </section>
          </aside>
        </div>
      </main>
    </div>
  </div>

  <!-- 로그인·회원가입: 왼쪽 소개 + 오른쪽 입력 카드 (스크롤 없이 한 화면) -->
  <div v-else class="auth">
    <section class="auth-left">
      <strong class="brand">입찰 공고 도우미</strong>
      <div v-if="hero" class="auth-copy">
        <p class="eyebrow">{{ hero[0] }}</p>
        <h1 class="auth-title">{{ hero[1] }}</h1>
        <p class="auth-desc">{{ hero[2] }}</p>
        <ul class="auth-features">
          <li v-for="f in FEATURES" :key="f[0]">
            <span class="auth-num">{{ f[0] }}</span>
            <div>
              <h3>{{ f[1] }}</h3>
              <p>{{ f[2] }}</p>
            </div>
          </li>
        </ul>
      </div>
      <p class="auth-foot">나라장터 공공 입찰 공고 탐색·요약 · SKALA 울산 4-3 미니 프로젝트</p>
    </section>
    <main class="auth-right">
      <button class="auth-theme icon-btn" type="button" :aria-label="themeLabel" :title="themeLabel" @click="toggleTheme">
        <svg v-if="theme === 'dark'" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
        <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
      </button>
      <router-view />
    </main>
  </div>
</template>
