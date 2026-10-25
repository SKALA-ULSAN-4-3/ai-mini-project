# 데이터 파이프라인 + RAG 통합 Render 배포

기존 Render 서비스 하나에서 데이터 API와 RAG API를 같은 프로세스로 실행한다. Vue·Java·새 DB는 배포하지 않고 기존 Java 백엔드를 인증·프로필 조회에 사용한다. bid_logic과 기존 RAG 업무 코드는 수정하지 않는다.

## 서비스 설정

- 서비스: `ai-mini-datapipeline`
- URL: `https://ai-mini-datapipeline.onrender.com`
- Swagger: `https://ai-mini-datapipeline.onrender.com/docs`
- 저장소/브랜치: `SKALA-ULSAN-4-3/ai-mini-project`, `develop` (2026-10-25 변경)
- 타입: Docker Web Service, Root Directory 비움
- Dockerfile: `data_pipeline/Dockerfile.render`, Build Context `.`
- 실행: `data_pipeline.render_rag_app:app`, PORT 환경변수, worker 1개
- 헬스: `/health` (기존 RAG의 벡터·공고 상태)
- BACKEND_URL: `https://ai-service-mini-backend.onrender.com`
- 비밀 환경변수: DATA_GO_KR_SERVICE_KEY, OPENAI_API_KEY. 값은 Render에만 등록한다.

## 실행 범위

기존 RAG 서버가 data_pipeline.api.router를 포함하므로 라우터를 중복 등록하지 않는다. Docker에는 데이터 패키지와 필요한 RAG 서버·인증 연결·bid_logic 코드를 함께 담고 두 requirements를 같이 설치한다. FAISS·파일 경로·임베딩 모델은 공유하며 업로드 후 저장소 세대 변경을 반영한다.

- 데이터: /search-bids, /fetch-notices, /fetch-documents, /jobs/{job_id}, /upload-paper, /upload-topic, /data-status
- RAG: /rag-query, /bids/summaries, /bids/{bid_no}/summary, /documents, /scoring-table, /required-docs
- 프로필 연결 공고 로직: /bids, /bids/recheck, /bids/{bid_no}/score, /checklist 및 기존 등록 경로

위 축약 경로는 해당 /bids/{bid_no} 뒤에 붙는다. 실제 요청·응답 형식은 배포된 /openapi.json 및 Swagger를 따른다. 선택·승인 저장이나 프론트 화면을 새로 구현한 것은 아니다.

## 인증과 호출 방법

루트·헬스·Swagger·OpenAPI는 인증 없이 연다. 나머지 실제 요청은 Java /api/auth/check로 Bearer JWT를 검증한다. 공고 로직은 기존 /api/profile 의존성도 사용하므로 회사 프로필 등록이 필요하다. Swagger Authorize에 기존 백엔드 로그인 토큰을 넣는다.

기존 RAG CORS 허용 정책을 배포 미들웨어 최외곽에 적용한다. OPTIONS 사전 요청뿐 아니라 인증 실패 401 응답에도 CORS 헤더를 유지해 브라우저가 실제 인증 오류를 읽을 수 있게 한다. POST 경로를 주소창에서 GET으로 열면 Method Not Allowed(405)가 나므로 Swagger의 Try it out이나 올바른 POST 요청을 사용한다. Swagger에 로그인 API는 없고 로그인은 기존 Java 백엔드 /api/login에서 한다.

데이터 API만 실행하는 기존 data_pipeline.render_app:app은 유지한다. 통합 배포에서는 render_rag_app을 실행한다. API 키를 브라우저에 넘기거나 JWT 대신 API 키를 Authorize에 넣지 않는다.

## 문서 변환과 저장

Docker 빌드에서 LibreOffice·Java·한글 글꼴·H2Orestart를 설치한다. 호스트 .env·수집 원본·FAISS·가상환경은 이미지에서 제외한다. 변환 프로필과 converter.json은 이미지 안에서 생성한다.

무료 인스턴스에는 영속 디스크가 없어 재배포·재생성 시 원본·인덱스가 사라질 수 있다. 영속 디스크 사용 시 BID_SEARCH_ROOT와 BID_INDEX_ROOT를 마운트 경로 아래로 지정한다. 유료 플랜·디스크는 승인 없이 만들지 않는다. 데이터가 없는 새 배포에서는 문서를 먼저 수집·적재해야 RAG 검색·추출을 사용할 수 있다.

## 검증 범위

임시 인덱스와 모의 인증으로 핵심 경로 15개 등록, Swagger Bearer 스키마, health/docs/root, 데이터·RAG 미인증 차단, 잘못된 토큰 차단, CORS 사전 요청, 인증된 빈 저장소 오류 응답을 확인했다. 실제 LLM·공고 수집·임베딩은 이 검사에서 실행하지 않았다. Render 배포 후 실제 health/OpenAPI/인증 차단을 별도로 확인한다. 헬스 성공은 문서별 답변 정확도나 전체 사용자 흐름 검증 완료를 뜻하지 않는다.

## 2026-10-25 실제 재배포 기록

