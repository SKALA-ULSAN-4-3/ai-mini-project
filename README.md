# 나라장터 입찰공고 맞춤 Q&A 서비스

SMB(중소기업)를 위한 RAG 기반 입찰공고 AI. 회사 프로필을 등록하고 기간을 고르면, 나라장터 공고를 검색해 관련 공고 20건을 추리고, 공고문 요약과 채점표 기준 예상 점수, 준비 체크리스트를 **공고문 출처(파일명 p.쪽)와 함께** 보여 줍니다.

> AI는 추천만 하고, 자격 판단과 최종 승인은 담당자가 합니다. 문서에 없는 질문은 "문서에 없음"(handoff)으로 넘기고, 총점은 보여 주지 않고 항목별로만 표시합니다.

## 서비스 흐름

1. **프로필 등록** — 회원가입·로그인(JWT) 후 업종, 지역, 희망 금액, 보유 서류 등을 저장
2. **검색 · 추리기** — 기간과 검색어로 나라장터 API를 조회해 관련 공고 20건으로 추림
3. **공고문 적재 · 요약** — 공고문을 받아 요약하고, 공고문 내용으로 부적격 공고를 재확인
4. **선택** — 담당자가 검토할 공고를 고름 (서버 DB에 저장)
5. **제안요청서 · 채점표 · 예상 점수** — 선택한 공고의 제안요청서를 받아 채점표를 만들고, 계산 가능한 항목만 점수를 보여 줌
6. **승인 · 준비 체크리스트** — 승인한 공고의 제출서류·일정을 체크리스트로 제공, 보유 서류는 자동 체크
7. **공고 Q&A** — 질문 → 출처가 달린 답, 문서에 없으면 handoff

## 아키텍처

```
Vue.js 프론트엔드 → Java 인증 서버(JWT, 프로필·선택·승인 저장, PostgreSQL)
                  → FastAPI RAG 서버(검색·적재·요약·채점·체크리스트·Q&A) → FAISS + Closed LLM
```

| 계층 | 위치 | 설명 |
| --- | --- | --- |
| 프론트엔드 | `frontend/` | Vue 3 + Vite + Pinia + vue-router |
| 인증·백엔드 API | `workplace/` | Java, JWT, 프로필·요약·선택·승인 저장 |
| 데이터 파이프라인 | `data_pipeline/` | 나라장터 검색, 공고문·첨부 다운로드, HWP→PDF 변환, 적재 |
| RAG · 추리기 · 점수 | `rag-code-template_ext/` | 요약, 채점표, 예상 점수, 체크리스트, `/rag-query` |

## 실행 방법

자세한 내용은 파트별 문서를 참고하세요.

- 데이터 파이프라인: [`data_pipeline/README.md`](data_pipeline/README.md), 배포는 [`data_pipeline/RENDER.md`](data_pipeline/RENDER.md)
- RAG 서버: [`rag-code-template_ext/RUN.md`](rag-code-template_ext/RUN.md)
- 백엔드: [`workplace/README_BACKEND.md`](workplace/README_BACKEND.md), 선택·승인 API는 [`workplace/docs/pipeline-api.md`](workplace/docs/pipeline-api.md)

### 프론트엔드

```bash
cd frontend
npm install
npm run dev          # http://localhost:5174
```

`frontend/.env.development`의 `VITE_USE_MOCK`로 서버 연결 방식을 고릅니다. (바꾼 뒤에는 개발 서버를 다시 켜야 합니다)

| 값 | 동작 |
| --- | --- |
| `true` | 전부 가짜 데이터 (서버 없이 화면 확인) |
| `auth` | 가입·로그인·프로필만 실제 서버 |
| `false` | 전부 실제 서버 |

실제 서버 주소는 `VITE_AUTH_URL`(Java), `VITE_RAG_URL`(RAG)에 적습니다. 이 값은 공개 빌드에 포함되므로 **비밀키를 넣지 마세요.** 로컬에서 Render의 Java 서버로 연결하려면 `AUTH_BACKEND=<서버 주소> npm run dev`로 실행합니다.

### 배포

- 프론트엔드: Vercel (Root Directory `frontend`, 프리셋 Vite)
- 백엔드·RAG: Render (환경변수 `OPENAI_API_KEY`, `DATA_GO_KR_SERVICE_KEY`, `BACKEND_URL` 등은 서버 환경변수로만 설정)

## 평가 결과 요약

<!-- 각 파트 담당자 요약으로 보완 -->

- Q&A: 22/22, 문서에 없는 예외 질문 4/4, 환각 0
- 예상 점수: 264/264
- 채점 에이전트 vs 고정 경로 비교(X2), 추리기 P@5: `rag-code-template_ext/evaluation/real/REPORT.md` 참고

## 한계와 다음 단계

- 선택·승인은 서버에 누적 저장되며, 취소·철회 API는 아직 없음
- 자격 관련 답은 `needs_review`로 표시하고 최종 판단은 담당자가 함
- 정성 평가·가격 점수와 낙찰 확률은 제공하지 않음
- Render 무료 서버는 재배포 시 저장된 문서와 인덱스가 사라짐
- 확장 화면은 화면까지 구현했고 서버 연결을 기다리는 중: 채점 에이전트(`POST /agent/score`, 고정 경로 결과와 비교·되묻기), 음성 질의(마이크 → 글자 → `/rag-query` → 음성 답변). 가짜 서버 모드에서 동작을 확인할 수 있음

## 팀

| # | 담당 | 이름 |
| --- | --- | --- |
| 1 | 데이터 파이프라인 | 안영준 |
| 2 | RAG · 요약 · Q&A | 손경락 |
| 3 | 추리기 · 점수 · 체크리스트 | 정하윤 |
| 4 | 인증 · 백엔드 API · 운영 | 손수경 |
| 5 | 프론트엔드 · 발표 | 신한수 |

## 데이터 출처

공공기관이 공개한 나라장터 공고문·제안요청서를 사용합니다. 담당자 성명·전화번호·이메일 등 개인정보는 적재 전에 마스킹하며, 회사 프로필에는 개인정보를 받지 않습니다.
