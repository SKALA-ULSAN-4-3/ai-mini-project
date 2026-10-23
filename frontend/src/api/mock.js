// 가짜 백엔드: 서버 없이(또는 서버에 아직 없는 API만) 화면을 테스트하기 위한 파일입니다.
//  VITE_USE_MOCK=true    → 모든 요청을 가짜로 처리 (서버가 하나도 없어도 화면 전체 테스트)
//  VITE_USE_MOCK=partial → 1번(검색·적재·작업)과 4번(선택·승인) API만 가짜, 나머지는 실제 서버
//  VITE_USE_MOCK=me      → 4번(선택·승인 /me/...)만 가짜, 1번까지 실제 서버 (1번 브랜치를 합친 뒤)
//  VITE_USE_MOCK=auth    → 회원가입·로그인·프로필(/signup /login /profile)만 실제 서버, 나머지는 전부 가짜
//  그 외(false 등)       → 가짜 없이 전부 실제 서버
// 데이터는 브라우저(localStorage)에 저장되므로 새로고침해도 유지됩니다.
import axios from 'axios'
import { handlePipeline, handleBidData } from './mockFlow'

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const load = (key, fallback) => JSON.parse(localStorage.getItem(key) || fallback)

// 서버가 돌려주는 "성공/실패 응답"을 흉내 내는 함수
function ok(config, data, status = 200) {
  return { data, status, statusText: 'OK', headers: {}, config }
}
function fail(config, status, detail) {
  const error = new Error(`mock ${status}`)
  error.config = config
  error.response = { status, data: { detail } }
  return error
}

// 서버에 아직 없는 API 주소들
const PIPELINE = [/^\/search-bids$/, /^\/fetch-notices$/, /^\/fetch-documents$/, /^\/jobs\//, /^\/me\//]
const ME_ONLY = [/^\/me\//]
const AUTH_REAL = [/^\/signup$/, /^\/login$/, /^\/profile$/] // auth 모드에서 진짜 서버로 보내는 주소

// auth 모드에서 "가입·로그인·프로필 서버"로 요청을 보내는 통로. 맨 처음 만든 창구(/api)가 등록합니다.
let authReal = null
let authBase = ''

export function installMock(client, mode = 'true') {
  // 진짜 서버로 보내는 원래 통신 방식을 저장해 둡니다. (partial 모드에서 사용)
  const real = axios.getAdapter(client.defaults.adapter)
  if (mode === 'auth' && !authReal) {
    authReal = real
    authBase = client.defaults.baseURL
  }

  // adapter: axios가 "실제로 서버에 요청을 보내는 부분". 이걸 가짜로 갈아 끼웁니다.
  client.defaults.adapter = async (config) => {
    const url = config.url
    const method = config.method
    const isPipeline = (mode === 'me' ? ME_ONLY : PIPELINE).some((r) => r.test(url))
    const isAuthMode = mode === 'auth'

    // auth 모드: 가입·로그인·프로필만 진짜 서버로 보냅니다.
    if (mode === 'auth' && AUTH_REAL.some((r) => r.test(url))) return real(config)

    // partial · me 모드: 서버에 이미 있는 API는 진짜 서버로 보냅니다.
    if ((mode === 'partial' || mode === 'me') && !isPipeline) return real(config)

    await delay(300) // 실제 서버처럼 약간 기다리기 (로딩 표시 확인용)
    const body = config.data ? JSON.parse(config.data) : {}

    if (isPipeline) {
      const hit = handlePipeline({ config, url, method, body, ok, fail })
      if (hit) return hit
    }

    const users = load('mock_users', '{}') // { 사업자번호: 비밀번호 }

    // 1. 회원가입
    if (url === '/signup' && method === 'post') {
      const number = String(body.business_registration_number || '').replace(/\D/g, '')
      if (number.length !== 10) throw fail(config, 400, '사업자등록번호는 숫자 10자리')
      if (!body.password || body.password.length < 8) throw fail(config, 400, '비밀번호는 8자 이상')
      if (!['여', '부'].includes(body.unit_taxpayer_applicable)) throw fail(config, 400, '여/부만 가능')
      if (users[number]) throw fail(config, 409, '이미 가입된 번호')
      users[number] = body.password
      localStorage.setItem('mock_users', JSON.stringify(users))
      return ok(config, { business_registration_number: number, corporate_name: body.corporate_name }, 201)
    }

    // 2. 로그인: 가입한 번호와 비밀번호가 맞으면 가짜 토큰을 줍니다.
    if (url === '/login' && method === 'post') {
      const number = String(body.business_registration_number || '').replace(/\D/g, '')
      if (users[number] !== body.password) throw fail(config, 401, '로그인 실패')
      return ok(config, { access_token: `mock-token-${number}`, token_type: 'Bearer', expires_in: 3600 })
    }

    // 3. 프로필 이하: 토큰(출입증)이 없으면 401
    const auth = config.headers?.Authorization || ''
    // auth 모드: 토큰은 진짜 서버가 준 것이므로 가짜 토큰 검사를 건너뛰고, 프로필은 진짜 서버에서 읽어 옵니다.
    if (!isAuthMode && !auth.startsWith('Bearer mock-token-')) throw fail(config, 401, '토큰 오류')
    const owner = auth.replace('Bearer mock-token-', '')
    const profiles = load('mock_profiles', '{}')
    if (isAuthMode) {
      try {
        const res = await authReal({ ...config, baseURL: authBase, url: '/profile', method: 'get', data: undefined, params: undefined })
        profiles[owner] = res.data
      } catch {
        delete profiles[owner] // 프로필이 없으면(404) 없는 상태로 둡니다.
      }
    }

    if (url === '/profile' && method === 'put') {
      if (!body.industry || !body.region || !body.company_size) throw fail(config, 400, '필수 항목 누락')
      profiles[owner] = body
      localStorage.setItem('mock_profiles', JSON.stringify(profiles))
      return ok(config, body)
    }
    if (url === '/profile' && method === 'get') {
      if (!profiles[owner]) throw fail(config, 404, '프로필 없음')
      return ok(config, profiles[owner])
    }

    const extra = handleBidData({ config, url, method, body, profile: profiles[owner], ok, fail })
    if (extra) return extra

    throw fail(config, 404, `mock에 없는 주소: ${method} ${url}`)
  }
}
