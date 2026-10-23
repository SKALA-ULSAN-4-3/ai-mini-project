# 확정 흐름 MD: 1번 데이터 파트 적용 결과

기준: 사용자가 첨부한 「확정 흐름 · 팀원별 변경 가이드」의 **1번 데이터** 및 그에 필요한 공통 규칙. 2026-10-23 작업. 다른 팀원 기능은 구현하거나 수정하지 않는다.

## 적용 기준과 실제 pull

로컬 소스는 프로젝트 외부 `../develop-sync-backup-20261023-162954/`에 복구 사본을 남겼다. `git fetch origin develop` 후 사용자의 덮어쓰기 지시에 따라 로컬 develop을 원격에 맞추고 `git pull --ff-only origin develop`을 실행했다. 결과는 `Already up to date.`이며 HEAD와 origin/develop은 `ed19475873a3ec922b53e0ec4e54b648282e1ff2`다. 이후 변경은 data_pipeline 내부에만 적용했다. 커밋·push는 하지 않았다.

이전 로컬의 bid_workflow, recommendations, delivery, summaries와 관련 API·문서는 복원하지 않았다. develop의 collect_bids, prepare_documents, privacy, metadata, convert_documents, knowledge를 기반으로 다시 연결했다. bid_logic 및 RAG·인증·화면 코드는 develop 원본을 유지한다.

고정 `dataset_selection.json`은 사용자 지시에 따라 삭제했다. 기존 CLI의 사용자 지정 목록 입력 옵션은 호환성을 위해 남겨 두었으며 고정 목록을 자동 복원하지 않는다. 기존 실제 데이터·인덱스는 유지한다.

## 추가한 API 네 개

구현: `api.py`의 기존 `router`와 `search_jobs.py`. develop에 있는 기존 CLI·적재 API는 유지했다. 이전 로컬에만 있던 `/bid-runs` 경로는 복원하지 않았다.

### ① 검색: POST /search-bids

```json
{
  "from": "2026-10-17",
  "to": "2026-10-23",
  "queries": ["시스템", "개발"],
  "limit": 100
}
```

`limit`는 API 후보 조회 수(1~100)다. 최신 차수·취소 제외 후 결과는 더 적을 수 있다. 응답은 `search_id`, `items`, `cached`, `collected_at`, `cache_seconds`, `page_limit_reached`다. 이 단계는 다운로드·변환·임베딩·점수 계산을 하지 않는다. 회사 프로필을 이용한 상위 20건 선별은 3번의 담당 영역이다.

각 공고에 `bid_no`, `bid_order`, `title`, `agency`, `published_at`, `deadline`, 금액, 원문 URL, `attachments[{file_name,url,kinds}]`를 제공한다. 다음 제한 필드를 원래 API 필드명으로 포함한다.

`indstrytyLmtYn`, `rgnLmtBidLocplcJdgmBssNm`, `jntcontrctDutyRgnNm1~3`, `cmmnSpldmdMethdNm`, `cntrctCnclsMthdNm`, `presmptPrce`, `asignBdgtAmt`, `bidClseDt`.

응답은 필드 허용 목록으로 구성해 API 담당자 성명·전화·이메일 필드를 제외한다. 파일명과 원문 링크는 보존한다. 원시 API 스냅샷은 서버 내부에서만 사용한다. 같은 기간·검색어·조회 수는 **300초** 동안 같은 `search_id`로 재사용한다. 기간이 지나거나 조건이 다르면 새로 검색한다.

### ③ 공고문 준비: POST /fetch-notices

```json
{
  "search_id": "검색 응답의 32자리 ID",
  "bids": [
    {"bid_no": "실제공고번호", "bid_order": "000"}
  ]
}
```

공고번호·차수는 해당 검색 결과에서 고른 **중복 없는 1~20건**이다. 차수는 문자열로 선행 0을 보존한다. `bid_order` 대신 `revision` 입력도 허용한다.

응답은 HTTP 202와 `{job_id,status,total}`다. FastAPI `BackgroundTasks`에서 준비하며 진행률 API로 확인한다. RAG의 **동일한** `knowledge_bridge.classify_attachment()`를 사용해 `notice`인 첨부 또는 표준공고서 중 공고문 한 개를 고르고 PDF를 우선한다. 식별 실패는 해당 공고만 실패로 남기며 제안요청서·신청서·ZIP으로 대체하지 않는다.

