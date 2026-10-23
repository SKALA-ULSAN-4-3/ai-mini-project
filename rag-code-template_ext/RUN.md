# RAG 서버 실행 · 평가 방법

모든 명령은 이 폴더(`rag-code-template_ext/`)에서 실행합니다.

## 1. 처음 한 번: 패키지 설치 · 키 설정

```bash
cd rag-code-template_ext
pip install -r requirements-e.txt
```

같은 폴더에 `.env` 파일을 만들고 키를 넣습니다. 이 파일은 git에 올라가지 않습니다.

```
OPENAI_API_KEY=...
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```

## 2. 서버 켜기 (터미널 1)

```bash
python -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001 --reload
```

- 브라우저: http://localhost:8001/docs (Swagger)
- 상태 확인: http://localhost:8001/health → `bid_nos`에 적재된 공고번호가 보입니다.
- 끄기: `Ctrl + C`

## 3. 공고 PDF 올리기 (`bid_nos`가 비어 있을 때만)

Swagger의 `/upload-paper`를 쓰거나 아래 명령을 씁니다. 같은 공고의 파일은 같은 `bid_no`로 올립니다.

```bash
curl -F "file=@공고문.pdf" -F "bid_no=2026-01" localhost:8001/upload-paper
curl -F "file=@제안요청서.pdf" -F "bid_no=2026-01" localhost:8001/upload-paper
```

처음부터 다시 올리려면 서버를 끄고 `rm -rf faiss_db/pdf`를 실행한 뒤 다시 켭니다.

## 4. 평가 실행 (터미널 2, 서버는 켜 둔 채로)

```bash
python eval/run_eval.py --label chunk500_top5
```

- 질문 26개를 보내고 1~2분 뒤 요약이 나옵니다(정확 · 근거성 · 예외 처리 · 환각).
- 질문별 결과: `eval/results/<시각>_<label>.csv` (엑셀로 열림)
- LLM 호출 없이 키워드 검색 베이스라인만: `python eval/run_eval.py --baseline-only`
- 코드를 바꾼 뒤에는 `--label`만 바꿔 다시 실행하고 숫자를 비교합니다.
