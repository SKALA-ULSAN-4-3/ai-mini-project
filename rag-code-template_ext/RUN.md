# RAG 서버 실행 · 평가 방법

RAG 서버(:8001) 하나가 질의 · 추출(2번), 데이터 적재(1번 라우터), 공고 추천 · 점수 · 체크리스트(3번 라우터, 4번 인증 연결 후)를 함께 제공합니다.

## 1. 처음 한 번: 키 · 패키지

프로젝트 **루트**의 `.env.example`을 `.env`로 복사하고 키를 넣습니다(git에 올라가지 않음).
`rag-code-template_ext/.env`도 옮기는 동안만 보조로 읽습니다.

```bash
pip install -r rag-code-template_ext/requirements-e.txt -r data_pipeline/requirements.txt
```

## 2. 데이터 (1번 데이터 파이프라인)

검색 대상은 루트의 `data/indexes/{pdf,web}`입니다(git 제외). 둘 중 하나로 준비합니다.

- 1번에게 `data/` 폴더(공고 20건 인덱스 · `corpus/bids.csv`)를 받아 루트에 둡니다.
- 또는 서버를 켠 뒤 직접 적재합니다. 같은 공고의 파일은 같은 `bid_no` · `bid_order`로 올립니다.

```bash
curl -F "file=@공고문.pdf" -F "bid_no=2026-01" -F "bid_order=000" localhost:8001/upload-paper
curl -X POST -G localhost:8001/upload-topic --data-urlencode "topic=공동수급 표준협정서"   # 등록된 공식 주제 5개 중 하나
```

적재하면 서버가 다음 요청부터 자동으로 새 데이터를 읽습니다(재시작 불필요).
`data/corpus/bids.csv`가 있으면 3번 형식으로 변환해 `rag-code-template_ext/data/bids.csv`에 둡니다.

## 3. 서버 켜기

```bash
cd rag-code-template_ext
python -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001 --reload
```

- Swagger: http://localhost:8001/docs
- 상태: http://localhost:8001/health → `bids`(공고번호 · 차수), `pdf_chunks`, `web_chunks`
- `data_pipeline.api`를 따로 띄우지 마세요. 같은 포트 · 경로를 이 서버가 이미 제공합니다.

## 4. 평가 · 테스트 (서버를 켠 채로, `rag-code-template_ext`에서)

```bash
python eval/run_eval.py --label 이름            # 질의 평가 26문항 (정확 · 근거성 · 환각)
python -m unittest discover -s tests -p "test_*.py"   # 2번 연결 + 3번 로직 테스트 (LLM 호출 없음)
cd .. && python -m unittest discover -s data_pipeline/tests    # 1번 테스트
```

## 5. 4번 로그인 연결

루트 `.env`에 4번 Java 백엔드 주소를 넣고 서버를 다시 켭니다 (4번 `workplace/.env`의 `SERVER_PORT`와 같은 포트).

```
BACKEND_URL=http://localhost:18080
```

- 시작 로그에 `[공고 API 연결] ... ← 프로필: http://localhost:18080/api/profile`이 보이면 연결된 것입니다.
- **`/health`를 뺀 모든 API에 로그인 토큰이 필요합니다** (질의 · 요약 · 추출 · 검색 · 적재 · 음성 · 추천 · 점수 · 체크리스트).
  4번 `/api/login`에서 받은 토큰을 `Authorization: Bearer <토큰>`으로 붙입니다. 토큰 없음 · 위조 · 만료는 401, 백엔드가 꺼져 있으면 503.
- Python 서버는 JWT 비밀키를 갖지 않습니다. 토큰을 4번에 넘겨 확인합니다
  (질의 · 요약 · 음성 등은 `/api/auth/check`로 토큰만, 추천 · 점수 · 체크리스트는 `/api/profile`로 회사 프로필까지).
- `BACKEND_URL`이 없으면 로그인 확인 없이 열립니다 (로컬 개발 · 평가용). 평가 스크립트에 토큰이 필요하면 `--token "$TOKEN"`.
- 흐름 ③: `POST /search-bids`가 돌려준 `search_id`를 `GET /bids?from=…&to=…&limit=20&search_id=…`에 넘기면
  그 검색 결과에서 3번 로직이 20건을 추립니다. 로그인 연결 상태에서는 `search_id`가 필수입니다.

## 6. 음성 질의 (X3)

화면(공고 Q&A)의 마이크 버튼이 `POST /stt` → `POST /rag-query` → `POST /tts` 순서로 부릅니다.

| API | 요청 | 응답 |
|---|---|---|
| `POST /stt` | multipart, 필드 `audio` (webm · mp3 · wav 등, 10MB 이하) | `{"text": "인식된 질문"}` |
| `POST /tts` | `{"text": "읽을 답변"}` (1,500자 넘으면 잘라 읽음) | `audio/mpeg` (mp3) |

- OpenAI `gpt-4o-mini-transcribe`(받아쓰기) · `tts-1`(읽기, 목소리 `nova`)을 씁니다. 바꾸려면 `.env`에 `STT_MODEL`, `TTS_MODEL`, `TTS_VOICE`.
- 질문 답변 · 추출 모델은 `RAG_LLM_MODEL`, `EXTRACT_LLM_MODEL` (기본 gpt-4o). 고른 근거는 `eval/MODEL_COMPARISON.md`.
- 올린 음성은 파일로 저장하지 않고 메모리에서만 처리합니다.

## 주의: OpenAI 키가 두 군데 있으면

이미 셸에 설정된 환경변수가 `.env`보다 우선합니다. `~/.zshrc` 등에 예전 `OPENAI_API_KEY`가 남아 있으면
`.env`의 키 대신 그 키를 써서 질의 · 요약 · 음성이 모두 401(키 오류)로 실패합니다. 셸의 줄을 지우거나 새 키로 바꾸세요.