API에 이름이 없는 표준공고서는 저장 파일명을 `표준입찰공고서`로 부여해 RAG의 공통 판별 함수도 공고문으로 인식하도록 했다. 공고문을 텍스트로 추출한 뒤 `bid_no`, `bid_order`, `file_name`, `page`와 출처·해시를 넣어 `upsert(records)`로 누적 적재한다. 새 실시간 경로에서는 `ingest_processed()`와 `replace_all=True`를 사용하지 않는다.

### ⑥ 선택 첨부 준비: POST /fetch-documents

요청 구조·202 응답·진행률 형식은 `/fetch-notices`와 같다. 담당자가 고른 공고만 지정한다. 선택·승인 상태와 사용자 소유권 저장은 4번의 담당 영역이다.

- 전체 목록/키워드 검색을 다시 실행하지 않는다.
- 지정한 공고번호 하나씩만 `getBidPblancListInfoServc`로 차수를 재확인한다.
- 차수가 같으면 `search_id`에 저장한 첨부 URL을 사용한다. 재확인 응답의 링크로 조용히 교체하지 않는다.
- 정정공고면 새 차수의 링크를 별도 스냅샷으로 저장하고 해당 차수로 받는다. 응답에 `requested_bid_order`, 실제 `bid_order`, `revision_changed`를 제공한다. 이전 차수나 취소·철회 응답이면 중단한다.
- 성공 파일은 재사용하고 나머지 첨부를 받는다. 다른 공고의 첨부는 받지 않는다.
- 내부 PDF 변환·적재는 공고문과 제안요청서/과업 문서에 한정한다. 같은 이름의 PDF가 있으면 HWP를 다시 변환하지 않는다. 신청서·ZIP 등은 원본만 보존한다.
- 기존 문서와 다른 공고를 지우지 않고 누적 적재한다. 원본 다운로드 범위는 OpenAPI 첨부 URL 최대 10개와 표준공고서다.

새 차수가 나오면 UI/담당자가 변경된 차수를 확인해야 하며, 이 API가 승인이나 참가 가능 여부를 확정하지 않는다.

### 진행률: GET /jobs/{job_id}

```json
{
  "job_id": "작업 ID",
  "search_id": "검색 ID",
  "status": "partial_failed",
  "done": 2,
  "total": 2,
  "bids": [
    {"bid_no": "공고A", "bid_order": "000", "status": "completed", "error": null},
    {"bid_no": "공고B", "bid_order": "000", "status": "failed", "error": "공고문 첨부 식별 실패"}
  ]
}
```

작업 상태는 `queued`, `running`, `completed`, `partial_failed`, `failed`다. 공고별 중간 상태는 `downloading`, `converting`, `indexing`이다. `done`은 성공·실패를 포함해 처리를 마친 건수다. 실패 한 건 때문에 나머지 공고 처리를 중단하지 않는다. 다운로드·변환·추출 실패는 공고별로 남기며 일부 자료만 적재됐으면 부분 실패로 표시한다. SDK 오류 원문이나 인증키는 반환하지 않는다.

## 저장과 운영

기본 경로는 `data/searches/`이며 `BID_SEARCH_ROOT`로 변경할 수 있다.

| 경로 | 내용 |
|---|---|
| `{search_id}/search.json` | 검색 조건·원시 API 스냅샷. 화면 응답과 구분 |
| `{search_id}/revision-*.json` | 선택 단계에서 확인한 정정 차수의 스냅샷 |
| `cache-*.json` | 같은 조건 검색의 재사용 포인터 |
| `documents/{공고번호_차수}/` | 검색 ID와 독립적인 원본·변환·전처리 캐시 |
| `jobs/{job_id}.json` | 공고별 진행률·실패 상태 |

FAISS는 기존 `BID_INDEX_ROOT` 설정을 따른다. 여러 검색 ID에서 같은 공고를 선택해도 공고번호·차수별 캐시를 공유한다. 변환은 기존 프로젝트 프로필 충돌을 막기 위해 새 작업 경로 내에서 직렬화한다.

