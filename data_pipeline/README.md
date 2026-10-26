# 역할 1: 나라장터 데이터 파이프라인

요청한 공고의 검색·다운로드, HWP/HWPX→PDF 변환, 마스킹, `bids.csv`·출처표 작성, `/upload-paper`·`/upload-topic` 적재와 FAISS 인덱스 생성만 담당합니다.

기업별 적합성·참가자격 판정, 공고 요약·Q&A, 예상 점수·추천·체크리스트, 사용자 인증·프로필 DB·화면은 구현 범위에서 제외합니다. 기존 강의 예제는 별도 디렉터리에 유지합니다.

## 설정

프로젝트 루트 `.env`의 `DATA_GO_KR_SERVICE_KEY`(입찰공고·첨부·제한 상세), `DATA_GO_KR_SCSBID_SERVICE_KEY`(개찰결과·재입찰), `OPENAI_API_KEY`(임베딩)를 사용합니다. 두 공공데이터 키는 별도 변수로 읽으며 서로 대체하지 않습니다. 값을 출력하거나 산출물에 기록하지 않습니다.

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


## 화면 연결용 확정 흐름


1. `POST /search-bids`: **게시 시작일~오늘 게시된 공고 중, 오늘~마감 종료일(양 끝 포함)에 마감하는 공고**의 목록과 첨부 링크를 조회해 search_id로 저장합니다. 마감일이 비어 있거나 읽을 수 없는 공고는 기간 포함을 확인할 수 없어 검색 결과에서 제외합니다. 다운로드·회사별 추천은 하지 않습니다.
2. `POST /fetch-notices`: 검색 결과에서 다른 담당 로직이 고른 최대 20건의 공고문 한 개씩만 받아 변환·누적 적재합니다.
3. `GET /jobs/{job_id}`: 공고별 진행률·실패를 확인합니다.
4. 담당자가 공고를 명시적으로 선택한 후 `POST /fetch-documents`: 선택한 공고번호의 차수만 재확인하고 저장한 링크로 나머지 첨부를 받습니다. 정정공고면 새 차수를 사용합니다.

### 개찰·재입찰에 따른 추천 입력 제외

