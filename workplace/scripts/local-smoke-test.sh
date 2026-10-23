#!/usr/bin/env bash

# 로컬 Docker 환경에서 실제 PostgreSQL을 사용해 핵심 인증 흐름을 검증합니다.
# 테스트가 끝나면 이 스크립트가 만든 회원 한 명과 연결된 프로필을 삭제합니다.
set -euo pipefail

readonly API_BASE_URL="${API_BASE_URL:-http://localhost:8080}"
readonly POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-ai-mini-postgres}"

for command_name in curl jq docker; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "필수 명령을 찾을 수 없습니다: ${command_name}" >&2
    exit 1
  fi
done

# 현재 초 단위 시각은 10자리 숫자이므로 테스트용 사업자등록번호로 사용합니다.
# 실행할 때마다 값이 달라 실제 개발 데이터와 충돌할 가능성을 줄입니다.
readonly TEST_BUSINESS_NUMBER="$(date +%s)"
readonly TEST_PASSWORD="smoke-test-password-123!"

cleanup() {
  local cleanup_sql
  cleanup_sql="DELETE FROM users WHERE business_registration_number = '${TEST_BUSINESS_NUMBER}';"

  # users 삭제 시 외래키 ON DELETE CASCADE가 테스트 프로필도 함께 정리합니다.
  docker exec \
    --env "CLEANUP_SQL=${cleanup_sql}" \
    "${POSTGRES_CONTAINER}" \
    sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --command="$CLEANUP_SQL"' \
    >/dev/null 2>&1 || true
}
trap cleanup EXIT

curl --fail --silent --show-error \
  "${API_BASE_URL}/api/health/ready" \
  >/dev/null

signup_payload="{
    \"business_registration_number\": \"${TEST_BUSINESS_NUMBER}\",
    \"password\": \"${TEST_PASSWORD}\",
    \"corporate_name\": \"통합 테스트 주식회사\",
    \"head_office_address\": \"울산광역시 남구\",
    \"business_type\": \"정보통신업\",
    \"business_item\": \"소프트웨어 개발 및 공급업\",
    \"unit_taxpayer_applicable\": \"부\"
  }"

signup_response="$(curl --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "${signup_payload}" \
  "${API_BASE_URL}/api/signup")"

# PostgreSQL의 UNIQUE 위반(SQLState 23505)이 공통 409 오류로 변환되는지
# 확인합니다. 응답 본문은 버리고 상태 코드만 검사해 테스트 로그를 간결하게 둡니다.
duplicate_signup_status="$(curl --silent --show-error \
  --output /dev/null \
  --write-out '%{http_code}' \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "${signup_payload}" \
  "${API_BASE_URL}/api/signup")"

if [[ "${duplicate_signup_status}" != "409" ]]; then
  echo "중복 회원가입 응답이 409가 아닙니다: ${duplicate_signup_status}" >&2
  exit 1
fi

login_response="$(curl --fail-with-body --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data "{
    \"business_registration_number\": \"${TEST_BUSINESS_NUMBER}\",
    \"password\": \"${TEST_PASSWORD}\"
  }" \
  "${API_BASE_URL}/api/login")"

access_token="$(printf '%s' "${login_response}" | jq --exit-status --raw-output '.access_token')"

auth_response="$(curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${access_token}" \
  "${API_BASE_URL}/api/auth/check")"

curl --fail-with-body --silent --show-error \
  --request PUT \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer ${access_token}" \
  --data '{
    "industry": "소프트웨어 개발",
    "licenses": ["소프트웨어사업자"],
    "region": "울산광역시",
    "company_size": "중소기업",
    "certs": ["벤처기업"],
    "credit_rating": "A",
    "track_records": [],
    "owned_docs": ["사업자등록증"],
    "budget_min": 10000000,
    "budget_max": 100000000,
    "keywords": ["AI", "소프트웨어"]
  }' \
  "${API_BASE_URL}/api/profile" \
  >/dev/null

profile_response="$(curl --fail-with-body --silent --show-error \
  --header "Authorization: Bearer ${access_token}" \
  "${API_BASE_URL}/api/profile")"

printf '%s' "${signup_response}" \
  | jq --exit-status --arg number "${TEST_BUSINESS_NUMBER}" \
      '.business_registration_number == $number' \
  >/dev/null
printf '%s' "${login_response}" \
  | jq --exit-status '.token_type == "Bearer" and (.expires_in > 0)' \
  >/dev/null
printf '%s' "${auth_response}" \
  | jq --exit-status --arg number "${TEST_BUSINESS_NUMBER}" \
      '.ok == true and .business_registration_number == $number' \
  >/dev/null
printf '%s' "${profile_response}" \
  | jq --exit-status --arg number "${TEST_BUSINESS_NUMBER}" \
      '.business_registration_number == $number and .industry == "소프트웨어 개발"' \
  >/dev/null

echo "로컬 통합 테스트 성공"
echo "- PostgreSQL 준비 상태"
echo "- 회원가입"
echo "- 중복 사업자등록번호 409 오류 처리"
echo "- 로그인 및 JWT 발급"
echo "- Bearer JWT 검증"
echo "- 회사 프로필 저장 및 조회"