- 관리 화면: https://dashboard.render.com/web/srv-dbdjrr2vcj2c738181s0
- 이전 배포: `feat/datapipeline` / `dd49dcc`.
- 변경: 브랜치를 `develop`으로 저장. 이 변경으로 자동 배포가 시작되어 수동 배포를 중복 실행하지 않았다.
- 배포 커밋: `1cbc6e3ce09725bf5f9a4dc7c73378d740791a01`.
- 배포 ID: `dep-dber6rdg1s2s73dhgalg`, 상태 Live, 빌드·배포 소요 1분 3초.
- 배포 시작: 2026-10-25 16:44:45 KST. 완료 화면과 커밋을 실제 Render 대시보드에서 확인했다.
- `79e34f4`를 포함하며, 이후 Java 선택·승인 API 변경 `f6d4fc7` 및 병합 `1cbc6e3`도 포함한다.
- 검색 스냅샷 공급자 `knowledge_bridge.search_results`를 `/bids`에 연결한 코드와 관련 회귀 테스트를 확인했다.
- Root Directory: 비움. Dockerfile: `data_pipeline/Dockerfile.render`. Build Context: `.`.
- Docker Command: 비움. Dockerfile CMD의 `python -m uvicorn data_pipeline.render_rag_app:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1` 사용.
- Health Check Path: `/health`.
- `BACKEND_URL=https://ai-service-mini-backend.onrender.com` 실제 등록값 일치.
- `DATA_GO_KR_SERVICE_KEY`, `OPENAI_API_KEY` 등록 여부만 확인. 키 값은 열거나 문서에 복사하지 않았다.
- 현재 Render 작업공간에는 RAG 서비스만 있다. Java 서비스 자체를 재배포한 것은 아니다. 사용자 전달 기준 Java 이전 배포는 `ec8d27d`; 현재 관리 화면 확인·최신 develop 재배포는 4번의 서비스 접근이 필요하다.

### 실제 API 결과

| 검사 | 결과 |
| --- | --- |
| `/health` | 200 |
| 토큰 없는 `GET /bids` | 401, `WWW-Authenticate: Bearer`, CORS Origin 반환 |
| 토큰 없는 `POST /search-bids` | 401, CORS Origin 반환 |
| Java `/api/auth/check` 토큰 없이 호출 | 401, 백엔드 응답 확인 |
| Java 로그인 preflight (localhost/127.0.0.1:5174) | 204이나 `Access-Control-Allow-Origin` 누락. 브라우저 직접 로그인 차단 가능 |
| 로그인 → `/search-bids` → `search_id` → `/bids` | 테스트 계정 로그인 대기. 완료로 처리하지 않음 |
| 재배포 후 문서 적재 | 로그인 및 시연 대상 선택 대기. 초기 문서 0개 확인 |

공개 API 검증 원본: [verification/render-20261025.json](verification/render-20261025.json).
기업별 후보가 실제 반환되고 `/bids`가 503 없이 응답해야 작업 1 전체 완료다.

### 로그인 검증 재실행

저장소 루트에서 실행한다. 로그인된 JWT는 `MINI_TEST_TOKEN` 환경변수로 제공하거나,
테스트 계정의 `MINI_TEST_BUSINESS_NUMBER`, `MINI_TEST_PASSWORD`를 환경변수에 설정한다.
키·JWT·비밀번호를 명령행 인수, 문서, 커밋에 적지 않는다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.verify_render --origin http://localhost:5174
```

기본 출력은 Git에서 제외된 `data/render-verification.json`이며 비밀값은 저장하지 않는다.
계정이 없거나 공고 목록을 확보하지 못하면 성공으로 표시하지 않고 종료 코드 1을 반환한다.
실제 검색 기간·검색어는 `--from`, `--to`, `--query`로 지정한다. 과거 평가 20건을 운영 입력으로 사용하지 않는다.

프론트는 `VITE_USE_MOCK=false`, `VITE_AUTH_URL=https://ai-service-mini-backend.onrender.com/api`,
`VITE_RAG_URL=https://ai-mini-datapipeline.onrender.com`으로 실행한다. `auth` 모드는 검색·요약을 모의 처리하므로 운영 검증에 쓰지 않는다.
Java에서 실제 프론트 출처의 `CORS_ORIGINS`를 허용해야 직접 요청이 가능하다. 현재 로컬 5174 출처는
preflight의 Origin 응답이 없어, 로컬 검증 화면은 개발 프록시(`/api`, `/rag`)를 통해 실제 Render 서버로 연결했다.
프록시 경유 성공은 배포된 프론트의 직접 CORS 통과를 의미하지 않는다.

문서가 없는 배포에서는 실제 검색의 `search_id`와 선택한 공고번호·차수로 `/fetch-notices`를 호출하고
`/jobs/{job_id}` 완료를 확인한다. 제안요청서가 필요하면 `/fetch-documents`를 추가 호출한다.
시연 대상 원문·인덱스가 준비된 뒤에는 시연 직전 재배포를 피한다. 평가 자료를 운영에 자동 적재하지 않는다.

평가 원문 재현과 팀원 인계: [EVALUATION.md](EVALUATION.md), [HANDOFF.md](HANDOFF.md).