`bid_progress.py`가 [나라장터 낙찰정보서비스](https://www.data.go.kr/data/15129397/openapi.do)의
`getOpengResultListInfoServc`와 `getOpengResultListInfoRebid`를 공고번호로 조회하고 정확한 차수만 사용합니다.
개찰결과가 있거나 개찰일시·입찰마감일시가 지난 공고는 `마감`으로 처리해 추천에 전달하지 않습니다.
미래 개찰 예정일만 있는 공고는 개찰 완료로 처리하지 않습니다. 개찰결과 없이 예정일시만 지난 경우에는
실제 개찰 확인과 구분하여 `opening_confirmed: false`와 사유를 남깁니다.

같은 공고·차수·입찰분류의 최신 재입찰 회차에서 새 마감일시가 남아 있고, 그 회차가 이미 개찰완료·유찰된
기록이 없으면 새 마감일을 검색 기간과 추천 판정에 사용합니다. 재공고 여부나 재입찰 허용 여부만으로
재입찰 진행 중이라고 확정하지 않습니다. 원래 마감일은 `original_bidClseDt`에 보존합니다.
재입찰 허용 공고는 기존 마감이 검색 기간 밖이어도 새 회차를 먼저 확인합니다.

이 확인은 후보 수 제한 전에 수행합니다. 검색 스냅샷에는 공개 상태 근거만 보관하며 업체·투찰자 정보는 저장하지 않습니다.
`/search-bids`의 `progress_excluded`에 마감·조회 실패로 제외한 공고와 이유를 반환합니다.
조회 실패를 접수 가능으로 간주하지 않으며 실패 결과는 검색 캐시로 재사용하지 않습니다.
완료된 재입찰 또는 캐시 확인 중 마감이 지난 회차도 추천에 넘기지 않습니다.
키·코드를 변경한 뒤에는 서버를 재시작하고 새 검색을 실행하세요. 기존 브라우저 목록은 자동으로 다시 검색되지 않습니다.

공고문 판별은 RAG의 `knowledge_bridge.classify_attachment`를 그대로 사용합니다. 공고문을 식별하지 못하면 다른 첨부로 대체하지 않습니다. 신청서 HWP·ZIP은 원본을 보존하고 공고문·제안요청서·협약문서만 내부 PDF 변환·적재합니다. 검색 응답에서 API 담당자 성명·연락처 필드는 제외하지만 원본과 추출된 공개 업무 연락처는 보존합니다.

### 파일첨부와 제안요청정보의 별도 조회

일반 파일첨부는 `ntceSpecDocUrl1~10`·`stdNtceDocUrl`에서 읽고, 제안요청정보는 같은
[공식 입찰공고정보서비스](https://www.data.go.kr/data/15129394/openapi.do)의
`getBidPblancListInfoEorderAtchFileInfo`에서 공고번호(`inqryDiv=2`)로 조회합니다.
일반 첨부는 응답에 실제 존재하는 `ntceSpecDocUrlN` 순번을 모두 읽습니다.
11번 이후 변환본이 응답에 포함되면 10개 제한으로 누락하지 않습니다.
파일명 없는 `stdNtceDocUrl`은 다운로드 헤더로 실제 이름을 확인한 뒤 공고문 PDF를
HWP보다 먼저 선택합니다. 헤더 조회 실패 시 기존 목록을 유지하며 PDF가 있다고 추정하지 않습니다.
`/fetch-notices`도 API 키가 있으면 선택 공고를 재조회해 같은 차수의 새 첨부를 반영합니다.
공고문 준비에서 제안요청서 HWP는 식별·대기 상태로 남기고, 선택 후 `/fetch-documents`에서 처리합니다.
추출 실패 메시지는 파일명과 `conversion_failed`·`empty_text` 등의 실제 준비 상태를 함께 표시합니다.
응답의 `bidNtceNo`·`bidNtceOrd`가 선택 공고·차수와 정확히 일치하는 첨부만 합칩니다.
`eorderAtchFileNm`·`eorderAtchFileUrl`·`eorderDocDivNm`을 보존하며 URL 중복은 제거합니다.
API 파일명이 비어 있으면 해당 공식 다운로드 주소의 `Content-Disposition`에서 파일명을 보완합니다.
파일명을 확인할 때는 범위 GET 요청의 헤더만 읽고 닫으며 본문을 저장하지 않습니다.
헤더에도 이름이 없거나 오류 페이지·비공식 주소이면 조회 실패로 남깁니다.
현재 `DATA_GO_KR_SERVICE_KEY`를 사용하고, 공식 G2B/PPS 다운로드 주소만 허용합니다.

검색에서는 일반 첨부에 RFP가 없는 후보에 e발주 목록을 보완 조회합니다(동시 최대 4건).
기존 일반 첨부만 있는 캐시는 재사용하지 않습니다. 다운로드는 선택 후 수행합니다.
`/fetch-documents`는 최신 공고·차수를 확인한 뒤 e발주 목록도 다시 조회하고 두 경로의 첨부를 받습니다.
HWP/HWPX 제안요청서·협약문서는 기존 LibreOffice 변환 → PDF 텍스트 추출 → 청크 적재를 사용합니다.
협약문서만 받았을 때는 제안요청서 준비 완료로 표시하지 않습니다.

목록·작업의 `attachment_lookup_status`는 `complete`(조회 성공), `unavailable`(조회 실패),
`not_checked`(미조회)를 구분합니다. 조회 실패를 첨부 없음으로 바꾸지 않습니다.
파일의 `source`는 `notice`(일반 파일첨부) 또는 `eorder`(제안요청정보)이며,
`document_type`은 e발주 문서구분명입니다. `files[].preparation_status`·`preparation_error`로
`conversion_failed`, `empty_text` 등의 준비 실패 원인을 확인할 수 있습니다.
스캔 PDF는 OCR을 수행하지 않으며 HWP 변환 도구 실패 시에도 원본은 보존하고 `rfp_ready=false`를 반환합니다.

공식 [입찰공고정보서비스 참고문서](https://www.data.go.kr/data/15129394/openapi.do)의
`getBidPblancListInfoServcPPSSrch` 날짜 조회는 게시일(`inqryDiv=1`)·개찰일(`2`)만 지원합니다.
FE의 시작일은 **게시 시작일**, 종료일은 **마감 종료일**입니다. 게시 공고는 FE 시작일~오늘(서울 날짜)만 조회하고,
그중 마감일이 오늘~FE 종료일(양 끝 포함)에 속하는 공고만 전달합니다. 시작일에서 과거 15일을 추가하지 않습니다.
예를 들어 오늘이 10월 26일이고 FE에 10월 1일~11월 30일을 입력하면, 게시기간은 10월 1일~10월 26일,
마감일 범위는 10월 26일~11월 30일입니다. 미래의 게시 시작일 또는 오늘보다 이전인 마감 종료일은 422로 거부합니다.
조회 구간이 28일을 넘으면 API가 허용하는 크기로 나눕니다.
검색 응답의 `publication_from/to`와 `deadline_from/to`로 두 범위를 구분합니다. FE는 반환된
`deadline_from/to`를 `/bids`·`/bids/recheck`에 전달하며, 연결 계층도 같은 기준으로 검색 기간을 검증합니다.
공식 API의 마감 공고 제외 조건도 사용하며 개찰·재입찰 판정은 별도로 유지합니다.
`BID_SEARCH_LOOKBACK_DAYS`는 더 이상 사용하지 않습니다. 기존 `.env`에 남아 있어도 무시합니다.

한 검색에서 목록 조회 100회 또는 구간별 20페이지 한도에 도달하면 `page_limit_reached=true`로 반환하고
화면에 일부 공고가 누락될 수 있음을 표시합니다. `search_coverage`에는 실제 탐색 게시기간·조회 횟수·중단 사유를 남깁니다.
요청한 후보 건수에 도달한 경우도 `stop_reason=candidate_limit`로 구분합니다. 일부 기간 조회를 전체 이력 조회 완료로 표시하지 않습니다.
탐색 방식이 다른 기존 캐시는 재사용하지 않습니다. 기존 오프라인 CLI의 게시일 검색·고정 평가셋은 유지합니다.

`notice_only=true`는 e발주 목록 조회까지 성공하고 제공된 첨부가 모두 공고문으로 식별된 경우입니다.
첨부 목록이 없거나 종류가 미확인 또는 e발주 조회가 실패했다면 공고문만 있다고 단정하지 않습니다.
맞춤 추천에서는 다른 후보를 먼저 배치하고 공고문만 있는 후보는 뒤로 보냅니다.
화면에 “해당 공고는 공고문만 있다” 안내를 표시하며 기본 선택에서 제외하지만, 사용자가 직접 선택할 수 있습니다.

### 지역·업종 제한 상세

실시간 검색은 동일 공고번호·차수로 공식 `getBidPblancListInfoPrtcptPsblRgn`(참가가능지역)과
`getBidPblancListInfoLicenseLimit`(면허제한)을 조회하고 `region_restriction`·`industry_restriction`에 보존합니다.
면허제한명·4자리 업종코드(선행 0 포함)·제한그룹·순번·대체 허용업종·주력분야를 전달합니다.
`indstrytyLmtYn=N`은 업종제한 없음으로 처리하며 불필요한 면허 상세 조회를 생략합니다.

| 상태 | 표시·처리 |
| --- | --- |
| `limited` | 실제 참가가능지역명 또는 대상 업종명·코드 표시 |
| `none` | 명시적으로 확인한 제한 없음 (`전국`, 업종제한 `N` 등) |
| `not_listed` | 상세 API 조회 성공·등록 내역 없음. 공고문 확인 필요이며 제한 없음으로 확정하지 않음 |
| `unknown` | 제한 신호는 있으나 상세 대상 값이 미등록·불완전 |
| `unavailable` | 상세 조회 실패. 등록 내역 없음과 구분하고 재시도 안내 |

성공한 상세 조회는 `data/searches/restriction-cache/`에서 공고·차수·업종제한 플래그별로
최대 300초 재사용하고 실패는 캐시하지 않습니다. 상세 조회가 실패한 검색 결과도 캐시로 고정하지 않아 재검색에서 다시 조회합니다.
이전 미확인 검색 캐시는 새 검색에서 재사용하지 않습니다.
검색·추천 응답의 상세 필드와 화면의 `summary`에 조건을 표시하며, 적재 후 재확인에도 같은 상세 정보를 전달합니다.
확인된 시·도 제한이 회사 소재지와 다르면 제외합니다. 시군구 제한을 시·도 전체로 확대하지 않으며,
회사 프로필이 시·도만 제공하면 상세 소재지 확인이 필요함을 별도 표시합니다.
여러 면허의 제한 그룹·주력분야를 단순 OR 배열로 바꾸지 않습니다. 실제 대상 업종은 표시하되
복수 업종의 동시 충족·대체 허용·공동수급에 의한 충족 여부는 공고문 검토 대상으로 유지합니다.

### 다운로드와 제안요청서 준비 상태

`/search-bids`의 `attachments`는 API가 제공한 파일명·URL·종류이며,
`rfp_listed`는 공통 판별 함수로 제안요청서류를 식별했는지 표시합니다.
`false`는 API 목록에서 식별하지 못했다는 의미이며, 실제 공고에 제안요청서가 없다는 확정이 아닙니다.
ZIP 내부나 다른 이름으로 배포된 문서는 별도 확인이 필요합니다.

`/fetch-documents`는 같은 차수여도 공고번호 재조회에서 받은 최신 첨부 목록으로 처리합니다.
`GET /jobs/{job_id}`의 공고별 응답을 다음과 같이 구분합니다.

| 필드 | 의미 |
| --- | --- |
| `download_complete` | 이번 단계에서 선택된 모든 첨부의 다운로드 완료 및 실제 파일 존재 여부 |
| `rfp_ready` | 제안요청서류의 텍스트 청크가 실제 인덱스에 적재되었는지 여부 |
| `rfp_status` | `ready`, `not_listed`, `not_requested`, `download_failed`, `not_indexed`, `lookup_failed`, `not_checked` |
| `rfp_files` | 식별한 제안요청서류의 파일명·원본 URL·다운로드 상태·적재 청크 수 |
| `files` | 전체 첨부의 파일명·원본 URL·출처·문서구분·다운로드/준비 상태·적재 청크 수 |
| `detail_url` | API에 제공된 공고 상세 주소. 제안요청서 위치가 미확인일 때 첨부를 확인할 경로 |

공고서만 적재되었다면 다운로드가 끝나도 `rfp_ready=false`입니다.
전체 첨부 단계에서는 이를 `completed`로 표시하지 않고, 공고서 적재가 성공한 경우
`partial_failed`와 확인 사유를 반환합니다. 변환 실패 시에도 다운로드 완료 여부는 별도로 전달합니다.
화면은 `rfp_ready=false`인 공고를 채점 화면으로 넘기지 않습니다.
다운로드가 끝난 후에도 `rfp_status=not_indexed`이면 변환·텍스트 추출 상태를 확인해야 합니다.
과업지시서·규격서도 기존 공통 판별의 제안요청서류에 포함되며, 준비 완료가 평가표의 존재를 보장하지는 않습니다.

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


## Render 통합 배포

데이터 API와 기존 RAG를 서비스 하나에서 실행합니다. Java 인증·프로필은 기존 백엔드에 연결합니다.

| 설정 | 값 |
| --- | --- |
| 서비스 | `https://ai-mini-datapipeline.onrender.com` |
| 배포 브랜치 | `develop` |
| Root Directory / Build Context | 비움 / `.` |
| Dockerfile | `data_pipeline/Dockerfile.render` |
| 실행 앱 / worker | `data_pipeline.render_rag_app:app` / 1 |
| 헬스 | `/health` |
| BACKEND_URL | `https://ai-service-mini-backend.onrender.com` |
| 비밀 환경변수 | `DATA_GO_KR_SERVICE_KEY`, `DATA_GO_KR_SCSBID_SERVICE_KEY`, `OPENAI_API_KEY` |

Dockerfile의 기본 실행 명령을 사용합니다. LibreOffice·Java·한글 글꼴·H2Orestart는 이미지에서 설치합니다.
호스트 `.env`, 원문, 인덱스, 가상환경은 이미지에 포함하지 않습니다.
무료 인스턴스의 저장소는 재배포 시 사라질 수 있습니다. 원문·인덱스를 준비한 뒤 재배포하면 다시 적재해야 합니다.
영속 디스크를 사용하는 경우 `BID_SEARCH_ROOT`와 `BID_INDEX_ROOT`를 마운트 아래로 지정합니다.

공개 헬스·Swagger와 실제 인증된 검색의 성공은 별도로 확인합니다. 다음 검증기는 프로젝트 루트 `.env`를 읽으며,
`MINI_TEST_TOKEN` 또는 `MINI_TEST_BUSINESS_NUMBER`·`MINI_TEST_PASSWORD`가 있어야 인증된 흐름을 검사합니다.
비밀값은 명령행이나 문서에 적지 않습니다. 토큰이 없어도 공개 경로는 점검하지만 전체 성공으로 처리하지 않습니다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.verify_render --origin http://localhost:5174
```

기간·검색어는 `--from`, `--to`, `--query`로 지정합니다. 검증은 실제 목록 검색과 `/bids` 호출을 수행하므로
등록된 기업 프로필과 검색 가능한 기간을 사용합니다. 첨부 다운로드·임베딩·Q&A는 이 명령으로 검증하지 않습니다.
결과는 Git에서 제외된 `data/render-verification.json`에 기록합니다.
`data_pipeline_passed`는 인증된 검색→`search_id`→`/bids`까지, `passed`는 Java 로그인 CORS까지 포함합니다.
로그인 사전 요청은 상태 코드뿐 아니라 허용 출처·메서드·헤더가 있어야 통과합니다.
Java의 프론트 출처 허용 설정은 인증 담당자가 관리합니다.

문서가 없는 배포에서는 인증 후 실제 검색의 `search_id`와 선택 공고번호·차수로 `/fetch-notices`를 호출하고
`/jobs/{job_id}`의 완료 상태를 확인합니다. 사용자 선택 후 전체 첨부는 `/fetch-documents`로 받습니다.
평가 자료를 운영에 자동 적재하지 않습니다.

## 공식 평가 원문 재현

운영 실시간 검색과 구별하여 아래 공식 평가셋을 사용합니다. 고정 수집 목록 `dataset_selection.json`을 복원하지 않습니다.

- 목록: `rag-code-template_ext/evaluation/real/bids.csv` (20개 공고·차수).
- 평가 기준: 같은 폴더의 `manifest.json` (3개 기업 프로필, 고정 평가 시각).
- 원문 기준: 같은 폴더의 `source-manifest.json` (74개 URL·파일명·차수·SHA-256).

해시나 차수가 다르면 공식 기준을 임의로 바꾸지 않고 평가 담당자에게 확인합니다.
다운로더는 URL 재다운로드를 통해 원문을 공유하며 원본 바이너리를 Git에 넣지 않습니다.
나라장터 API 키·OpenAI 키·LibreOffice 없이 다운로드·추천 라벨 재현이 가능합니다.
Python 3.10 이상에서 최소 환경을 준비하거나 기존 데이터 가상환경을 사용합니다.

```bash
python3 -m venv .venv-evaluation
.venv-evaluation/bin/python -m pip install 'pypdf>=6.10,<7' tzdata
.venv-evaluation/bin/python -m data_pipeline.evaluation_sources
.venv-evaluation/bin/python -m data_pipeline.evaluation_sources --verify-only
cd rag-code-template_ext
../.venv-evaluation/bin/python -m unittest discover -s tests -p test_recommendation_labels.py -v
```

Windows에서는 `.venv-evaluation/bin/python` 대신 `.venv-evaluation\Scripts\python.exe`를 사용합니다.
테스트 완료 기준은 `Ran 2 tests`, `OK`, 건너뜀 0개입니다. 근거 파일이 없어 건너뛴 검사는 완료가 아닙니다.
기존 원문을 재사용하려면 수집 시 `--reuse-manifest data/corpus/attachments.csv`를 지정할 수 있습니다.

기본 출력은 `data/evaluation-source-20261023/`입니다.

| 출력 | 용도 |
| --- | --- |
| `raw/{공고번호}_{차수}/` | 해시가 일치하는 원문 |
| `attachments.json` | 검증 성공 첨부의 실제 저장 경로 |
| `evidence.json` | PDF 페이지·HWPX XML 표의 평가 근거 |
| `download-failures.json` | 원문·근거 추출 실패 목록 |
| `verification.json` | 원문 수·공식 목록 해시·성공 여부 |

성공 파일은 재사용하고 실패 파일만 다시 받습니다. 임시 다운로드가 기준 해시와 일치해야 최종 원본으로 이동합니다.
원문·차수 검증이나 근거 추출에 실패하면 기존 `attachments.json`·`evidence.json`을 제거하여
오래된 성공 결과가 테스트에 사용되지 않도록 합니다. 원본 파일은 삭제하지 않습니다.
`--verify-only`는 원본 해시만 확인하며 근거를 재생성하지 않습니다. 근거 생성은 기본 수집 명령으로 수행합니다.
HWPX 근거는 XML 위치를 유지하며 PDF 쪽수로 바꾸지 않습니다.
공식 정답·프로필·평가 시각·운영 인덱스는 변경하지 않습니다.
다른 PC 재현과 정답의 사람 검토는 평가 담당자가 별도로 수행합니다.
