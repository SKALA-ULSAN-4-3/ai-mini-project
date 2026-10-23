import axios from 'axios'
import { installMock } from './mock'

// 서버 통신 창구를 만드는 함수. 토큰 첨부와 401 처리를 공통으로 넣습니다.
function makeClient(baseURL) {
  const c = axios.create({ baseURL })

  // [요청 직전] 토큰이 있으면 출입증(Bearer)을 헤더에 붙임
  c.interceptors.request.use((config) => {
    const token = sessionStorage.getItem('token')
    if (token) config.headers.Authorization = `Bearer ${token}`
    return config
  })

  // [응답 직후] 401이면 토큰을 지우고 로그인 화면으로 (로그인 요청 자체는 제외)
  c.interceptors.response.use(
    (res) => res,
    (error) => {
      const isLogin = error.config?.url === '/login'
      if (error.response?.status === 401 && !isLogin) {
        sessionStorage.removeItem('token')
        sessionStorage.removeItem('flow')
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
  )

  // VITE_USE_MOCK: 'true' = 전부 가짜 / 'partial' = 1번·4번 API만 가짜 / 'me' = 4번 API만 가짜 / 그 외 = 전부 실제 서버
  const mock = import.meta.env.VITE_USE_MOCK
  if (['true', 'partial', 'me', 'auth'].includes(mock)) installMock(c, mock)
  return c
}

// 개발: 주소를 안 적으면 '/api' → vite 프록시가 :8080 으로 전달
// 배포: .env.production 에 실제 서버 주소를 적으면 그 주소로 직접 요청
const AUTH_URL = import.meta.env.VITE_AUTH_URL || '/api'
const RAG_URL = import.meta.env.VITE_RAG_URL || '/rag'
const client = makeClient(AUTH_URL) // 가입·로그인·프로필
export const rag = makeClient(RAG_URL) // RAG 서버(:8001): 공고·요약·채점표·Q&A

// 서버 오류를 사용자에게 보여줄 문장으로 바꿔 주는 도우미
export function errorMessage(error, messages = {}) {
  const status = error.response?.status
  if (!error.response) return '서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요.'
  if (messages[status]) return messages[status]
  if (status === 400) return '입력값이 올바르지 않습니다. 내용을 다시 확인해 주세요.'
  if (status === 401) return '인증에 실패했습니다.'
  if (status === 404) return '요청한 대상을 찾을 수 없습니다.'
  if (status === 503) return '데이터 연동에 문제가 있습니다. 잠시 후 다시 시도해 주세요.'
  return `요청을 처리하지 못했습니다. (오류 코드 ${status})`
}

export default client
