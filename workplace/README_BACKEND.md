# Workplace Java 백엔드

`workplace`는 사업자 회원가입·로그인, Bearer JWT 발급·검증, 회사 프로필,
공고 요약·원본 문서, 공고 선택·승인 상태와 공통 오류 처리를 담당합니다.
PDF 청킹, FAISS 검색, 프롬프트와 LLM 호출은 RAG 담당 영역이므로 이 모듈에
포함하지 않습니다.

- 배포 주소: <https://ai-service-mini-backend.onrender.com>

## 패키지 책임

- `config`: 환경 설정
- `domain`: 요청·응답과 사용자·프로필·공고 데이터
- `repository`: JDBC 데이터 접근
- `service`: 인증, 프로필, 공고 요약·문서, 선택·승인 업무 규칙
- `security`: JWT 생성·검증
- `web.handler`: 엔드포인트별 HTTP 처리
- `storage`: Supabase Storage를 통한 공고 원본 PDF 보관
- `web`: JSON, Bearer·서비스 키 인증, CORS, 오류 처리와 요청 로그
- `WorkplaceApplication`: 객체 조립과 엔드포인트 등록

## 회원 테이블

`database/schema.sql`의 `users` 테이블에 아래 값을 모두 필수로 저장합니다.

| DB 열 | 의미 | 규칙 |
|---|---|---|
| `business_registration_number` | 사업자등록번호 | PK, 하이픈 없는 숫자 10자리 |
| `password` | 비밀번호 | BCrypt 해시만 저장 |
| `corporate_name` | 법인명 | 필수 |
| `head_office_address` | 본점 소재지 | 필수 |
| `business_type` | 업태 | 필수 |
| `business_item` | 업종 | 필수 |
| `unit_taxpayer_applicable` | 사업자 단위 과세 적용 여부 | `여` 또는 `부` |

사업자등록번호 `123-45-67890`과 `1234567890`은 같은 값으로 정규화합니다.

## 데이터 테이블

| 테이블 | 역할 | 사용자 분리 기준 |
| --- | --- | --- |
| `users` | 회원 인증과 필수 법인 정보 | 사업자등록번호 PK |
| `company_profiles` | 추천에 사용하는 회사 프로필 | 사업자등록번호 UNIQUE·FK |
| `bid_summaries` | 사용자별 공고 요약 | 사업자번호·공고번호·차수 복합 PK |
| `bid_documents` | 공고 원본 PDF의 Storage 메타데이터 | 공고번호·차수·파일명 UNIQUE |
| `user_bid_pipeline` | 사용자별 공고 선택·승인 상태 | 사업자번호·공고번호·차수 복합 PK |
| `bid_search_cache` | 회사 프로필 기반 최종 검색 결과의 24시간 캐시 | 사업자번호·요청 해시 복합 PK |
| `bid_rfp_cache` | 제안요청서 다운로드·변환 결과의 24시간 공용 캐시 | 공고번호·차수 복합 PK |

회원가입의 `head_office_address`는 `울산광역시 남구`와 같은 상세 소재지 자유
입력입니다. 추천 조건에 사용하는 회사 프로필의 `region`은 별도 필드이며,
프론트엔드의 대한민국 17개 시·도 드롭다운 값만 저장합니다.

## API

