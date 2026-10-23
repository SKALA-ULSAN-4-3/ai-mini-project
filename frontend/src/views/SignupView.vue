<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import client, { errorMessage } from '../api/client'

const router = useRouter()

// reactive(): 여러 입력값을 한 묶음으로 관리합니다. (form.password 처럼 접근)
const form = reactive({
  business_registration_number: '',
  password: '',
  corporate_name: '',
  head_office_address: '',
  business_type: '',
  business_item: '',
  unit_taxpayer_applicable: '부',
})
const error = ref('')
const loading = ref(false)

function validate(data) {
  if (data.business_registration_number.length !== 10) return '사업자등록번호는 숫자 10자리입니다.'
  if (data.password.length < 8 || data.password.length > 100) return '비밀번호는 8~100자로 입력해 주세요.'
  if (!data.corporate_name) return '법인명을 입력해 주세요.'
  if (!data.head_office_address) return '본점 소재지를 입력해 주세요.'
  if (!data.business_type) return '업태를 입력해 주세요.'
  if (!data.business_item) return '업종을 입력해 주세요.'
  return ''
}

async function onSubmit() {
  error.value = ''
  // 서버로 보낼 데이터 만들기: 사업자번호는 숫자만 남기고, 나머지는 앞뒤 공백 제거
  const data = {
    business_registration_number: form.business_registration_number.replace(/\D/g, ''),
    password: form.password,
    corporate_name: form.corporate_name.trim(),
    head_office_address: form.head_office_address.trim(),
    business_type: form.business_type.trim(),
    business_item: form.business_item.trim(),
    unit_taxpayer_applicable: form.unit_taxpayer_applicable,
  }

  const message = validate(data)
  if (message) {
    error.value = message
    return
  }

  loading.value = true
  try {
    await client.post('/signup', data)
    alert('가입이 완료되었습니다. 로그인해 주세요.')
    router.push('/login')
  } catch (e) {
    error.value = errorMessage(e, { 409: '이미 가입된 사업자등록번호입니다.' })
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card narrow">
    <h1>회원가입</h1>
    <p class="sub">모든 항목이 필수입니다.</p>

    <form @submit.prevent="onSubmit">
      <label for="bn">사업자등록번호 <span class="hint">하이픈 없이 10자리</span></label>
      <input id="bn" v-model="form.business_registration_number" inputmode="numeric" />

      <label for="pw">비밀번호 <span class="hint">8자 이상</span></label>
      <input id="pw" v-model="form.password" type="password" autocomplete="new-password" />

      <label for="cn">법인명</label>
      <input id="cn" v-model="form.corporate_name" />

      <label for="ad">본점 소재지</label>
      <input id="ad" v-model="form.head_office_address" />

      <div class="row">
        <div>
          <label for="bt">업태</label>
          <input id="bt" v-model="form.business_type" placeholder="예: 정보통신업" />
        </div>
        <div>
          <label for="bi">업종</label>
          <input id="bi" v-model="form.business_item" placeholder="예: 소프트웨어 개발" />
        </div>
      </div>

      <label for="ut">사업자 단위 과세 적용 여부</label>
      <select id="ut" v-model="form.unit_taxpayer_applicable">
        <option value="부">부</option>
        <option value="여">여</option>
      </select>

      <p v-if="loading" class="meta" style="margin-top: 10px">서버가 잠들어 있으면 첫 요청에 30~60초 걸릴 수 있어요.</p>
      <p v-if="error" class="error">{{ error }}</p>
      <button class="primary" :disabled="loading">{{ loading ? '가입 중…' : '가입하기' }}</button>
    </form>

    <p class="foot">이미 계정이 있나요? <router-link to="/login">로그인</router-link></p>
  </div>
</template>
