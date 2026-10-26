<script setup>
import { reactive, ref, onMounted } from 'vue'
import client, { errorMessage } from '../api/client'
import { REGIONS, matchRegion } from '../utils'

// 쉼표로 구분해 입력받는 목록 항목 ("a, b" ↔ ["a", "b"])
const toList = (text) => text.split(',').map((s) => s.trim()).filter(Boolean)
const toText = (list) => (list || []).join(', ')

// 쉼표 목록으로 입력하는 항목들
const LIST_FIELDS = [
  { key: 'licenses', label: '보유 면허', hint: '쉼표로 구분', placeholder: '' },
  { key: 'certs', label: '기업 인증', hint: '쉼표로 구분 · 예: 벤처기업', placeholder: '' },
  { key: 'owned_docs', label: '보유 서류', hint: '쉼표로 구분', placeholder: '예: 사업자등록증 사본, 중소기업확인서' },
  { key: 'keywords', label: '관심 키워드', hint: '쉼표로 구분', placeholder: '예: 웹 구축, 모바일 앱, AI 챗봇' },
]
// 금액 단위: 값은 3번 점수 계산이 인정하는 이름 그대로 보냅니다.
const UNITS = [
  { value: 'KRW', label: '원' }, { value: '천원', label: '천원' },
  { value: '백만원', label: '백만원' }, { value: '억원', label: '억원' },
]

const form = reactive({
  industry: '', region: '', company_size: '', credit_rating: '',
  licenses: '', certs: '', owned_docs: '', keywords: '',
  budget_min: '', budget_max: '',
})
// 항목별 "없음" 체크: 체크하면 [](없음 확인), 체크도 입력도 없으면 보내지 않음(= 미확인).
// 3번 규칙에서 []는 "없음", 값 없음(null)은 "모름"이라 둘을 구분해야 공고가 잘못 제외되지 않습니다.
const none = reactive({ licenses: false, certs: false, owned_docs: false, keywords: false, track_records: false })
const trackRecords = ref([]) // 수행 실적: 줄 단위로 추가/삭제
const regionNotice = ref('')
const prefillNotice = ref('')

const error = ref('')
const saved = ref(false)
const loading = ref(false)

function onNone(key) {
  if (none[key]) {
    if (key === 'track_records') trackRecords.value = []
    else form[key] = ''
  }
}
function addRecord() {
  none.track_records = false
  trackRecords.value.push({ summary: '', completed_at: '', category: '', amount: '', amount_unit: 'KRW' })
}
function removeRecord(index) {
  trackRecords.value.splice(index, 1)
}

// 화면이 열리면 저장된 프로필이 있는지 불러옵니다. (없으면 빈 칸으로 시작)
onMounted(async () => {
  try {
    const { data } = await client.get('/profile')
    form.industry = data.industry || ''
    form.company_size = data.company_size || ''
    form.credit_rating = data.credit_rating || ''
    form.budget_min = data.budget_min ?? ''
    form.budget_max = data.budget_max ?? ''

    // 예전에 자유롭게 입력해 저장한 지역("울산광역시 남구" 등)을 시·도 목록에 맞춥니다.
    form.region = matchRegion(data.region)
    if (data.region && !form.region) regionNotice.value = `저장된 지역 "${data.region}"은 시·도 목록에 없어 비워 두었어요. 다시 선택해 주세요.`
    else if (data.region && form.region !== data.region) regionNotice.value = `저장된 지역 "${data.region}"을(를) "${form.region}"(으)로 맞췄어요. 저장하면 반영됩니다.`

    for (const f of LIST_FIELDS) {
      form[f.key] = toText(data[f.key])
      none[f.key] = Array.isArray(data[f.key]) && data[f.key].length === 0 // []는 "없음", null은 "미확인"
    }
    trackRecords.value = (data.track_records || []).map((r) => ({
      summary: r.summary ?? r.project_name ?? '', completed_at: r.completed_at ?? '', category: r.category ?? '',
      amount: r.amount ?? '', amount_unit: r.amount_unit || 'KRW',
    }))
    none.track_records = Array.isArray(data.track_records) && data.track_records.length === 0
  } catch (e) {
    // 404(프로필 없음)이거나 조회 API가 아직 없으면 그냥 빈 폼으로 둡니다.
  }
  await prefillFromSignup()
})

