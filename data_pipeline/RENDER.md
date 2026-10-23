# 데이터 파이프라인 + RAG 통합 Render 배포

기존 Render 서비스 하나에서 데이터 API와 RAG API를 같은 프로세스로 실행한다. Vue·Java·새 DB는 배포하지 않고 기존 Java 백엔드를 인증·프로필 조회에 사용한다. bid_logic과 기존 RAG 업무 코드는 수정하지 않는다.

## 서비스 설정

- 서비스: `ai-mini-datapipeline`
- URL: `https://ai-mini-datapipeline.onrender.com`
- Swagger: `https://ai-mini-datapipeline.onrender.com/docs`
- 저장소/브랜치: `SKALA-ULSAN-4-3/ai-mini-project`, `feat/datapipeline`
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

브라우저 CORS OPTIONS는 기존 RAG CORS 미들웨어에 전달하고 실제 API 요청에는 인증을 적용한다. POST 경로를 주소창에서 GET으로 열면 Method Not Allowed(405)가 나므로 Swagger의 Try it out이나 올바른 POST 요청을 사용한다. Swagger에 로그인 API는 없고 로그인은 기존 Java 백엔드 /api/login에서 한다.

데이터 API만 실행하는 기존 data_pipeline.render_app:app은 유지한다. 통합 배포에서는 render_rag_app을 실행한다. API 키를 브라우저에 넘기거나 JWT 대신 API 키를 Authorize에 넣지 않는다.

## 문서 변환과 저장

Docker 빌드에서 LibreOffice·Java·한글 글꼴·H2Orestart를 설치한다. 호스트 .env·수집 원본·FAISS·가상환경은 이미지에서 제외한다. 변환 프로필과 converter.json은 이미지 안에서 생성한다.

무료 인스턴스에는 영속 디스크가 없어 재배포·재생성 시 원본·인덱스가 사라질 수 있다. 영속 디스크 사용 시 BID_SEARCH_ROOT와 BID_INDEX_ROOT를 마운트 경로 아래로 지정한다. 유료 플랜·디스크는 승인 없이 만들지 않는다. 데이터가 없는 새 배포에서는 문서를 먼저 수집·적재해야 RAG 검색·추출을 사용할 수 있다.

## 검증 범위

임시 인덱스와 모의 인증으로 핵심 경로 15개 등록, Swagger Bearer 스키마, health/docs/root, 데이터·RAG 미인증 차단, 잘못된 토큰 차단, CORS 사전 요청, 인증된 빈 저장소 오류 응답을 확인했다. 실제 LLM·공고 수집·임베딩은 이 검사에서 실행하지 않았다. Render 배포 후 실제 health/OpenAPI/인증 차단을 별도로 확인한다. 헬스 성공은 문서별 답변 정확도나 전체 사용자 흐름 검증 완료를 뜻하지 않는다.