운영 서버는 MD 지시대로 **기존 RAG 서버(:8001) 한 개, uvicorn worker 1개**를 사용한다. RAG의 `requirements-e.txt`와 데이터의 `requirements.txt`가 함께 설치되어야 공통 판별 함수를 사용할 수 있다. 4번에서 JWT·사용자별 권한과 Docker/볼륨을 연결해야 한다. 다른 팀원 서버 코드는 수정하지 않았다.

`BackgroundTasks`는 프로세스 종료 후 자동 복구하는 작업 큐가 아니다. 재시작으로 중단된 작업은 재요청하고 파일 캐시를 재사용한다. 실제 작업 시간과 화면 폴링 간격은 실제 환경에서 측정해야 한다.

## 고정 목록 제외

고정 20건 목록(`dataset_selection.json`)은 현재 존재하지 않으며, 사용자 지시에 따라 복원·운영 대상에서 제외한다. 검색 결과에서 요청받은 공고를 처리한다. API의 최대 20건 요청 제한은 고정 데이터 목록과 별개의 배치 크기 제한이다.

## 적용 범위와 제외 사항

- 공고문 판별은 새 경로에서 RAG의 동일 함수를 사용한다. develop에는 이전 로컬의 notice_attachment()가 없으므로 이중 판별 경로를 복원하지 않았다.
- 새 첨부 준비 API는 최대 20건이다. 이전 로컬의 1~2건 선택 API는 복원하지 않았다. 사용자 선택·승인 저장은 4번 영역이다.
- 신청서 HWP/HWPX·ZIP 원본은 보존하고 내부 변환은 공고문/RFP만 수행한다. 이는 사용자의 기존 원본 전달 요구를 유지한 것이다.
- standalone `data_pipeline.api:app`은 develop의 기존 테스트용 진입점이라 유지했다. 운영은 기존 RAG 서버 한 개에 등록된 router를 사용한다.
- JWT·소유권·Docker·프로필·점수·요약·체크리스트·화면은 다른 담당 영역이므로 수정하지 않았다.
- 서버 설치/기동·실제 조회·작업시간 측정은 실행하지 않았다. 변환 환경 설치 방법은 기존 convert_documents.py --setup 안내를 따른다. 설치 Bash는 develop에 없으므로 이전 로컬 파일을 되살리지 않았다.

## 검증

실제 검색·다운로드·운영 임베딩·LibreOffice 설치/변환을 실행하지 않았다. 임시 디렉터리, 모의 API/다운로드/변환과 오프라인 테스트 벡터를 사용했으며 네트워크·운영 임베딩 호출을 차단했다. 새 테스트 파일은 만들지 않았다.

**24개 검사 통과**: develop 기존 단위 검사 13개(새 경로 목록에 맞춰 기존 API 경로 검사만 갱신), 아래 모의 흐름 8개 및 번호 조회 검사 3개. 실제 로컬 코퍼스에 의존하는 통합 검사 1개는 고정 목록 제거와 운영 데이터 접근 방지를 위해 실행하지 않았다.

모의 흐름·번호 조회 검사:

1. 검색 허용 필드·개인 연락처/성명 제외·최신/취소 제외·동일 조건 재사용.
2. 최초 PDF 공고문만 확보, 기존 다른 공고의 인덱스 유지, 재실행 다운로드 재사용.
3. 명시한 공고만 나머지 수신, 검색 재호출 없음, PDF 우선·서식 원본 보존, 캐시 재사용.
4. 공고문 누락 시 대체 다운로드 금지 및 다른 공고 계속 처리.
5. 정정 차수로 수신하고 이전 차수 자료 보존.
6. 잘못된 선택·중복·빈 목록·없는 job 거부.
7. 일부 첨부 실패·부분 실패 표시·실패 파일만 재시도.
8. 표준공고서가 RAG 공통 판별에서 notice로 인식되고 필수 메타데이터 포함.
9. 차수 확인이 선택 공고번호 하나와 번호 조회 모드만 사용하는지 확인.
10. 취소·조회 불가 공고를 그대로 재사용하지 않음.
11. 상위 API 오류의 인증키가 응답 오류에 포함되지 않음.

실제 번호 조회 오퍼레이션·다운로드·변환·임베딩 및 RAG 서버 전체 기동은 별도 실환경 확인이 남아 있다.
