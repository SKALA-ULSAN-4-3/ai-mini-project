// 여러 화면에서 같이 쓰는 도우미 함수 모음
export const won = (n) => (n == null ? '-' : Number(n).toLocaleString('ko-KR') + '원')
export const iso = (d) => d.toLocaleDateString('sv-SE') // 'YYYY-MM-DD'
export function addDays(base, n) {
  const d = new Date(base)
  d.setDate(d.getDate() + n)
  return d
}
// 마감일까지 남은 날짜: 'D-12', 'D-day', '마감'
export function dday(dateStr) {
  const diff = Math.round((new Date(String(dateStr).slice(0, 10)) - new Date(iso(new Date()))) / 86400000)
  return diff > 0 ? `D-${diff}` : diff === 0 ? 'D-day' : '마감'
}

// 공고 하나를 구분하는 키: 공고번호 + 차수(문자열, 앞의 0 유지)
export const keyOf = (b) => `${b.bid_no}|${b.revision}`

// 'YYYY-MM-DDTHH:mm...' → 'YYYY-MM-DD'
export const ymd = (s) => (s ? String(s).slice(0, 10) : '-')
// 서버가 계산해 준 d_day(숫자) → 'D-5' / 'D-day' / '마감' / '미확인'
export const ddayText = (n) => (n == null ? '미확인' : n > 0 ? `D-${n}` : n === 0 ? 'D-day' : '마감')
// 3번이 돌려주는 "확인하지 못한 조건" 문구를 알아보기 쉽게 바꿉니다.
const WORDS = { industries: '업종', regions: '지역', licenses: '면허', company_sizes: '기업 규모', certs: '인증', industry: '업종', region: '지역', company_size: '기업 규모' }
export const unknownLabel = (s) => String(s).replace(/\b[a-z_]+\b/g, (w) => WORDS[w] || w)

// 3번(공고 로직)이 인정하는 시·도 17개. 이 밖의 값("울산광역시 남구" 등)은 공고 추천이 거부(422)됩니다.
export const REGIONS = [
  '서울특별시', '부산광역시', '대구광역시', '인천광역시', '광주광역시', '대전광역시', '울산광역시', '세종특별자치시',
  '경기도', '강원특별자치도', '충청북도', '충청남도', '전북특별자치도', '전라남도', '경상북도', '경상남도', '제주특별자치도',
]
const REGION_ALIASES = { 세종시: '세종특별자치시', 강원도: '강원특별자치도', 전라북도: '전북특별자치도', 제주도: '제주특별자치도' }
const REGION_SHORT = {
  서울: '서울특별시', 부산: '부산광역시', 대구: '대구광역시', 인천: '인천광역시', 광주: '광주광역시', 대전: '대전광역시',
  울산: '울산광역시', 세종: '세종특별자치시', 경기: '경기도', 강원: '강원특별자치도', 충북: '충청북도', 충남: '충청남도',
  전북: '전북특별자치도', 전남: '전라남도', 경북: '경상북도', 경남: '경상남도', 제주: '제주특별자치도',
}
// 예전에 저장된 지역값을 시·도 목록의 값으로 맞춥니다. 맞출 수 없으면 '' 를 돌려줍니다.
export function matchRegion(value) {
  const v = String(value ?? '').trim()
  if (!v) return ''
  if (REGIONS.includes(v)) return v
  if (REGION_ALIASES[v]) return REGION_ALIASES[v]
  if (REGION_SHORT[v]) return REGION_SHORT[v]
  // "울산광역시 남구"처럼 뒤에 시·군·구가 붙은 값은 앞부분의 시·도로 맞춥니다.
  const hit = [...REGIONS, ...Object.keys(REGION_ALIASES)].find((n) => v.startsWith(n + ' ') || v.startsWith(n))
  if (hit) return REGION_ALIASES[hit] || hit
  const short = Object.keys(REGION_SHORT).find((n) => v.startsWith(n + ' '))
  return short ? REGION_SHORT[short] : ''
}
