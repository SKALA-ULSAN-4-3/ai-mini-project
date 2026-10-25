# X2 채점 에이전트 실행

루트 `.env`의 `OPENAI_API_KEY`와 `BACKEND_URL`을 읽는다.
`BID_AGENT_ENABLED=true`가 기본이며 `false`이면 `/agent/score`를 등록하지 않는다.
`BID_AGENT_MODEL=gpt-4o`가 기본이다. 실제 `.env` 값은 이 작업에서 변경하지 않았다.

기존 RAG 서버 실행 방법은 `../RUN.md` 참고. 요청은
`POST /agent/score`에 `{ "bid_no": "공고번호", "revision": "000" }`과
`Authorization: Bearer <로그인 토큰>`을 보낸다. 프로필은 인증 서버에서 조회한다.
토큰 없음은 401, 제안요청서 준비 중은 409다.

[응답 예시](../evaluation/agent-response-examples.json)는 합성 데이터·가짜 모델로 만든 계약 예시다.
`complete`는 처리 종료, `needs_input`이면 `missing_fields`와 `questions`를 표시한다.
사용자 입력을 프로필 API에 저장한 뒤 동일 채점 요청을 다시 호출한다.
`timeout`, `model_error`, `incomplete`, `invalid_response`, `max_rounds`, `max_tool_calls`는
완료로 표시하지 말고 `unresolved_items`와 함께 재시도/담당자 확인을 안내한다.
정성·가격은 담당자 판단이며 `needs_review=true`다. `cost=null`은 무료를 의미하지 않는다.
SDK 재시도는 끄고 실행기 전체 60초 제한을 사용한다. 화면은 로딩과 충분한 요청 대기시간이 필요하다.

[실제 모델 검증](../evaluation/live-agent-check.json)은 합성 입력을 실제 OpenAI로 실행한 결과다.
정상 프로필은 complete, 신용등급 누락은 needs_input이며 두 경우 모두 고정 계산과 일치했다.
백엔드 연결은 ConnectError였다. 실제 로그인·프로필·RAG 문서·화면의 전체 흐름은 미검증이다.

## 추가 인증 검증 (2026-10-25)

임시 실제 Java/PostgreSQL과 Uvicorn HTTP 라우터에서 실제 JWT·프로필 보완 후 재채점까지 확인했다.
이전에 기록된 ConnectError는 기존 BACKEND_URL 서버의 상태이며, 임시 환경에서 인증 연동은 통과했다.
[상세](../evaluation/real/AUTH_INTEGRATION.md), [프론트 전달](FRONTEND_HANDOFF.md).