| 메서드 | 경로 | 설명 | 인증 |
|---|---|---|---|
| POST | `/api/signup` | 사업자 회원가입 | 불필요 |
| POST | `/api/login` | 로그인 및 JWT 발급 | 불필요 |
| GET | `/api/auth/check` | 현재 JWT 확인·가입 기본정보 조회 | Bearer JWT |
| GET | `/api/profile` | 회사 프로필 조회 | Bearer JWT |
| PUT | `/api/profile` | 회사 프로필 생성·수정 | Bearer JWT |
| POST | `/api/me/selections` | 공고 선택 상태 저장 | Bearer JWT |
| POST | `/api/me/approvals` | 선택된 공고 승인 | Bearer JWT |
| GET | `/api/me/pipeline` | 내 선택·승인 목록 | Bearer JWT |
| GET | `/api/bids` | 내 공고 요약 목록 | Bearer JWT |
| GET | `/api/bids/{bid_no}/summary` | 공고 요약 상세·PDF 링크 | Bearer JWT |
| PUT | `/api/bids/{bid_no}/summary` | 공고 요약 저장·수정 | Bearer JWT |
| GET | `/api/bids/{bid_no}/documents` | 원본 PDF 목록·임시 링크 | JWT 또는 서비스 키 |
| POST | `/api/bids/{bid_no}/documents` | 원본 PDF 업로드 | 서비스 키 |
| POST | `/api/cache/search/lookup` | 회사별 공고 검색 캐시 조회 | 서비스 키 + Bearer JWT |
| PUT | `/api/cache/search` | 회사별 공고 검색 결과 캐시 저장 | 서비스 키 + Bearer JWT |
| GET | `/api/cache/rfp/{bid_no}` | 공고·차수별 제안요청서 캐시 조회 | 서비스 키 |
| PUT | `/api/cache/rfp/{bid_no}` | 공고·차수별 제안요청서 캐시 저장 | 서비스 키 |
| GET | `/api/health` | API·DB 준비 상태 | 불필요 |
| GET | `/api/health/ready` | API·DB 준비 상태 | 불필요 |
| GET | `/api/health/live` | Java 프로세스 생존 상태 | 불필요 |

### 회원가입

```http
POST /api/signup
Content-Type: application/json

{
  "business_registration_number": "123-45-67890",
  "password": "password123!",
  "corporate_name": "예시 주식회사",
  "head_office_address": "울산광역시 남구",
  "business_type": "정보통신업",
  "business_item": "소프트웨어 개발 및 공급업",
  "unit_taxpayer_applicable": "부"
}
```

성공 시 HTTP 201과 아래처럼 비밀번호를 제외한 식별 정보만 반환합니다.

```json
{
  "business_registration_number": "1234567890",
  "corporate_name": "예시 주식회사"
}
```

### 로그인 및 토큰 발급

```http
POST /api/login
Content-Type: application/json

{
  "business_registration_number": "123-45-67890",
  "password": "password123!"
}
```

```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

로그인 이후 보호 API에는 토큰을 다음과 같이 전달합니다.

```http
Authorization: Bearer eyJ...
```

### JWT 및 가입 기본정보 확인

프론트엔드는 로그인 상태를 복원할 때 아래 API로 JWT를 검증하고, 회원가입 때
저장한 본점 소재지·업태·업종을 함께 조회할 수 있습니다.

```http
GET /api/auth/check
Authorization: Bearer eyJ...
```

```json
{
  "ok": true,
  "business_registration_number": "1234567890",
  "corporate_name": "예시 주식회사",
  "head_office_address": "울산광역시 남구",
  "business_type": "정보통신업",
  "business_item": "소프트웨어 개발 및 공급업"
}
```

JWT에서 사용자 식별값을 검증한 뒤 `users` 테이블에서 최신 가입 정보를 조회합니다.
따라서 기존에 발급한 토큰도 다시 로그인하지 않고 사용할 수 있으며,
`company_profiles`가 아직 생성되지 않은 사용자도 위 세 가지 기본정보를 받을 수
있습니다.

로그아웃 API는 별도로 두지 않습니다. 클라이언트가 보관한 Access Token을
삭제하면 로그아웃됩니다. 운영 환경의 브라우저 토큰 보관 방식은 프론트엔드와
보안 정책을 함께 정해야 하며, 예제 로그인 화면은 개발 확인용으로
`sessionStorage`만 사용합니다.

## 인증과 공통 응답

- 사용자 보호 API: `Authorization: Bearer <access_token>`
- PDF 업로드 서버 간 인증: `X-Service-Key: <service_api_key>`
- JWT 알고리즘: HMAC-SHA256
- JWT 기본 만료 시간: 3,600초
- 비밀번호: BCrypt cost 12 해시만 저장
- JSON 필드명: `snake_case`
- 오류 본문: `code`, `message`, `request_id`
- 요청 로그: 메서드·경로·상태·처리 시간만 기록하고 JWT와 본문은 제외

## 검색·제안요청서 24시간 캐시

캐시 API는 브라우저가 직접 호출하지 않고 데이터 파이프라인·RAG 서버가 사용합니다.
검색 캐시는 회사 프로필에 따라 결과가 달라지므로 서비스 키와 사용자 JWT를 모두
검증합니다. 제안요청서는 공용 자료이므로 서비스 키로 인증하고 `bid_no`와
정정공고 `revision`을 기준으로 모든 회사가 같은 처리 결과를 재사용합니다.

### 공고 검색 캐시 조회

```http
POST /api/cache/search/lookup
Authorization: Bearer <사용자 토큰>
X-Service-Key: <서비스 키>
Content-Type: application/json

