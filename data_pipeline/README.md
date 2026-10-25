# 역할 1: 나라장터 데이터 파이프라인

배포·평가 원문 인계 문서:

- 실제 배포 설정과 검증: [RENDER.md](RENDER.md)
- 평가 원문 다운로드·무결성·추천 테스트 재현: [EVALUATION.md](EVALUATION.md)
- 2~5번 협업 및 남은 확인: [HANDOFF.md](HANDOFF.md)

요청한 공고의 검색·다운로드, HWP/HWPX→PDF 변환, 마스킹, `bids.csv`·출처표 작성, `/upload-paper`·`/upload-topic` 적재와 FAISS 인덱스 생성만 담당합니다.

기업별 적합성·참가자격 판정, 공고 요약·Q&A, 예상 점수·추천·체크리스트, 사용자 인증·프로필 DB·화면은 구현 범위에서 제외합니다. 기존 강의 예제는 별도 디렉터리에 유지합니다.

## 설정

프로젝트 루트 `.env`의 `DATA_GO_KR_SERVICE_KEY`(조회), `OPENAI_API_KEY`(임베딩)를 사용합니다. 값을 출력하거나 산출물에 기록하지 않습니다.

macOS(Homebrew 필요) 또는 Ubuntu 24.04에서 다음 Bash로 Python 패키지·LibreOffice·JDK 21을 설치하고 H2Orestart를 프로젝트 프로필에 등록합니다. 스크립트 전체를 sudo로 실행하지 않습니다. Ubuntu에서는 시스템 패키지 설치 단계에서만 sudo를 사용합니다.

```bash
bash data_pipeline/setup_environment.sh --help
bash data_pipeline/setup_environment.sh
```

기존 가상환경이 있으면 해당 Python을 재사용합니다. `PYTHON=python3.12`처럼 버전을 명시할 수도 있지만, 기존 가상환경과 버전이 다르면 덮어쓰지 않고 중단합니다. 실패하면 설치 단계와 도구 오류를 표시합니다. 완료 메시지는 패키지 의존성 검사와 FAISS·PDF·API 로딩까지 통과한 뒤 출력됩니다.

macOS는 LibreOffice 25.8.7.3 설치 파일의 SHA-256을 확인해 `data/tools/LibreOffice.app`에 설치하고, Ubuntu는 배포판 패키지를 사용합니다. 설치 도구는 변환 환경만 준비하며 공고 검색·다운로드·임베딩을 실행하지 않습니다. Python 패키지만 설치하려면 아래 명령을 사용합니다.

```bash
python3 -m venv data_pipeline/.venv
data_pipeline/.venv/bin/python -m pip install -r data_pipeline/requirements.txt
```

HWP/HWPX 변환은 Java 지원 LibreOffice + H2Orestart가 필요합니다. 현재 컴퓨터는 `data/tools/LibreOffice.app`의 LibreOffice 25.8.7.3 + H2Orestart 0.8.0 + JDK 21로 설정돼 있습니다. Bash 대신 이미 설치한 LibreOffice를 연결하려면 다음 초기 설정을 실행합니다.

```bash
data_pipeline/.venv/bin/python data_pipeline/convert_documents.py --setup --soffice /Applications/LibreOffice.app/Contents/MacOS/soffice
```

