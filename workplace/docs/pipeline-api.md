# 선택·승인 저장 API

작업 기준: `develop`의 `79e34f4`. 백엔드 변경만 포함합니다.

## 공통 계약

- 인증: `Authorization: Bearer <access_token>`. 사업자등록번호는 JWT에서 추출합니다.
- 요청: 단일 공고 `{ "bid_no": "R26BK123", "revision": "000" }`.
- `bid_no`: 영문·숫자·밑줄·하이픈 1~100자.
- `revision`: 필수 문자열, 같은 문자 집합 1~20자. 앞자리 0을 보존하고 `"00"`과 `"000"`을 구분합니다.
- HTTP 200: 신규·반복 저장 모두 동일. 반복 요청은 행이나 최초 처리 시각을 추가하지 않습니다.
- 타임스탬프: UTC ISO 8601. `approved_at`은 승인 전 `null`입니다.
- 본문의 사용자 식별자는 사용하지 않습니다. 응답에도 사업자등록번호를 포함하지 않습니다.

## 엔드포인트

| 메서드 | 경로 | 동작 |
| --- | --- | --- |
| POST | `/api/me/selections` | 신규 선택 저장. 이미 승인된 행은 승인 상태 유지 |
| POST | `/api/me/approvals` | 선택된 행 승인. 선택 이력이 없으면 409 |
| GET | `/api/me/pipeline` | 로그인 사업자의 전체 선택·승인 목록. 없으면 `[]` |

POST 응답과 GET 배열의 각 원소는 같은 형식입니다.

```json
{
  "bid_no": "R26BK123",
  "revision": "000",
  "status": "selected",
  "selected_at": "2026-10-25T00:00:00Z",
  "approved_at": null
}
```

승인 후 `status`는 `approved`이고 `approved_at`에 최초 승인 시각이 들어갑니다.
GET은 선택 시각 내림차순, 공고번호·차수 오름차순입니다.
잘못된 입력은 400, 인증 누락·실패는 401, 없는 경로는 404, 잘못된 메서드는 405입니다.
DB 오류는 기존 공통 오류 처리에 따라 503입니다.

## 프런트 담당자 확인 사항

- 승인 선행 선택 정책은 409 거절을 기준으로 구현했습니다. 팀 합의가 다르면 서비스·저장소 정책 변경이 필요합니다.
- `flow.js`는 아직 sessionStorage를 사용합니다. 이 변경에는 프런트 수정이 없습니다.
- 로그인 후 GET으로 상태를 복원하고 POST를 공고별로 호출해야 합니다.
- 현재 화면은 선택 체크박스 변경, 재검색 시 초기화, 승인 목록 교체가 가능합니다.
  서버의 이 API는 누적 저장하므로 화면의 목록 전체 교체·삭제 의미와 동일하지 않습니다.
  선택·승인 취소, 승인 철회, 목록 교체 정책은 5번과 합의 후 별도 API가 필요합니다.
- 화면이 차수를 변경하면 기존 차수와 별개 행입니다. 최신 차수를 선택 저장한 다음 승인해야 합니다.
- 공고 제목은 이 테이블에 저장하지 않습니다. 복원 시 공고 메타데이터와 결합해야 합니다.

## DB 적용

기존 `users`의 기본키는 `business_registration_number CHAR(10)`입니다. `users.id`는 없습니다.
`database/migrations/003_user_bid_pipeline.sql`을 대상 DB에 수동 실행합니다.
같은 DDL을 신규 설치용 `database/schema.sql`에도 포함했습니다.
앱 시작 시 자동 스키마 실행은 없습니다. 기존 테이블을 바꾸지 않고 새 테이블만 추가합니다.
기본키 `(business_registration_number, bid_no, revision)`가 중복과 사용자별 조회 인덱스를 담당합니다.
외래키와 상태·승인 시각 CHECK 제약으로 데이터 일관성을 보장합니다.

2026-10-25: Aiven `ai-service-mini-project` / `defaultdb.public`에 테이블을 생성하고,
Tables 화면에서 `user_bid_pipeline`과 0개 행을 확인했습니다.
Render 배포 및 프런트 연동은 이 작업에서 실행하지 않았습니다.

## 검증 범위

`PipelineHandlerTest`(로컬 검증용, 커밋 제외): 실제 로컬 HTTP 서버와 가짜 저장소로 인증, 사용자별 격리,
차수 분리, 재로그인 조회, 반복 요청, 승인 상태 유지, 미선택 승인 거절, 잘못된 입력·경로·메서드를 검증합니다.
가짜 저장소 테스트는 운영 PostgreSQL의 동시 요청 동작을 검증하지 않습니다.
JDBC는 복합 기본키와 PostgreSQL의 단일 UPSERT/UPDATE로 상태를 원자적으로 갱신합니다.

## 완료 목록과 남은 순서

- 완료: `feat/backend`를 `develop`의 `79e34f4`까지 fast-forward하고 작업 3 변경만 작성.
- 완료: HTTP 컨트롤러·서비스·JDBC 저장소·요청/응답 DTO 분리.
- 완료: SQL 원본 및 신규 설치용 schema.sql 반영, Aiven 테이블 생성.
- 완료: Java 17에서 `gradlew.bat test --console=plain` 실행, 전체 29개 통과(신규 5개 포함).
- 완료: Windows 한글 컴파일 문제를 막도록 JavaCompile UTF-8 지정.
- 반영 범위: 구현 코드·SQL·이 문서만 커밋하며, 신규 테스트 파일은 로컬에 유지합니다.
- 후속: feat/backend 검토 → develop 반영 → Java 백엔드 배포 → 5번 프런트 연동.
- 최종 확인: 실제 계정으로 선택·승인 → 로그아웃 → 재로그인 → GET 및 화면 복원.
- 검증 한계: HTTP 테스트는 가짜 저장소 사용. 운영 JDBC를 통한 E2E·동시 요청 테스트는 미실행.
  PG Studio는 여러 SQL의 연결이 유지되지 않아 임시 테이블을 이용한 트랜잭션 테스트를 완료하지 못했습니다.

## 5번에게 전달할 메시지

> 작업 3은 B안(서버 저장)으로 구현했습니다. Aiven에 user_bid_pipeline 테이블은 추가 완료했고,
> Java API 코드는 feat/backend에 작성·테스트 완료했습니다. develop 반영·배포 전이라 운영 주소에는 새 API가 없습니다.
> 배포 후 기존 Java API 클라이언트로 POST /me/selections, POST /me/approvals, GET /me/pipeline을 연결해 주세요.
> 클라이언트 baseURL에 /api가 포함된 경우의 상대 경로이며, 실제 주소는 /api/me/...입니다.
> 저장 본문은 단건 {bid_no, revision}이고 revision은 앞자리 0을 유지하는 문자열입니다.
> 여러 건은 공고별로 호출하고, 선택 저장 성공 후 승인을 호출해 주세요. 미선택 승인은 409입니다.
> 로그인 때 GET 결과로 상태를 복원하고, 계정 전환 시 이전 계정의 sessionStorage 상태를 비워 주세요.
> GET의 approved 행도 선택 목록에 포함해야 합니다. 서버 상태가 복원의 기준입니다.
> 취소·초기화·목록 교체는 아직 서버 API가 없으므로, 화면에서 이를 어떻게 처리할지 합의가 필요합니다.
> 자세한 요청·응답 예시는 workplace/docs/pipeline-api.md에 정리했습니다.
