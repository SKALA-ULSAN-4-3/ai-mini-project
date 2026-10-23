# 나라장터 데이터 파이프라인

## 코드 구조와 변경 내역

개인정보·원문 메타데이터·PDF 페이지 처리는 `prepare_documents.py`, 공통 파일 처리는 `common.py`, 공공 API 통신은 `g2b_client.py`에서 확인할 수 있습니다. 수집 단계 제어는 `bid_workflow.py`가 맡습니다. CLI 명령과 HTTP API 계약은 유지합니다.

## 현재 연결 흐름: 공고문 → bid-logic 추천 → 사용자 선택 → 원본 첨부 전달

[Vue 연결 API 안내](DELIVERY_API.md)에 요청·응답·클라이언트 예제를 정리했습니다. `feat/bid-logic`의 원본 패키지는 수정하지 않고 연결 모듈이 공고문 페이지·메타데이터·임베딩 거리를 전달합니다. API 탐색은 추천까지 수행하고, 사용자 선택 후 공고 1~2건의 원본 첨부를 ZIP 또는 개별 파일로 제공합니다. 신청서 HWP/HWPX는 전달을 위해 변환하지 않습니다.

추천은 조건 필터와 PDF 유사도 순위이며 정량 평가점수나 낙찰확률이 아닙니다. 아래 CLI의 `preliminary`는 종전 키워드 사전 분류이며, 실제 bid-logic 추천 결과는 API 및 `recommendations.json`을 사용합니다.

## 설정

Python 3.10 이상과 macOS 또는 Linux가 필요합니다. 현재 파일 잠금은 `fcntl`을 사용하므로 Windows 네이티브 실행은 지원하지 않습니다. Windows에서는 Linux 환경(예: WSL)에서 Python과 변환 도구를 함께 준비해야 합니다.

프로젝트 루트 `.env`의 `DATA_GO_KR_SERVICE_KEY`(조회), `OPENAI_API_KEY`(임베딩)를 사용합니다. 값을 출력하거나 산출물에 기록하지 않습니다.

```bash
python3 -m venv data_pipeline/.venv
data_pipeline/.venv/bin/python -m pip install -r data_pipeline/requirements.txt
```

`requirements.txt`에는 Python 패키지만 설치 항목으로 기록합니다. LibreOffice·Java·H2Orestart는 pip 패키지가 아니므로 별도로 준비합니다. 목록 조회·PDF 추출·원본 첨부 전달만 하는 경우 변환 도구는 필요하지 않습니다. 공고문이 HWP/HWPX인 경우 내부 평가용 PDF 변환에 필요합니다.

| 설치 대상 | 용도 | 이 프로젝트에서 확인한 버전/조건 |
|---|---|---|
| Python 패키지 | PDF 추출·FAISS·HTTP API·웹 원문·임베딩 | `requirements.txt`의 버전 범위 |
| LibreOffice | HWP/HWPX → PDF 실행 | **25.8.7.3**. Java를 지원하고 `soffice`, `unopkg`가 포함된 배포판 |
| Java JDK | H2Orestart 확장 실행 | **JDK 21**. LibreOffice와 CPU 아키텍처를 맞춤 |
| H2Orestart | LibreOffice의 한글 문서 읽기 확장 | **0.8.0**. 코드에 고정된 배포 파일과 SHA-256 사용 |

설치 순서는 다음과 같습니다.

