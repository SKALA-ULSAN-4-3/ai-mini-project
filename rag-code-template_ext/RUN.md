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

## 5. 3번 라우터 연결 (4번 인증이 준비되면)

`GET /bids`, `/bids/{bid_no}/score`, `/bids/{bid_no}/checklist`는 로그인한 회사 프로필이 필요해 아직 등록하지 않았습니다.
4번의 "JWT 검증 + 프로필 조회" 의존성 함수가 준비되면 서버 파일 끝에서 한 번 호출합니다.

```python
connect_bid_routes(get_authenticated_profile)
```
