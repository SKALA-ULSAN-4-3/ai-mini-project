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

## 5. 4번 로그인 연결 (공고 추천 · 점수 · 체크리스트)

`GET /bids`, `/bids/{bid_no}/score`, `/bids/{bid_no}/checklist`는 로그인한 회사의 프로필이 필요합니다.
루트 `.env`에 4번 Java 백엔드 주소를 넣고 서버를 다시 켜면 자동으로 등록됩니다.

```
BACKEND_URL=http://localhost:8080
```

- 시작 로그에 `[공고 API 연결] ... ← 프로필: http://localhost:8080/api/profile`이 보이면 연결된 것입니다.
- 요청에는 4번 `/api/login`에서 받은 토큰을 `Authorization: Bearer <토큰>`으로 붙입니다.
- Python 서버는 JWT 비밀키를 갖지 않습니다. 토큰을 4번 `/api/profile`에 그대로 전달하고, 검증과 프로필 조회는 4번이 합니다
  (토큰 없음 · 위조 · 만료 401, 프로필 없음 404, 백엔드 꺼짐 503).
- 공고 목록은 1번 수집 결과 `data/corpus/bids.csv`를 변환해 씁니다. 이 파일이 없으면 `/bids`가 503입니다.
