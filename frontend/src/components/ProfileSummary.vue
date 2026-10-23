<script setup>
import { ref, onMounted } from 'vue'
import client from '../api/client'
import { won } from '../utils'

// 공고 검색 화면 옆에 "지금 검색에 쓰는 회사 프로필"을 작게 보여주는 부품
defineProps({ active: { type: Array, default: () => [] } }) // 지금 검색어에 들어간 키워드
const emit = defineEmits(['loaded', 'pick'])

const p = ref(null)
const state = ref('loading') // loading | ok | empty | error

onMounted(async () => {
  try {
    p.value = (await client.get('/profile')).data
    state.value = 'ok'
    emit('loaded', p.value)
  } catch (e) {
    state.value = e.response?.status === 404 ? 'empty' : 'error'
  }
})

const range = () => {
  const { budget_min: a, budget_max: b } = p.value
  if (a == null && b == null) return '미입력'
  return `${a == null ? '' : won(a)} ~ ${b == null ? '' : won(b)}`
}
</script>

<template>
  <aside class="panel">
    <div class="panel-head">
      <strong>검색에 쓰는 회사 프로필</strong>
      <router-link to="/profile">수정</router-link>
    </div>

    <p v-if="state === 'loading'" class="meta">불러오는 중…</p>
    <p v-else-if="state === 'empty'" class="meta">저장된 프로필이 없습니다. <router-link to="/profile">프로필 입력하기</router-link></p>
    <p v-else-if="state === 'error'" class="meta">프로필을 불러오지 못했습니다.</p>

    <template v-else>
      <p v-if="p.corporate_name" style="margin: 0 0 8px"><strong>{{ p.corporate_name }}</strong></p>
      <dl>
        <dt>업종</dt><dd>{{ p.industry || '미입력' }}</dd>
        <dt>소재지</dt><dd>{{ p.region || '미입력' }}</dd>
        <dt>규모</dt><dd>{{ p.company_size || '미입력' }}</dd>
        <dt>희망 금액</dt><dd>{{ range() }}</dd>
      </dl>

      <h4>키워드 <span class="hint">(누르면 검색어에 추가)</span></h4>
      <div v-if="p.keywords?.length" class="chips">
        <button v-for="k in p.keywords" :key="k" type="button" class="chip" :class="{ on: active.includes(k) }" @click="emit('pick', k)">{{ k }}</button>
      </div>
      <p v-else class="meta">등록된 키워드가 없습니다.</p>

      <template v-if="p.licenses?.length || p.certs?.length">
        <h4>면허·인증</h4>
        <div class="chips">
          <span v-for="x in [...(p.licenses || []), ...(p.certs || [])]" :key="x" class="chip">{{ x }}</span>
        </div>
      </template>
    </template>
  </aside>
</template>