// 회원가입 때 입력한 업종·본점 소재지로 아직 비어 있는 칸을 미리 채웁니다. (확인 후 저장해야 반영됨)
// 1순위: 서버가 /auth/check 로 돌려주는 값(서버가 지원하면), 2순위: 가입할 때 이 브라우저에 보관해 둔 값
async function prefillFromSignup() {
  if (form.industry && form.region) return
  let info = null
  try {
    const { data } = await client.get('/auth/check')
    if (data && (data.head_office_address || data.business_item || data.business_type)) info = data
  } catch (e) { /* 서버가 아직 지원하지 않으면 다음 방법으로 */ }
  if (!info) {
    try { info = JSON.parse(localStorage.getItem('signup_info_' + (sessionStorage.getItem('bn') || '')) || 'null') } catch (e) { info = null }
  }
  if (!info) return
  const filled = []
  if (!form.industry && (info.business_item || info.business_type)) { form.industry = info.business_item || info.business_type; filled.push('업종') }
  if (!form.region && info.head_office_address) {
    const r = matchRegion(info.head_office_address)
    if (r) { form.region = r; filled.push('소재지') }
  }
  if (filled.length) prefillNotice.value = `가입할 때 입력한 정보로 ${filled.join('·')}를 채웠어요. 확인하고 저장해 주세요.`
}

