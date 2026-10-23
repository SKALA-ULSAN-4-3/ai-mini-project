# 데이터 파이프라인만 Render에 배포

이 배포는 검색·공고문 확보·선택 첨부 수집·업로드·진행률 API만 실행한다. Vue, Java, RAG 질의응답 서버는 새로 배포하지 않는다. 공통 문서 판별 함수와 의존성만 함께 포함한다.

## 서비스 설정

- 저장소: `SKALA-ULSAN-4-3/ai-mini-project`
- 배포 브랜치: `feat/datapipeline`
- 타입: Docker Web Service
- Root Directory: 비움(저장소 루트)
- Dockerfile Path: `data_pipeline/Dockerfile.render`
- Docker Build Context: `.`
- Health Check Path: `/health`
- 환경변수 `BACKEND_URL`: `https://ai-service-mini-backend.onrender.com`
- 비밀 환경변수: `DATA_GO_KR_SERVICE_KEY`, `OPENAI_API_KEY`. 저장소에 값을 기록하지 않는다.
- 기본 `BID_EMBEDDING_MODEL`: `text-embedding-3-small`

Docker 빌드에서 LibreOffice·Java·한글 글꼴·H2Orestart를 설치한다. 호스트의 .env·기존 수집 파일·가상환경·인덱스는 이미지에 복사하지 않는다. 변환 프로필과 converter.json은 컨테이너 안에서 생성한다.

## 접속

배포 완료 후 실제 서비스 URL의 `/docs`에서 Swagger를 연다. `/`와 `/health`만 인증 없이 응답한다. 데이터 API는 기존 Java 백엔드에서 발급한 Bearer JWT가 필요하며 `/api/auth/check`로 검증한다. Swagger의 Authorize에 로그인 토큰을 입력한다. 기존 `data_pipeline.api:app`의 로컬 실행 계약은 바꾸지 않았다.

OpenAI·나라장터 키는 Render의 비밀 환경변수로 등록하며 브라우저 코드에 전달하지 않는다. 이 배포 계층은 토큰의 유효성을 확인하지만 기존 검색·작업 산출물의 사용자별 소유권 저장 기능을 새로 구현하지는 않는다.

## 저장

현재 기본 원본·캐시·인덱스는 컨테이너 파일시스템에 저장된다. 디스크를 연결하지 않으면 서비스 재생성·재배포 시 사라질 수 있다. 영속 디스크를 사용할 때는 마운트 경로 아래로 `BID_SEARCH_ROOT`, `BID_INDEX_ROOT`를 지정한다. 유료 디스크나 플랜은 별도 결정 없이 생성하지 않는다. worker는 1개로 유지한다.

API 헬스 성공은 실제 공고 수집·임베딩·문서 변환의 종단 검증 완료를 뜻하지 않는다. 모의 검사와 실제 서비스 검증 결과를 구분해 기록한다.
