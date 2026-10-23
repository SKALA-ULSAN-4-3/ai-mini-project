# 역할 1: 나라장터 데이터 파이프라인

공고 20건 선정·다운로드, HWP/HWPX→PDF 변환, 마스킹, `bids.csv`·출처표 작성, `/upload-paper`·`/upload-topic` 적재와 FAISS 인덱스 생성만 담당합니다.

기업별 적합성·참가자격 판정, 공고 요약·Q&A, 예상 점수·추천·체크리스트, 사용자 인증·프로필 DB·화면은 구현 범위에서 제외합니다. 기존 강의 예제는 별도 디렉터리에 유지합니다.

## 설정

프로젝트 루트 `.env`의 `DATA_GO_KR_SERVICE_KEY`(조회), `OPENAI_API_KEY`(임베딩)를 사용합니다. 값을 출력하거나 산출물에 기록하지 않습니다.

```bash
python3 -m venv data_pipeline/.venv
data_pipeline/.venv/bin/python -m pip install -r data_pipeline/requirements.txt
```

HWP/HWPX 변환은 Java 지원 LibreOffice + H2Orestart가 필요합니다. 현재 컴퓨터는 `data/tools/LibreOffice.app`의 LibreOffice 25.8.7.3 + H2Orestart 0.8.0 + JDK 21로 설정돼 있습니다. 다른 컴퓨터에서는 다음 초기 설정을 실행합니다.

```bash
data_pipeline/.venv/bin/python data_pipeline/convert_documents.py --setup --soffice /Applications/LibreOffice.app/Contents/MacOS/soffice
```

공식 확장 배포 파일은 SHA-256을 검증하고 프로젝트 전용 `data/tools/hwp-profile`에 등록합니다. 기존 LibreOffice 설정은 수정하지 않습니다. 26.8.1은 실제 첨부의 한글 손상이 발견돼 사용하지 않았습니다. [H2Orestart 공식 문서](https://github.com/ebandal/H2Orestart).

## 고정 공고 20건 만들기

프로젝트 루트에서 실행합니다. `dataset_selection.json`은 공고문과 제안요청서/과업지시서가 있는 SW 개발·고도화 자료의 고정 목록입니다. 선정 기준은 자료 수집용이며 회사별 추천이나 참가자격 판정이 아닙니다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.build_dataset --selection-file data_pipeline/dataset_selection.json
```

수집된 파일로 전처리·메타데이터·검수를 다시 실행합니다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.build_dataset --prepare-only
```

기본 조회 기간은 2026-08-01~2026-10-23이며 현재 데이터는 학습·평가용 과거 공고입니다. 현재 입찰 가능 여부는 판단하지 않습니다. 수집 목록 안에서 최신 차수만 사용하고 취소·철회 공고를 제외합니다.

## OpenAPI 자동 조회·다운로드 (X1)

검색어·기간·건수를 지정합니다. 회사 프로필이나 금액 선호 조건은 받지 않습니다.

```bash
python3 data_pipeline/collect_bids.py --query 개발 --from 2026-10-17 --to 2026-10-23 --limit 50 --search-only
python3 data_pipeline/collect_bids.py --resume data/collected/실행폴더
```

`--query`를 여러 번 쓰면 OR 조회합니다. `--search-only`는 파일에 접근하지 않고 목록·첨부 링크만 저장합니다. `--resume`은 새 폴더를 만들지 않고 실패 파일을 재시도하며 기존 다운로드를 재사용합니다. 공식 G2B/PPS 첨부 URL만 허용하고 HTML 안내 응답과 50MB 초과 파일을 거부합니다.

[나라장터 입찰공고정보서비스](https://www.data.go.kr/data/15129394/openapi.do)의 `getBidPblancListInfoServcPPSSrch`를 사용합니다. API가 제공하는 첨부 URL 1~10과 별도 표준공고서 URL을 사용하며 화면의 모든 첨부를 보장하지 않습니다.

## 변환·전처리

```bash
data_pipeline/.venv/bin/python data_pipeline/prepare_documents.py --run-dir data/collected/실행폴더 --convert-hwp
```

원본은 보존하고 PDF는 `converted/`에 저장합니다. 변환 기록에는 원본/PDF 해시·경로·상태를 남깁니다. PDF 헤더·페이지·텍스트 추출·심한 한글 반복 손상을 검사합니다. 같은 파일은 재사용합니다.

페이지는 PDF 뷰어의 첫 장부터 센 1 기반 순서이며, 청크는 페이지 안에서 1,000자·중첩 200자입니다. 공고번호·차수·파일명·쪽수·수집일·URL을 보존합니다. 원본은 수정하지 않고 적재 텍스트의 이름·식별번호를 마스킹하며 공개 전화번호·이메일은 보존합니다.

같은 공고의 긴 동일 페이지는 검색용 청크에서만 합치고 `equivalent_sources`에 대체 출처를 남깁니다. 서로 다른 공고를 합치거나 원본을 삭제하지 않습니다.

## 산출물 (`data/corpus`)

| 경로 | 용도 |
|---|---|
| `pdf20/` | 공고별 대표 PDF 20개와 출처 매니페스트 |
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
data_pipeline/.venv/bin/python -m uvicorn data_pipeline.api:app --port 8001
```

- `POST /upload-paper`: PDF 파일과 공고번호·차수·출처를 누적 적재합니다.
- `POST /upload-topic`: 등록된 공식 웹 주제를 누적 적재합니다.
- `GET /data-status`: PDF·웹 적재 건수를 확인합니다.

FAISS는 `data/indexes/pdf`·`data/indexes/web`에 JSON 출처와 함께 저장합니다. 기본 임베딩은 `text-embedding-3-small`이며 오프라인 테스트는 `local-char-ngram-v1`을 사용합니다. 동일 그룹 재업로드는 교체하고 전체 PDF 갱신은 현재 데이터셋으로 동기화합니다. 검수 실패 자료는 적재를 중단합니다. 검색·답변 생성 함수나 서비스용 추천 API는 제공하지 않습니다.

## 점검

```bash
data_pipeline/.venv/bin/python -m data_pipeline.audit_dataset --run-dir data/corpus
data_pipeline/.venv/bin/python -m unittest discover -s data_pipeline/tests -v
```

현재 20공고·74첨부·1,998페이지·2,849청크입니다. 공고문 및 제안요청서/과업지시서 확보는 20/20건입니다. 원본 레이아웃 전체 대조와 영향평가 이미지 부록 3페이지는 검토 대상으로 기록하며 OCR 완료로 표시하지 않습니다. 임시 테스트 입력·인덱스는 종료 시 삭제하고 기존 원본 수집 자료는 보존합니다.