async function onSubmit() {
  if (loading.value) return
  error.value = ''
  saved.value = false

  if (!form.industry.trim() || !form.company_size.trim()) {
    error.value = '업종과 기업 규모는 꼭 입력해 주세요.'
    return
  }
  if (!REGIONS.includes(form.region)) {
    error.value = '소재지를 시·도 목록에서 선택해 주세요.'
    return
  }
  const min = form.budget_min === '' ? null : Number(form.budget_min)
  const max = form.budget_max === '' ? null : Number(form.budget_max)
  if ((min !== null && min < 0) || (max !== null && max < 0)) {
    error.value = '금액은 0 이상이어야 합니다.'
    return
  }
  if (min !== null && max !== null && max < min) {
    error.value = '최대 금액은 최소 금액보다 작을 수 없습니다.'
    return
  }

  // 수행 실적: 점수 계산에 쓰이므로 입력한 줄은 4가지(내용·완료일·분야·금액)를 모두 요구합니다. 완전히 빈 줄은 버립니다.
  const records = []
  for (const [i, r] of trackRecords.value.entries()) {
    const any = r.summary.trim() || r.completed_at || r.category.trim() || r.amount !== ''
    if (!any) continue
    if (!r.summary.trim() || !r.completed_at || !r.category.trim() || r.amount === '' || Number(r.amount) < 0) {
      error.value = `수행 실적 ${i + 1}번째 줄: 사업 내용, 완료일, 분야, 금액(0 이상)을 모두 입력해 주세요.`
      return
    }
    records.push({
      summary: r.summary.trim(), completed_at: r.completed_at, category: r.category.trim(),
      amount: Number(r.amount), amount_unit: r.amount_unit,
    })
  }

  // 서버로 보낼 데이터
  const payload = { industry: form.industry.trim(), region: form.region, company_size: form.company_size.trim() }
  for (const f of LIST_FIELDS) {
    const list = toList(form[f.key])
    if (list.length) payload[f.key] = list
    else if (none[f.key]) payload[f.key] = [] // "없음"으로 확인한 항목만 빈 목록으로
  }
  if (records.length) payload.track_records = records
  else if (none.track_records) payload.track_records = []
  if (form.credit_rating.trim()) payload.credit_rating = form.credit_rating.trim()
  if (min !== null) payload.budget_min = min
  if (max !== null) payload.budget_max = max

  loading.value = true
  try {
    await client.put('/profile', payload)
    saved.value = true
    regionNotice.value = ''
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="card narrow">
    <h1>회사 프로필</h1>
    <p class="sub">입력한 정보로 우리 회사에 맞는 공고를 추립니다.</p>

    <form @submit.prevent="onSubmit">
      <label for="ind">업종 <span class="hint">필수</span></label>
      <input id="ind" v-model="form.industry" placeholder="예: 소프트웨어사업자(컴퓨터 관련 서비스사업)" />

      <div class="row">
        <div>
          <label for="reg">소재지(시·도) <span class="hint">필수</span></label>
          <select id="reg" v-model="form.region">
            <option value="" disabled>선택해 주세요</option>
            <option v-for="r in REGIONS" :key="r" :value="r">{{ r }}</option>
          </select>
        </div>
        <div>
          <label for="size">기업 규모 <span class="hint">필수</span></label>
          <input id="size" v-model="form.company_size" placeholder="예: 중소기업" />
        </div>
      </div>
      <p v-if="regionNotice" class="notice">{{ regionNotice }}</p>
      <p v-if="prefillNotice" class="notice">{{ prefillNotice }}</p>

      <template v-for="f in LIST_FIELDS" :key="f.key">
        <label :for="'f-' + f.key">{{ f.label }} <span class="hint">{{ f.hint }}</span></label>
        <input :id="'f-' + f.key" v-model="form[f.key]" :placeholder="f.placeholder" :disabled="none[f.key]" />
        <label class="check">
          <input v-model="none[f.key]" type="checkbox" @change="onNone(f.key)" />
          없음 (확인했고 해당 사항이 없어요)
        </label>
      </template>

      <label for="cr">신용등급</label>
      <input id="cr" v-model="form.credit_rating" />

      <div class="row">
        <div>
          <label for="bmin">희망 최소 금액 <span class="hint">원</span></label>
          <input id="bmin" v-model="form.budget_min" type="number" min="0" />
        </div>
        <div>
          <label for="bmax">희망 최대 금액 <span class="hint">원</span></label>
          <input id="bmax" v-model="form.budget_max" type="number" min="0" />
        </div>
      </div>

      <label>수행 실적 <span class="hint">분야는 공고 평가기준의 분야명과 같아야 점수가 계산돼요</span></label>
      <div v-for="(r, i) in trackRecords" :key="i" class="item" style="margin-top: 8px">
        <input v-model="r.summary" placeholder="사업 내용 (예: 민원 챗봇 구축)" aria-label="사업 내용" />
        <div class="row" style="margin-top: 8px">
          <div><input v-model="r.completed_at" type="date" aria-label="완료일" /></div>
          <div><input v-model="r.category" placeholder="분야 (예: 소프트웨어 개발)" aria-label="분야" /></div>
        </div>
        <div class="row" style="margin-top: 8px">
          <div><input v-model="r.amount" type="number" min="0" placeholder="금액" aria-label="금액" /></div>
          <div>
            <select v-model="r.amount_unit" aria-label="금액 단위">
              <option v-for="u in UNITS" :key="u.value" :value="u.value">{{ u.label }}</option>
            </select>
          </div>
          <div style="flex: 0"><button type="button" class="small" @click="removeRecord(i)">삭제</button></div>
        </div>
      </div>
      <button type="button" class="small" style="margin-top: 8px" @click="addRecord">실적 추가</button>
      <label class="check">
        <input v-model="none.track_records" type="checkbox" @change="onNone('track_records')" />
        없음 (확인했고 해당 사항이 없어요)
      </label>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="saved" class="ok">프로필을 저장했습니다.</p>
      <button class="primary" :disabled="loading">{{ loading ? '저장 중…' : '프로필 저장' }}</button>
    </form>
  </div>
</template>
