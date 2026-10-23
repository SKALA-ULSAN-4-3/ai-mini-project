# Vue 연결: 추천 목록과 원본 첨부 전달

```bash
data_pipeline/.venv/bin/python -m uvicorn data_pipeline.api:app --port 8001
```

`http://localhost:8001/docs`에서 요청·응답을 확인한다. 루트 `.env`에 `DATA_GO_KR_SERVICE_KEY`, `OPENAI_API_KEY`를 설정한다. 기본 임베딩은 `text-embedding-3-small`이다. 공고문이 HWP/HWPX이면 README의 내부 PDF 변환 환경도 필요하다.

## 1. 탐색과 추천

```http
POST /bid-runs
Content-Type: application/json

{
  "start": "2026-10-17",
  "end": "2026-10-23",
  "queries": ["개발", "시스템"],
  "limit": 30,
  "company_profile": {
    "industry": "소프트웨어사업자",
    "region": "울산광역시",
    "company_size": "중소기업",
    "licenses": [],
    "certs": [],
    "business_fields": ["정보시스템", "소프트웨어"],
    "keywords": ["웹", "챗봇", "AI"],
    "track_records": [{"summary": "공공기관 웹 시스템 개발"}],
    "budget_min": null,
    "budget_max": null
  }
}
```

응답은 201이며 `run_id`, 전체 `items`, `recommendations.bids`, `recommended_bid_ids`를 포함한다. `limit`는 수집할 후보 수(1~100)이고 추천은 최대 20건이다. 최초 요청은 외부 조회·다운로드·필요한 공고문 변환·임베딩을 기다리므로 Vue에 처리 중 상태를 표시한다.

추천은 **가져온 bid_logic의 필터와 순위 로직**을 사용한다. 공고문을 식별하지 못했거나 텍스트 추출에 실패한 공고는 `documents_unavailable`로 분리한다. 정량 채점표가 없으므로 평가 총점·낙찰확률은 제공하지 않는다.

현재 사용자 흐름은 **공고문 PDF → 사업 요약이 있는 추천 목록 → 사용자 1~2건 선택 → 선택 공고 전체 첨부**다. 초기 추천에 점수 평가를 요구하지 않는다. `next_action`은 `user_select_1_or_2_bids`, `selection_requires_evaluation`은 `false`다. 외부 점수 결과를 등록하지 않아도 선택할 수 있다.

| 추천 항목 | 용도 |
|---|---|
| `bid_id`, `bid_no`, `revision` | 사용자 선택에 전달할 식별자. 차수의 선행 0 보존 |
| `title`, `agency`, `deadline`, `budget`, `url` | 목록 표시 |
| `distance` | 공고문 청크와 기업 키워드·실적 요약 간 최소 제곱 L2 거리. 작을수록 유사 |
| `reason`, `unknown`, `needs_review` | 추천 근거 및 확인할 조건 |
| `sources` | 공고번호·차수·PDF 파일명·쪽수·URL·수집일 |
| `restriction_evidence` | PDF에서 읽은 지역·마감 근거 |
| `summary`, `summary_sources` | 목록 카드에 표시할 사업 개요 발췌와 파일·쪽수·원문 인용 |
| `project_summary.overview` | 사업 개요·사업명에 해당하는 원문 발췌와 출처 |
| `project_summary.scope` | 주요 과업·사업 내용의 원문 발췌와 출처 |
| `project_summary.period` | 사업·용역·계약 기간의 원문 발췌와 출처 |
| `summary_method` | `notice_extractive_v1`; 추가 LLM 호출 없이 공고문에서 발췌 |
| `summary_is_notice_preview` | 개요 항목을 찾지 못해 공고문 앞부분을 표시하면 `true` |
| `summary_missing_fields` | 추출하지 못한 개요·과업·기간 항목. 없는 값은 `null`, 출처는 빈 배열 |

화면은 `summary`와 기존 사업예산·마감·기관을 기본으로 표시하고 필요하면 `project_summary`를 펼쳐 보여 준다. `summary_is_notice_preview:true`인 경우에는 “공고문 발췌”로 구분한다. 누락 항목은 “공고문 확인 필요”로 표시하며 임의의 기간·과업을 만들지 않는다. 이미 저장된 추천도 조회 시 사업 요약만 보완하므로 추가 첨부 다운로드나 임베딩은 발생하지 않는다.

