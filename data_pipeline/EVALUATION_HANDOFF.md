# 외부 평가 로직 연계 규약

추천은 수정하지 않은 `bid_logic.recommend_bids()`에 연결했습니다. 추천 조회·1~2건 선택·원본 첨부 다운로드는 [현재 API 안내](DELIVERY_API.md)를 사용합니다. 아래 규약은 별도 정량 점수 평가 입력·결과 저장을 위한 기존 계약이며, 정량 평가점수 계산은 추가 구현하지 않았습니다.

## 전체 흐름

```text
API 공고 목록 조회
→ 공고문 한 개만 다운로드·변환·텍스트 추출
→ 사업 개요·과업 범위·기간과 출처가 있는 추천 목록 표시
→ 사용자 공고 1~2건 선택 (점수 평가 불필요)
→ 선택한 공고의 전체 첨부 다운로드
```

공고문에 채점표 등 평가 자료가 없으므로 초기 추천 목록에서 정량 점수를 계산하지 않는다. 아래 점수 입력·결과 계약은 향후 다른 담당자의 기능을 위한 선택적 호환 인터페이스다. 초기 추천·파일 선택의 선행 단계로 사용하지 않는다. 상세 표시 필드는 `DELIVERY_API.md`의 `summary`, `project_summary`를 참고한다.

`preliminary`는 본문 키워드와 API 추정가격에 기반한 예비 분류다. 참가자격을 확정하지 않고 점수를 계산하지 않는다. 추후 더 정교한 적합성 판단은 같은 입력을 사용하는 외부 담당 로직으로 연결할 수 있다.

초기에는 파일명으로 확실히 식별되는 공고문 한 개만 받는다. 공고문 PDF가 있으면 HWP/HWPX보다 우선한다. 제안요청서·과업지시서·서식·ZIP으로 임의 대체하지 않는다. 식별 실패·추출 실패는 검토 필요 상태로 반환한다. 공개 연락처는 보존하고 기존 이름·식별번호 마스킹을 적용한다.

## 입력

탐색 폴더의 `evaluation_inputs.jsonl` 또는 `GET /bid-runs/{run_id}/evaluation-inputs`를 사용한다. 텍스트가 준비된 공고문만 평가 입력으로 제공한다.

| 필드 | 의미 |
|---|---|
| `schema_version` | `bid-evaluation-input.v1` |
| `bid_id` | 공고번호와 차수를 합친 식별자 |
| `evaluation_input_id` | 기업 프로필·공고 메타데이터·공고문 해시/상태에 따른 입력 버전 |
| `company_profile` | 기업 프로필 JSON |
| `company_profile_version` | 기업 프로필 해시 |
| `notice` | API 공고 메타데이터 |
| `notice_document` | 공고문 파일 경로·해시·추출 상태 |
| `notice_pages` | 마스킹된 공고문 페이지 텍스트·쪽수·출처·공개 연락처 |
| `preliminary` | 사전 분류와 일치 키워드의 페이지 근거 |

제안요청서·평가표 등 다른 첨부는 사용자 선택 전 평가 입력에 없다. 초기 점수는 공고문만으로 계산 가능한 범위로 설계해야 한다. 추가 문서가 필요한 평가는 사용자 선택 이후에 확장한다. 문서가 없다는 이유로 데이터를 만들거나 전체 첨부를 자동으로 받지 않는다.

## 미평가 상태

```json
{
  "status": "pending",
  "score": null,
  "max_score": null,
  "result": null
}
```

미평가를 0점으로 처리하지 않는다. 평가 기준·가중치·점수 산식·등급·추천 순위는 외부 담당자가 정의한다.

## 외부 결과 저장

`PUT /bid-runs/{run_id}/bids/{bid_id}/evaluation` 또는 Python 함수 `record_evaluation(run_dir, bid_id, result)`를 호출한다.

아래는 외부 담당자가 계산한 결과를 보관하는 형식 예시이며 점수 계산 구현이 아니다.

```json
{
  "evaluation_input_id": "입력으로 받은 값을 그대로 반환",
  "score": 82,
  "max_score": 100,
  "evaluator_version": "외부 평가기 버전",
  "criteria": [
    {
      "name": "외부 담당자가 정의한 항목",
      "score": 20,
      "max_score": 25,
      "sources": [{"file_name": "입찰공고문.pdf", "page": 2}]
    }
  ]
}
```

보관 시 입력 버전 일치, 유한한 숫자, `0 ≤ score ≤ max_score`, 양수 만점, 평가기 버전 유무만 확인한다. 항목별 계산의 타당성은 외부 담당자 책임이다. 기업 프로필이나 공고문 버전이 바뀌면 이전 결과를 현재 결과로 재사용하지 않는다.

**평가 결과 저장은 첨부 다운로드를 유발하지 않는다.**

## 사용자 선택

```http
POST /bid-runs/{run_id}/selection
Content-Type: application/json

{"bid_id": "R26BK00000000_000"}
```

이 호출 또는 CLI의 명시적 `--select-bid`가 있어야 해당 공고의 전체 첨부를 다운로드한다. 점수가 높다고 자동으로 선택하지 않는다. 평가 로직이 아직 없어도 사용자는 명시적으로 공고를 선택할 수 있다.

`user_selections.json`에 선택 시각과 당시 평가 입력·평가 상태를 남긴다. 이미 받은 공고문과 성공한 파일은 재사용하며 실패한 첨부는 재선택 시 재시도한다. 다운로드는 API가 제공한 첨부 URL 1~10과 별도 표준공고서 URL을 모두 대상으로 하며 파일 확장자로 제한하지 않는다. 웹 화면에만 있고 API가 제공하지 않는 첨부까지 확보했다고 표시하지 않는다.

결과의 `all_attachments_downloaded`와 각 첨부 `status`를 확인한다. 이 값은 API 첨부 목록 기준이다. `attachment_inventory_source`에 목록 출처를 남긴다.

## 데이터 API

| 경로 | 역할 |
|---|---|
| `POST /bid-runs` | API 탐색·공고문 준비·기업 프로필 사전 분류 |
| `GET /bid-runs/{run_id}/bids` | 목록·사전 분류·평가 상태·다운로드 상태 |
| `GET /bid-runs/{run_id}/bids?suitable_only=true` | 공고문 본문 일치 후보만 조회 |
| `GET /bid-runs/{run_id}/evaluation-inputs` | 외부 평가 담당자에게 전달할 입력 |
| `PUT /bid-runs/{run_id}/bids/{bid_id}/evaluation` | 외부 평가 결과 저장; 계산·다운로드 없음 |
| `POST /bid-runs/{run_id}/selection` | 사용자가 선택한 공고의 전체 첨부 다운로드 |

서버의 탐색 경로는 `BID_DISCOVERY_ROOT` 환경변수로 설정한다. 인증·사용자별 프로필 DB·화면은 다른 담당 영역이며 이 데이터 API는 해당 계층에서 호출하도록 연결한다.
