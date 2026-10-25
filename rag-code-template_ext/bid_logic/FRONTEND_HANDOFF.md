# 프론트 담당자 전달용: X2 채점 API

2026-10-25 기준, 정하윤 서버 기능의 계약과 실제 인증 검증 결과다. 이 문서를 작성한 것으로 팀원에게 메시지를 전송한 것은 아니다.

## 현재 구현 경계

- Java `/api/login`, `/api/profile`: 기존 구현 사용.
- RAG `/agent/score`: 서버 시작 시 모델 어댑터 연결 완료. BACKEND_URL 필요.
- 프론트 일반 채점 화면: 구현됨.
- 프론트 에이전트 버튼·고정 결과와 비교·에이전트 재질문 흐름: 현재 frontend에는 미구현. 신한수 담당.

## 호출 코드

`frontend/src/api/flow.js`는 기존 `rag` 클라이언트를 이미 import한다. 프론트 담당자가 다음 함수를 추가할 수 있다.
기존 클라이언트가 sessionStorage의 토큰을 Bearer 헤더에 넣으므로 토큰 전달 코드를 중복 작성하지 않는다.

```js
export async function fetchAgentScore(b) {
  return (await rag.post('/agent/score', {
    bid_no: b.bid_no,
    revision: String(b.revision ?? b.bid_order ?? '000'),
  }, { timeout: 75000 })).data
}
```

인증 서버 주소는 VITE_AUTH_URL(`/api` 포함), RAG 주소는 VITE_RAG_URL이다.
로컬 프록시 기본값은 `/api`와 `/rag`다. 실제 연결 검증 시 VITE_USE_MOCK=false로 실행한다.
이번 작업에서 프론트 소스나 환경 파일은 변경하지 않았다.

## 응답 처리

- `status=complete`: 에이전트 결과 표시. 고정 경로 결과는 별도 상태에 보존해 나란히 비교.
- `status=needs_input`: `questions`를 보여주고 `missing_fields`의 정보를 받는다.
  기존 GET /api/profile로 프로필을 읽고 기존 프로필 입력 화면을 통해 PUT /api/profile로 전체 프로필을 저장한 뒤 같은 공고로 재채점한다.
  PUT은 부분 수정 API가 아니므로 `{credit_rating: answer}`만 보내면 필수 항목 검증에 실패한다.
- `manual` 항목: 정성·가격은 담당자 판단으로 표시. 총점을 합산하지 않는다.
- `needs_review=true`: 결과가 참가자격·낙찰 가능성 확정이 아님을 기존 안내 문구로 표시.
- `timeout`, `model_error`, `incomplete`, `invalid_response`, `max_rounds`, `max_tool_calls`:
  HTTP 200이어도 채점 성공으로 표시하지 않는다. `unresolved_items`와 재시도를 안내한다.
- `cost=null`: 무료나 0원으로 표시하지 않는다.

## HTTP 오류

| 상태 | 의미 / 화면 처리 |
| --- | --- |
| 401 | 토큰 없음·위조·만료. 기존 클라이언트의 로그인 이동 처리 사용 |
| 404 | 프로필 미등록 또는 공고/차수 없음. 응답 detail에 따라 입력/공고 선택 안내 |
| 409 | 제안요청서 준비 중. 기다린 뒤 다시 호출 |
| 422 | 차수 누락 등 잘못된 입력. 요청 값 확인 |
| 503 | 인증 백엔드나 데이터 서비스 연결 문제. 로그인 실패로 단정하지 않고 연결 상태 안내 |

## 연동 확인 순서

- [ ] 실제 로그인 후 공고 선택 → 에이전트 버튼 → 고정 점수와 결과 비교
- [ ] 채점 중 로딩, 중복 클릭 방지, 공고 변경 시 이전 결과 혼입 방지
- [ ] 프로필의 신용등급을 비움 → needs_input 질문 표시
- [ ] 기존 프로필 화면에서 보완·저장 → 돌아와 동일 공고 재채점 → complete
- [ ] 로그아웃 상태의 401 처리, 준비 중 409, 차수 누락 422 처리
- [ ] timeout/model_error 등 응답 status를 완료로 표시하지 않는지 확인

위 체크박스는 아직 브라우저에서 수행하지 않은 항목이다.
프론트 구현 후 이 흐름을 실제 배포 주소에서도 확인해야 한다.

## 검증 근거

[인증 통합 결과](../evaluation/real/AUTH_INTEGRATION.md),
[원본 검사 기록](../evaluation/real/authenticated-agent-live.json),
[정상·되묻기 JSON 계약 예시](../evaluation/agent-response-examples.json).

## 목록·체크리스트 기한 보완

영진 R26BK01753530/000의 목록 응답은 deadline_kind=participation, deadline_event=입찰참가신청,
그리고 deadlines 배열(참가신청·파일·제본의 id/event/due/sources)을 제공한다.
현재 frontend의 toBid는 이 추가 필드를 옮기지 않으므로 프론트 담당자가 deadline_kind/deadline_event/deadlines도 보존하면 단계별 표시가 가능하다.
기존 /checklist 응답 schedule에는 세 항목과 각각의 status/d_day가 들어가므로 기존 일정 UI로도 구분할 수 있다.
참가신청 경과를 제안서 파일·제본 제출까지 종료된 것으로 표시하지 않는다.
마산 R26BK01707131/000은 경남 또는 부산 소재지 필터가 적용된다. needs_review는 유지된다.