1. [LibreOffice 공식 다운로드](https://www.libreoffice.org/download/)에서 OS·CPU에 맞는 Java 지원 배포판을 설치합니다. 이전 버전은 [공식 보관소](https://downloadarchive.documentfoundation.org/libreoffice/old/25.8.7.3/)에서 확인할 수 있습니다. 위 버전은 프로젝트의 변환 검증 기록이며 최신 권장 버전을 뜻하지 않습니다.
2. JDK 21을 설치하고 `java -version`으로 확인합니다. 필요하면 `JAVA_HOME`을 JDK 설치 경로로 지정합니다. macOS의 변환 실행기는 미설정 시 `/usr/libexec/java_home`으로 Java를 찾습니다.
3. 아래 설정 명령을 실행합니다. 이 명령이 H2Orestart 0.8.0을 다운로드·해시 검증하고 프로젝트 전용 프로필에 등록합니다. 별도 pip 패키지를 설치하거나 기본 LibreOffice 프로필에 확장을 수동 등록할 필요는 없습니다.

현재 컴퓨터의 검증 경로는 `data/tools/LibreOffice.app`입니다. 일반적인 macOS 설치 경로를 사용하는 새 컴퓨터의 설정 예시는 다음과 같습니다.

```bash
data_pipeline/.venv/bin/python data_pipeline/convert_documents.py --setup --soffice /Applications/LibreOffice.app/Contents/MacOS/soffice
```

Linux에서는 설치된 `soffice`의 절대 경로를 `--soffice`에 지정합니다. 설정은 `data/tools/converter.json`, 확장 프로필은 `data/tools/hwp-profile`에 저장하며 기존 LibreOffice 설정은 수정하지 않습니다. 변환된 한글·표·페이지 배치는 원문과 대조해야 합니다. 프로젝트의 기존 검증에서 26.8.1 조합은 한글 손상이 발견돼 채택하지 않았습니다. [H2Orestart 공식 문서](https://github.com/ebandal/H2Orestart).

## 공고문만 먼저 준비

프로젝트 루트에서 실행합니다. 최초 실행은 API 목록을 조회한 뒤 명확히 식별되는 공고문 한 개씩만 받습니다. 제안요청서·서식 등 나머지 첨부는 `deferred`로 남깁니다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.collect_bids --query 개발 --from 2026-10-17 --to 2026-10-23 --limit 50 --profile data_pipeline/company_profile.example.json
```

`--search-only`를 추가하면 목록·링크만 저장하며 공고문도 다운로드하지 않습니다. 같은 실행 폴더에서 프로필을 바꾸려면 `--resume`과 `--profile`을 함께 지정합니다. 이미 받은 공고문은 재사용하고 사전 분류와 평가 입력 버전을 갱신합니다.

`bid_list.json`에는 본문 기반 사전 분류와 페이지 근거, 미평가 상태(`score: null`), 첨부별 `deferred` 상태를 제공합니다. `recommended_bid_ids`는 키워드·금액 조건을 통과한 사전 후보이며 최종 자격 판정이나 점수 순위가 아닙니다. 공고문을 식별하지 못하면 다른 첨부를 대신 받지 않고 확인 필요로 남깁니다.

## 외부 점수 평가 연결

초기 목록에서는 점수 평가를 진행하지 않습니다. 사용자는 사업 개요·과업 범위·기간과 출처가 포함된 `recommendations.bids`를 보고 바로 공고 1~2건을 선택합니다. 공고문에 없는 평가표·정보를 임의로 만들지 않습니다. 점수 평가 연결은 다른 담당자의 후속 기능용으로 유지하며 사용자 선택의 선행 조건이 아닙니다.

[외부 평가 연계 규약](EVALUATION_HANDOFF.md)에 입력·결과 구조와 API를 정리했습니다. `evaluation_inputs.jsonl`에 기업 프로필과 공고문 페이지·출처·버전을 제공합니다. 점수 산식은 외부 담당자가 구현합니다. 외부 평가 결과 저장만으로는 첨부를 다운로드하지 않습니다.

## 사용자가 선택한 공고의 전체 첨부 다운로드

```bash
data_pipeline/.venv/bin/python -m data_pipeline.collect_bids --resume data/collected/실행폴더 --select-bid R26BK00000000_000
```

공고번호·차수는 탐색 결과의 실제 `bid_id`를 사용합니다. 선택된 한 공고의 API 첨부 목록 전체를 받으며 ZIP·서식 등 확장자로 제한하지 않습니다. 다른 공고의 첨부는 받지 않습니다. 성공한 공고문·첨부는 재사용하고 실패 항목은 재선택으로 재시도합니다. 현재 API가 제공하는 첨부 URL 1~10 및 별도 표준공고서가 대상입니다. 웹 화면의 모든 첨부와 같다고 보장하지 않습니다.

## 데이터셋 명령과 기존 오프라인 자료

```bash
data_pipeline/.venv/bin/python -m data_pipeline.build_dataset --query 개발 --profile data_pipeline/company_profile.example.json --count 20 --output data/my_run
```

이 명령도 초기에는 공고문만 준비하며 `data/my_run/discovery/`에 결과를 둡니다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.build_dataset --output data/my_run --select-bid R26BK00000000_000
```

기존에 받아 둔 `data/corpus`의 자료 후처리는 `--prepare-only`로 유지합니다. 이 경로는 새 다운로드를 하지 않습니다. 기존 데이터셋 건수는 과거에 구축한 자료이며 새로운 단계 분리 흐름의 다운로드 결과가 아닙니다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.build_dataset --prepare-only
```

[나라장터 입찰공고정보서비스](https://www.data.go.kr/data/15129394/openapi.do)의 `getBidPblancListInfoServcPPSSrch`를 사용합니다. 공식 G2B/PPS 첨부 URL만 허용하고 HTML 안내 응답과 50MB 초과 파일을 거부합니다.

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

`bids.csv`의 조건은 원문 발췌·기록입니다. 미명시나 상충 문구를 확정된 참가 조건으로 바꾸지 않습니다. `deadline_schedule`도 문서에 기록된 제출 일시이며 D-day나 준비 일정을 계산하지 않습니다. `metadata_needs_review`는 추출 데이터 확인 표시입니다.

## FAISS 및 데이터 적재 API

```bash
data_pipeline/.venv/bin/python -m data_pipeline.ingest --run-dir data/corpus
data_pipeline/.venv/bin/python -m uvicorn data_pipeline.api:app --port 8001
```

- `POST /upload-paper`: PDF 파일과 공고번호·차수·출처를 누적 적재합니다.
- `POST /upload-topic`: 등록된 공식 웹 주제를 누적 적재합니다.
- `GET /data-status`: PDF·웹 적재 건수를 확인합니다.
- 탐색·외부 평가 연결·사용자 선택 API는 [연계 규약](EVALUATION_HANDOFF.md)을 참고하세요.

FAISS는 `data/indexes/pdf`·`data/indexes/web`에 JSON 출처와 함께 저장합니다. 기본 임베딩은 `text-embedding-3-small`이며 오프라인 테스트는 `local-char-ngram-v1`을 사용합니다. 동일 그룹 재업로드는 교체하고 전체 PDF 갱신은 현재 데이터셋으로 동기화합니다. LLM 답변 생성과 점수 계산은 제공하지 않습니다. 초기 탐색은 자동 임베딩·웹 자료 적재를 실행하지 않습니다.