공식 확장 배포 파일은 SHA-256을 검증하고 프로젝트 전용 `data/tools/hwp-profile`에 등록합니다. 기존 LibreOffice 설정은 수정하지 않습니다. 26.8.1은 실제 첨부의 한글 손상이 발견돼 사용하지 않았습니다. [H2Orestart 공식 문서](https://github.com/ebandal/H2Orestart).

macOS 신규 프로필에서는 `unopkg`가 실행하는 보조 프로세스가 `Launch Constraint Violation`으로 종료되는 문제가 재현됐습니다. macOS에서는 LibreOffice 내부의 임시 설치 매크로로 검증된 확장만 등록하고, 완료 후 매크로를 제거하며 원래 매크로 목록을 복원합니다. 앱 서명이나 시스템 보안 설정은 변경하지 않습니다. 설치할 때는 해당 프로필을 쓰는 변환 작업을 종료해야 합니다.

2026-10-23 macOS 26.5.2 arm64에서 가상환경·LibreOffice·확장 프로필이 없는 별도 경로(공백 포함)로 다운로드부터 설치 종료까지 검증했습니다. Python 3.14.6에서 API 로딩·의존성 검사, 실제 HWP 3쪽·HWPX 5쪽의 PDF 변환 및 텍스트 추출, 설치 재실행, 기존 등록 실패 프로필 복구를 통과했습니다. Homebrew·JDK 21은 호스트에 이미 설치되어 있었으므로 이 두 도구의 신규 설치 및 Ubuntu 실행은 검증 범위에 포함되지 않습니다.

## 화면 연결용 확정 흐름

원격 develop을 실제 pull한 뒤 첨부 MD의 1번 지시만 반영했습니다. [API 계약·저장 구조·검증·제약](MD_DATA_GUIDE.md)을 확인하세요.

1. `POST /search-bids`: 기간·검색어로 목록과 첨부 링크를 조회해 search_id로 저장합니다. 다운로드·회사별 추천은 하지 않습니다.
2. `POST /fetch-notices`: 검색 결과에서 다른 담당 로직이 고른 최대 20건의 공고문 한 개씩만 받아 변환·누적 적재합니다.
3. `GET /jobs/{job_id}`: 공고별 진행률·실패를 확인합니다.
4. 담당자가 공고를 명시적으로 선택한 후 `POST /fetch-documents`: 선택한 공고번호의 차수만 재확인하고 저장한 링크로 나머지 첨부를 받습니다. 정정공고면 새 차수를 사용합니다.

공고문 판별은 RAG의 `knowledge_bridge.classify_attachment`를 그대로 사용합니다. 공고문을 식별하지 못하면 다른 첨부로 대체하지 않습니다. 신청서 HWP·ZIP은 원본을 보존하고 공고문/RFP만 내부 PDF 변환·적재합니다. 검색 응답에서 API 담당자 성명·연락처 필드는 제외하지만 원본과 추출된 공개 업무 연락처는 보존합니다.

고정 20건 목록 `dataset_selection.json`은 삭제했습니다. 최대 20건은 요청당 배치 제한이며 미리 고른 데이터 목록이 아닙니다. 기존 데이터는 삭제하지 않았습니다.

## 기존 CLI 조회·다운로드 (오프라인 도구)

검색어·기간·건수를 지정합니다. 회사 프로필이나 금액 선호 조건은 받지 않습니다.

```bash
python3 data_pipeline/collect_bids.py --query 개발 --from 2026-10-17 --to 2026-10-23 --limit 50 --search-only
python3 data_pipeline/collect_bids.py --resume data/collected/실행폴더
```

아래 기존 CLI의 다운로드는 목록의 전체 첨부를 받으므로, 화면의 단계별 흐름에는 위 `/search-bids`·`/fetch-*` API를 사용합니다.

`--query`를 여러 번 쓰면 OR 조회합니다. `--search-only`는 파일에 접근하지 않고 목록·첨부 링크만 저장합니다. `--resume`은 새 폴더를 만들지 않고 실패 파일을 재시도하며 기존 다운로드를 재사용합니다. 공식 G2B/PPS 첨부 URL만 허용하고 HTML 안내 응답과 50MB 초과 파일을 거부합니다.

[나라장터 입찰공고정보서비스](https://www.data.go.kr/data/15129394/openapi.do)의 `getBidPblancListInfoServcPPSSrch`를 사용합니다. API가 제공하는 첨부 URL 1~10과 별도 표준공고서 URL을 사용하며 화면의 모든 첨부를 보장하지 않습니다.

## 변환·전처리

```bash
data_pipeline/.venv/bin/python data_pipeline/prepare_documents.py --run-dir data/collected/실행폴더 --convert-hwp
```

원본은 보존하고 PDF는 `converted/`에 저장합니다. 변환 기록에는 원본/PDF 해시·경로·상태를 남깁니다. PDF 헤더·페이지·텍스트 추출·심한 한글 반복 손상을 검사합니다. 같은 파일은 재사용합니다.

페이지는 PDF 뷰어의 첫 장부터 센 1 기반 순서이며, 청크는 페이지 안에서 1,000자·중첩 200자입니다. 공고번호·차수·파일명·쪽수·수집일·URL을 보존합니다. 원본은 수정하지 않고 적재 텍스트의 이름·식별번호를 마스킹하며 공개 전화번호·이메일은 보존합니다.

같은 공고의 긴 동일 페이지는 검색용 청크에서만 합치고 `equivalent_sources`에 대체 출처를 남깁니다. 서로 다른 공고를 합치거나 원본을 삭제하지 않습니다.

## 기존 오프라인 산출물 (`data/corpus`)

| 경로 | 용도 |
|---|---|
| `pdf20/` | 기존 오프라인 대표 PDF와 출처 매니페스트 |
| `raw/`, `converted/`, `conversions.jsonl` | 원본·변환 PDF·변환 이력 |
| `bids.csv` | 공고명·기관·공고일·금액·마감·업종·지역·공동수급·파일명·출처 근거 |
| `README.md` | 공고번호·차수·공고 URL·수집일·파일명 출처표 |
| `processed/pages.jsonl` | 페이지 텍스트와 출처 |
| `processed/chunks.jsonl` | 임베딩용 청크와 출처 |
| `processed/documents.jsonl`, `needs_attention.jsonl` | 첨부별 추출 상태와 검토 대상 |
| `validation.json`, `VALIDATION.md`, `page_reviews.json` | 데이터 품질 검수와 페이지 확인 기록 |

`bids.csv`의 조건은 원문 발췌·기록입니다. 미명시나 상충 문구를 확정된 참가 조건으로 바꾸지 않습니다. `deadline_schedule`도 문서에 기록된 제출 일시이며 D-day나 준비 일정을 계산하지 않습니다. `metadata_needs_review`는 추출 데이터 확인 표시입니다.

## FAISS 및 데이터 적재 API

```bash
data_pipeline/.venv/bin/python -m data_pipeline.ingest --run-dir data/corpus
# 운영: 기존 RAG 서버 하나에 data_pipeline.api.router가 등록되어 있습니다.
cd rag-code-template_ext
../data_pipeline/.venv/bin/python -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001 --workers 1
```

- `POST /upload-paper`: PDF 파일과 공고번호·차수·출처를 누적 적재합니다.
- `POST /upload-topic`: 등록된 공식 웹 주제를 누적 적재합니다.
- `GET /data-status`: PDF·웹 적재 건수를 확인합니다.

위 RAG 실행에는 RAG의 `requirements-e.txt`도 설치되어 있어야 합니다. standalone `data_pipeline.api:app`은 기존 테스트용으로 유지하지만 운영 서버를 따로 띄우지 않습니다.

FAISS는 `data/indexes/pdf`·`data/indexes/web`에 JSON 출처와 함께 저장합니다. 기본 임베딩은 `text-embedding-3-small`이며 오프라인 테스트는 `local-char-ngram-v1`을 사용합니다. 실시간 API는 `upsert(records)`로 누적합니다. 기존 오프라인 ingest는 전체 교체를 수행하므로 `BID_INDEX_ROOT`를 별도 경로로 지정해야 합니다. 검수 실패 자료는 적재를 중단합니다. 답변 생성·추천·점수 계산은 이 파트에서 제공하지 않습니다.

## 점검

```bash
data_pipeline/.venv/bin/python -m data_pipeline.audit_dataset --run-dir data/corpus
data_pipeline/.venv/bin/python -m unittest discover -s data_pipeline/tests -v
```

현재 적용 검증은 단위·모의 검사 24개입니다. 실제 API·다운로드·변환 도구·운영 임베딩·RAG 전체 기동은 실행하지 않았습니다. 테스트 임시 디렉터리는 정리했고 기존 데이터와 인덱스는 변경하지 않았습니다. 기존 코퍼스 통합 검사는 별도이며 고정 20건 평가 완료를 뜻하지 않습니다.