공고문에 조건이 없거나 복잡하면 `null`로 전달한다. 현재 업종·면허·기업규모·인증은 자동 확정하지 않으며 `unknown`으로 표시된다. 불일치가 없는 공고를 유사도 순서로 정렬하므로 관련성이 낮은 공고도 뒤쪽에 남을 수 있다. 추천은 최종 참가자격 판정이 아니다.

`GET /bid-runs/{run_id}/recommendations`로 같은 결과를 조회하고, `POST /bid-runs/{run_id}/recommendations`로 현재 자료·시각 기준으로 다시 생성한다. 마감 시각은 평가 실행 시점에 확인하므로 장시간 지난 목록은 재평가 후 표시한다. 기업정보·공고문 버전이 바뀐 경우 이전 추천 조회는 409다.

`search_only:true`는 목록·링크만 저장하며 추천은 생성하지 않는다. 기본 임베딩 호출 실패 시 503의 `detail.run_id`와 `detail.retry_url`을 사용하면 재수집 없이 추천을 재시도할 수 있다.

## 2. 사용자가 공고 1~2건 선택

```http
POST /bid-runs/{run_id}/selection
Content-Type: application/json

{"bid_ids": ["실제공고번호_000", "다른실제공고번호_001"]}
```

선택은 이 탐색 결과의 공고에 대해서만 허용한다. 0개·3개 이상·중복·알 수 없는 ID는 422이며 다운로드하지 않는다. 기존 단건 요청 `{"bid_id":"실제공고번호_000"}`도 지원한다.

응답의 `items[].attachments[]`에 원본 파일명·상태·개별 `download_url`을 제공한다. **HWP/HWPX 신청서·제안요청서·ZIP 등을 원본 그대로** 받으며 이 단계는 변환이나 재적재를 하지 않는다.

`complete:true`면 ZIP `download_url`이 제공된다. `complete:false`면 첨부별 상태를 표시하고 같은 선택 요청을 다시 보내 실패한 파일만 재시도한다. 성공한 파일은 재사용한다. 새 선택 요청은 전달할 ZIP의 공고 목록을 해당 요청의 1~2건으로 갱신한다. 앞서 받은 원본은 보존한다.

## 3. 사용자 파일 다운로드

| API | 응답 |
|---|---|
| `GET /bid-runs/{run_id}/download` | 선택 공고별 폴더의 원본 첨부 + manifest.json ZIP |
| `GET /bid-runs/{run_id}/bids/{bid_id}/attachments/{file_id}` | 선택 공고의 개별 원본 |

ZIP에 내부 변환 PDF·기업 프로필·인덱스를 넣지 않는다. 선택하지 않은 공고의 개별 첨부는 404다. 누락·실패 파일이 있는 ZIP 요청은 409이며 불완전한 묶음을 완전한 결과처럼 내려주지 않는다.

첨부 전체는 **OpenAPI 첨부 URL 1~10 및 별도 표준공고서** 기준이다. 웹 화면에만 있는 파일까지 확보했다고 보장하지 않는다. 파일당 다운로드 제한은 50MB이며 차단·실패 상태가 반환된다.

## Vue 호출 예시

```javascript
import { createBidClient } from './vue_client.js';

const api = createBidClient('http://localhost:8001');
const result = await api.discover(conditions); // 위 요청 JSON
const runId = result.run_id;
const rows = result.recommendations.bids;     // 체크박스 목록

// 사용자가 실제로 체크한 bid_id 1~2개를 전달한다.
const delivery = await api.select(runId, selectedBidIds);
if (delivery.complete) {
  const link = document.createElement('a');
  link.href = api.downloadUrl(delivery.download_url);
  link.click();
}
```

`data_pipeline/vue_client.js`는 Vue 프로젝트로 가져와 사용할 수 있는 ES module이다. 기본 개발 CORS는 `localhost:5173`, `127.0.0.1:5173`이며 다른 주소는 `BID_CORS_ORIGINS`를 쉼표로 구분해 지정한다. API 인증·run_id별 사용자 소유권 검증은 기존 BE 담당 영역이다. 이 API는 BE 뒤에 연결하고, 실제 사용자 화면과 인증은 여기에서 구현하지 않는다.
