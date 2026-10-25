# 실제 인증·채점 HTTP 통합 검증

검증일: 2026-10-25 KST. 원본 프로젝트 설정을 유지하고 임시 Java 서버·PostgreSQL로 검증했다.
서비스 포트와 DB 비밀번호·JWT 비밀키는 실행 중 임시 생성했으며 결과 파일에 저장하지 않았다.

## 통과한 흐름

- 실제 PostgreSQL 준비 → 실제 Java 회원가입 → 로그인 → JWT 발급.
- 실제 프로필 PUT/GET → RAG가 Bearer 토큰을 Java에 전달해 프로필 조회.
- Uvicorn의 실제 루프백 HTTP /agent/score 호출.
- 토큰 없음·위조 401, 프로필 미등록 404, 공고 없음 404, RFP 준비 중 409, 차수 누락 422.
- 허용 Origin의 인증 실패 응답에도 CORS 헤더 포함.
- 신용등급 누락 → needs_input → Java 프로필 보완 → complete.
- 실제 평가 채점표 5건 × 프로필 3개: 264개 항목이 직접 계산 결과와 일치.

규칙 기반 테스트 모델과 실제 OpenAI 모델 각각 검사 63개 통과. 실제 모델 사용 흐름은 아래 3건이다.

| 흐름 | 응답 상태 | 응답 시간 | 모델 호출 수 |
| --- | --- | ---: | ---: |
| complete | complete | 8.15초 | 3 |
| needs_input | needs_input | 7.97초 | 3 |
| complete_after_profile_update | complete | 6.86초 | 3 |

## 검증 범위와 남은 연결

Java 인증·DB와 OpenAI는 실제 실행했다. Python 쪽은 실제 bid_logic.api 라우터·backend_auth·모델 어댑터를 Uvicorn으로 실행했다.
문서 공급은 저장된 실제 평가 채점표와 합성 fixture를 사용했다. 전체 RAG 서버 시작·실시간 문서 추출·프론트 브라우저·배포 서버 E2E를 완료한 것은 아니다.
프론트 에이전트 버튼·결과 비교·질문 입력 화면은 현재 미구현이다. [전달 자료](../../bid_logic/FRONTEND_HANDOFF.md)의 체크리스트로 후속 검증한다.
기존 루트 .env에는 DB_PASSWORD와 JWT_SECRET이 없어 기존 BACKEND_URL 서버가 실행되지 않았다. 실제 실행 시 백엔드 담당자의 DB/JWT 설정이 필요하다.
이번 검증의 임시 Java 프로세스와 임시 PostgreSQL 컨테이너·DB 데이터는 종료 후 제거했다.

## 재실행 도구

`tools/verify_authenticated_agent.py`는 이미 기동한 임시 로컬 Java/PostgreSQL을 대상으로 실행한다.
프로젝트 루트에서 임시 가상환경에 fastapi/httpx/uvicorn/openai를 설치한 뒤:

```bash
python rag-code-template_ext/tools/verify_authenticated_agent.py \
  --project-root . --backend-url http://127.0.0.1:8080 \
  --disposable-backend --output /tmp/authenticated-agent-check.json
```

`--live-model`을 추가하면 실제 모델 3건을 호출하며 비용이 발생한다. 기본은 규칙 기반 테스트 모델이다.
테스트 회원을 생성하므로 기존 업무 DB 대신 폐기 가능한 임시 DB에서만 실행한다. 이 도구는 외부 인증 서버를 실행하거나 DB를 지우지 않으며 임시 서버/DB의 생성·종료는 실행자가 담당한다.

원본 기록: [실제 모델](authenticated-agent-live.json), [테스트 모델](authenticated-agent-scripted.json).