{
  "from": "2026-10-01",
  "to": "2026-10-26",
  "queries": ["AI", "소프트웨어"],
  "limit": 100
}
```

캐시 적중과 미스는 모두 HTTP 200입니다. 미스는 오류가 아니므로 기존 검색을
실행하면 됩니다.

```json
{
  "cached": false,
  "result": null,
  "created_at": null,
  "expires_at": null
}
```

검색어는 서버에서 공백·유니코드·대소문자·중복·순서를 정규화합니다. 캐시 키에는
검색 기간, 검색어, 조회 한도와 회사 프로필의 `updated_at` 지문이 들어갑니다.
따라서 프로필이 수정되면 이전 결과가 남아 있어도 자동으로 캐시 미스가 됩니다.

`search_id`만 캐시해서 그대로 돌려주면 안 됩니다. 현재 데이터 파이프라인의
`search_id`는 Render 인스턴스의 검색 스냅샷을 가리키므로 재시작 후 파일이 없어질
수 있습니다. 캐시 `result`에 후속 다운로드에 필요한 원본 공고·첨부 메타데이터도
포함하고, 캐시 적중 시 새 검색 스냅샷과 `search_id`를 복원하거나 후속 API가 캐시된
원본 데이터를 직접 읽도록 연결해야 합니다.

### 공고 검색 캐시 저장

조회와 같은 조건에 최종 화면 응답을 `result`로 추가합니다. 나라장터 검색 결과와
회사 프로필 기반 추천이 모두 끝난 뒤 저장해야 다음 요청에서 두 단계를 함께
생략할 수 있습니다.

```http
PUT /api/cache/search
Authorization: Bearer <사용자 토큰>
X-Service-Key: <서비스 키>
Content-Type: application/json

{
  "from": "2026-10-01",
  "to": "2026-10-26",
  "queries": ["AI", "소프트웨어"],
  "limit": 100,
  "result": {
    "search_id": "검색 ID",
    "items": [],
    "bids": [],
    "excluded": []
  }
}
```

### 제안요청서 캐시 조회·저장

```http
GET /api/cache/rfp/R26BK01789933?revision=000
X-Service-Key: <서비스 키>
```

```http
PUT /api/cache/rfp/R26BK01789933
X-Service-Key: <서비스 키>
Content-Type: application/json

