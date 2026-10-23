# Workplace Java 백엔드

`workplace`는 사업자 회원가입·로그인, Bearer JWT 발급·검증, 회사 프로필
API와 공통 오류 처리를 담당합니다. PDF 청킹, FAISS 검색, 프롬프트와 LLM
호출은 RAG 담당 영역이므로 이 모듈에 포함하지 않습니다.

## 패키지 책임

- `config`: 환경 설정
- `domain`: 요청·응답과 사용자·프로필 데이터
- `repository`: JDBC 데이터 접근
- `service`: 인증과 프로필 업무 규칙
- `security`: JWT 생성·검증
- `web.handler`: 엔드포인트별 HTTP 처리
- `web`: JSON, Bearer 인증, CORS, 오류 처리와 요청 로그
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

## API

| 메서드 | 경로 | 설명 | 인증 |
|---|---|---|---|
| POST | `/api/signup` | 사업자 회원가입 | 불필요 |
| POST | `/api/login` | 로그인 및 JWT 발급 | 불필요 |
| GET | `/api/auth/check` | 현재 JWT 확인 | Bearer JWT |
| GET | `/api/profile` | 회사 프로필 조회 | Bearer JWT |
| PUT | `/api/profile` | 회사 프로필 생성·수정 | Bearer JWT |
| GET | `/api/health` | API·DB 상태 확인 | 불필요 |

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

로그아웃 API는 별도로 두지 않습니다. 클라이언트가 보관한 Access Token을
삭제하면 로그아웃됩니다. 운영 환경의 브라우저 토큰 보관 방식은 프론트엔드와
보안 정책을 함께 정해야 하며, 예제 로그인 화면은 개발 확인용으로
`sessionStorage`만 사용합니다.

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

`CREATE TABLE IF NOT EXISTS`는 기존 테이블 구조를 변경하지 않습니다. 예전
`id/username` 구조의 테이블을 이미 생성했다면 데이터를 백업한 뒤 별도의
마이그레이션을 수행하거나 개발용 DB를 새로 만들어야 합니다.

Aiven PostgreSQL 생성과 연결 방법은 `deploy/postgresql/README.md`에 정리되어
있습니다. 실제 비밀번호는 저장소 파일이 아닌 로컬 `.env`와 배포 서비스의
Secret 환경변수로만 관리합니다.