{
  "revision": "000",
  "result": {
    "status": "completed",
    "documents": []
  }
}
```

PDF·HWP 원본은 JSONB에 넣지 않습니다. `result`에는 외부 Storage의 영구 식별자인
`storage_key`, 파일명, 처리 상태와 화면에 필요한 메타데이터만 저장합니다. 만료될
수 있는 서명 URL은 캐시하지 않고 조회할 때 새로 발급해야 합니다. 두 캐시는 저장
시점부터 24시간 동안 유효하며, 모든 캐시 조회·저장 시 만료 행을 조회 대상에서
제외하고 `purge_expired_bid_caches()`로 물리 삭제합니다.

## 현재 연동 상태

Java 백엔드의 선택·승인 API와 `user_bid_pipeline` 테이블은 Vue 프론트엔드에
연결되어 있습니다. 프론트엔드는 공고별로 선택·승인을 서버에 저장하고, 로그인 후
`GET /api/me/pipeline`으로 사용자 상태를 복원합니다. 선택 취소와 승인 철회 API는
아직 없습니다.

공고 요약은 프론트엔드가 사용자의 Bearer JWT로
`PUT /api/bids/{bid_no}/summary`를 호출해 저장하고, 요약 상세 화면은 원본 PDF
목록을 조회합니다. 원본 PDF 업로드 엔드포인트는 데이터 파이프라인의 서버 간 호출용으로
구현되어 있지만, 최신 `develop`에서 실제 업로드 호출 연결은 확인되지 않습니다.

FastAPI RAG 서버는 `BACKEND_URL`이 설정된 경우 프론트에서 받은 Bearer Token을
Java 백엔드의 `/api/auth/check` 또는 `/api/profile`로 전달합니다. JWT 비밀키를
RAG 서버에 중복 보관하지 않고 Java 백엔드가 토큰 검증과 프로필 원본 조회를 담당합니다.

백엔드의 검색·제안요청서 캐시 API와 Aiven 테이블은 구현되어 있습니다. 실제 속도
개선을 위해서는 데이터 파이프라인·RAG 서버가 작업 전에 캐시를 조회하고, 캐시가
없을 때만 기존 작업을 수행한 뒤 최종 결과를 저장하도록 연결해야 합니다. 기존
프론트 응답 형식을 `result`에 그대로 저장하고 캐시 적중 시 그대로 반환하면
프론트엔드 변경은 필요하지 않습니다.

## 실행 준비

로컬 개발에서는 Docker Compose로 PostgreSQL과 테이블을 한 번에 생성할 수 있습니다.

```bash
docker compose up -d postgres
docker compose ps
```

처음 생성되는 DB 볼륨에는 `database/schema.sql`이 자동 적용됩니다. 이후 아래
명령으로 `.env`를 현재 셸에 불러온 다음 테스트하고 백엔드를 실행합니다.

```bash
set -a
source .env
set +a

./gradlew :app:test
./gradlew :app:run --no-configuration-cache
```

Java 백엔드와 PostgreSQL을 모두 Docker로 실행하고 실제 인증 흐름까지 확인하려면
다음 명령을 사용합니다.

```bash
docker compose up -d --build
./scripts/local-smoke-test.sh
```

통합 테스트는 회원가입, 로그인, JWT 검증, 회사 프로필 저장·조회를 확인하고
자신이 만든 테스트 데이터만 종료 시 삭제합니다.

현재 Java 테스트 소스는 JWT, 인증 서비스, 인증 확인 응답의 가입 기본정보,
회사 프로필 서비스, 공고 API와 캐시 키·서비스 키·JWT 격리를 검증합니다.
`scripts/local-smoke-test.sh`는 실제 HTTP 서버와 PostgreSQL을 연결해 회원가입,
중복 가입, 로그인, JWT 확인과 프로필 저장·조회를 점검합니다.

`CREATE TABLE IF NOT EXISTS`는 기존 테이블 구조를 변경하지 않습니다. 예전
`id/username` 구조의 테이블을 이미 생성했다면 데이터를 백업한 뒤 별도의
마이그레이션을 수행하거나 개발용 DB를 새로 만들어야 합니다.

Aiven PostgreSQL 생성과 연결 방법은 `deploy/postgresql/README.md`에 정리되어
있습니다. 실제 비밀번호는 저장소 파일이 아닌 로컬 `.env`와 배포 서비스의
Secret 환경변수로만 관리합니다.
