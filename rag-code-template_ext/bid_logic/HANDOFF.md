# 실제 자료를 받기 전 준비한 연결 규격

현재 작업 폴더는 `/Users/jeonghayun/Desktop/AI-Service-Mini-Project/rag-code-template_ext`다.
기능 구현은 `bid_logic`에서 관리하고 기존 RAG 파일에는 연결 함수만 둔다.
이 파일은 전달할 내용을 정리한 저장소 안내이며, 팀원에게 메시지를 전송한 것은 아니다.

## 지금 실행할 수 있는 것

```sh
# 핵심·도구·실행기·평가 입력 검증 (외부 패키지 없이 실행)
python3 -B -m unittest discover -s tests -p test_bid_logic.py
python3 -B -m unittest discover -s tests -p test_agent_tools.py
python3 -B -m unittest discover -s tests -p test_agent_runner.py
python3 -B -m unittest discover -s tests -p test_validation.py

# 실제 LLM 호출 없이 도구 실행 흐름 시연
python3 -B -m bid_logic.agent_demo --output evaluation/offline-agent-demo.json

# 받은 자료를 넣은 후 실제 평가 / 지금은 미완료 안내와 종료 코드 2
python3 -B -m bid_logic.validation --dataset evaluation/real --output evaluation/real-readiness.json
```

빈 작성 틀은 `evaluation/real/`에 이미 생성했다. 추가 세트를 만들 때만
`python3 -B -m bid_logic.validation --init evaluation/새폴더`를 사용한다.
기존 파일이 있는 폴더는 덮어쓰지 않는다.

## 데이터 담당자에게 받을 것

`bids.csv`: 공고 20건. 공고번호와 차수는 문자열이며 선행 0을 보존한다.

| 열 | 형식/의미 |
| --- | --- |
| `bid_no`, `revision` | 공고번호·차수. 결합하여 공고 식별 |
| `title`, `agency` | 공고명·수요기관 |
| `published_at` | `YYYY-MM-DD`. 기간 필터는 공고일 기준 |
| `budget` | 숫자로 된 원 단위 금액. 쉼표·통화 문자 없음 |
| `deadline` | ISO 마감 일시. 권장 `+09:00` 시간대 포함 |
| `regions`, `industries`, `licenses`, `company_sizes`, `certs` | CSV 셀의 JSON 문자열 배열. 제한 없음 `[]`, 미확인 `null` |
| `filename`, `url` | 해당 원문 파일·원문 링크 |

예: 지역 셀의 JSON 값은 `["서울", "울산"]`. CSV에서 따옴표를 이스케이프하는 방식은
기존 `tests/fixtures/bids.synthetic.csv`를 참고한다.

같은 제한 필드는 OR, 서로 다른 필드는 AND다. 복잡한 면허 결합·공동수급 예외를
이 배열로 단순화하여 확정하지 않는다. 그런 조건은 미확인으로 남겨 별도로 검토한다.
지역은 시·도 17개 이름만 쓴다. `서울특별시`와 `서울`은 같은 값으로 처리하지만,
`서울 강남구`·`전국` 같은 표기는 적재 오류다(전국은 `[]`, 시·군·구 제한은 `null`).
업종·면허명은 팀 공통 표기를 써야 한다.
`published_at`·`deadline` 형식이 다르면(`2026/10/15`, 시각 없는 마감 등) CSV 적재가 실패한다.

추가로 받을 것: 공고별 원문 PDF, 누적 적재된 FAISS 인덱스와 청크별
`bid_no`, `revision`, `filename`, `page`, `collected_at` 메타데이터.
기존 업로드의 덮어쓰기·파일명뿐인 메타데이터는 데이터 담당자 작업과 연결해야 한다.

## RAG 담당자에게 받을 것

`scoring_tables.json`: 평가용 공고 5건의 채점표 배열.
각 객체에 `bid_no`, `revision`, `items`가 필요하다.
항목은 `id`, `item`, `kind`(quantitative/qualitative/price), `max`, `basis`, `sources`를 포함한다.
정량 항목에는 `metric`, `rule`도 포함한다. 원문에 없는 규칙을 추정하지 않는다.

```json
{
  "bid_no": "실제 공고번호", "revision": "실제 차수",
  "items": [{
    "bid_no": "실제 공고번호", "revision": "실제 차수",
    "id": "credit", "item": "신용등급", "kind": "quantitative",
    "max": null, "basis": "원문 기준 입력",
    "metric": {"field": "credit_rating"},
    "rule": null,
    "sources": []
  }]
}
```

이 예시는 작성 형식일 뿐이며, null/빈 출처를 채우기 전에는 유효한 채점 기준이 아니다.
구간표·등급표·비례식·실적 집계 상세 계약은 README의 C4 절에 있다.
제출서류/일정은 `checklists.json`에 공고별로 다음 형태로 받는다.

```json
{
  "bid_no": "실제 공고번호", "revision": "실제 차수",
  "documents": [{"id": "서류 식별자", "doc": "원문 서류명",
    "bid_no": "실제 공고번호", "revision": "실제 차수", "due": null, "sources": []}],
  "schedule": [{"id": "일정 식별자", "event": "원문 일정명",
    "bid_no": "실제 공고번호", "revision": "실제 차수", "due": null, "sources": []}]
}
```

날짜가 원문에 없으면 null을 유지한다. 날짜만 있고 시각이 없으면 임의 마감 시각을 만들지 않는다.
출처는 공고·차수·파일명·1부터 시작하는 쪽수를 포함해야 평가에서 원문 검산이 가능하다.

## 백엔드 담당자와 맞출 것

인증된 프로필 의존성이 JWT 서명·만료를 검증하고 sub로 프로필을 조회해야 한다.
이 의존성은 토큰 오류 401, 프로필 없음 404를 처리하고 아래 dict를 반환한다.

- `industry`, `licenses[]`, `region`, `company_size`, `certs[]`
- `credit_rating`, `track_records[]`, `owned_docs[]`
- `budget_min`, `budget_max`(원), `keywords`(문자열 또는 문자열 배열)
- 실적 항목: `completed_at`, `category`, `summary`, `amount`, `amount_unit`

빈 배열은 보유 없음이고 누락/null은 미확인이다. 둘을 구분해야 한다.
현재 API 계약은 `GET /bids?from=&to=`,
`GET /bids/{bid_no}/score?revision=`, `GET /bids/{bid_no}/checklist?revision=`다.
공고 차수 query와 응답 객체 필드를 프론트·백엔드와 합의하고
기존 RAG 파일의 `register_bid_routes()`를 실제 공급자 함수로 한 번 호출한다.
이번 작업에서는 운영 API를 활성화하지 않았다.

## 하윤님이 실제 자료를 받은 후 채울 평가 입력

| 파일 | 작성 내용 |
| --- | --- |
| `manifest.json` | 평가 기간·기준 시각, 임베딩 모델명·인덱스 버전. 실제 검색 결과이면 ranking_input_kind=actual_embeddings |
| `bids.csv` | 선정된 실제 공고 20건 |
| `profiles.json` | 서로 다른 가상 프로필 3개, 각각 고유 id |
| `scoring_tables.json` | 고정 공고 5건의 구조화 채점표 |
| `checklists.json` | 동일 공고 5건의 서류·일정 추출 결과 |
| `hits.json` | `[{profile_id, hits: [{bid_no, revision, distance}]}]`. L2 거리는 작을수록 유사 |
| `gold.json` | 사람이 작성·검산한 추천·점수·서류 정답 |

### 정답의 정확한 형식

`gold.json`의 배열 세 개를 채운다. **코드 출력을 복사하여 정답으로 만들지 않는다.**

1. `recommendations`: 프로필 3개 각각
   `{profile_id, relevant: [{bid_no, revision}], rationale, review}`.
   전체 공고 20건을 보고 관련 공고를 고른다. 상위5 일치율의 분모는 항상 5다.
2. `scores`: 공고 5건 × 프로필 3개 = 15조합 각각
   `{bid_no, revision, profile_id, items: [{id, expected, status, basis, sources}], review}`.
   정량·정성·가격 항목 모두를 기록한다. status는 calculated/manual/missing_profile.
   calculated의 expected는 원문 기준으로 손계산한 점수, 나머지는 `담당자 판단`.
   basis에는 적용 구간, 인정 실적/등급 등 검산 근거를 적는다.
3. `checklists`: 같은 15조합 각각
   `{bid_no, revision, profile_id, documents: [{doc, owned, due, sources}],
   schedule: [{event, due, sources}], review}`.
   owned는 true/false/미확인 null, due는 원문 기한/미확인 null을 명시한다.

모든 정답의 review 초기값은 아래처럼 둔다. 다른 사람이 원문·계산을 확인한 후에만 변경한다.

```json
{"status": "pending", "reviewer": null, "reviewed_at": null}
```

검산 후 status=`verified`, reviewer=실제 검토자, reviewed_at=실제 검토 ISO 일시를 기록한다.
평가기는 이 기록의 존재·형식을 확인할 뿐, 실제 사람의 검산 사실을 자동 입증하지 않는다.
실제 자료·검토 기록이 없으면 평가 상태는 incomplete, 성능 수치는 null이다.

평가 출력에는 전체 항목 정확도와 **정량 항목 정확도를 별도로** 제공한다.
정답 항목 id로 비교하고 점수·판단 상태·출처까지 맞는지 확인한다.
서류 비교는 이름·보유 여부·기한·출처의 누락/추가를 세며 중복도 숨기지 않는다.
종료 코드는 0=평가 실행 및 점수/서류 일치, 1=점수/서류 불일치, 2=자료 미완료/형식 오류.
추천 지표는 보고하며 일률적인 합격 임계값을 임의 설정하지 않는다.

## X2 사전 실행기 계약

`run_scoring_agent(table, profile, bid_no, revision, model=...)`는 이미 읽어 둔
입력을 복사하고, 비동기 모델 어댑터가 선택한 도구를 제한된 횟수만큼 실행한다.
모델의 자유 서술은 점수로 사용하지 않는다. calc_score의 숫자와 mark_manual의 상태만 최종 결과로 쓴다.
동일 항목 덮어쓰기, 잘못된 도구/인자, 공고·차수 혼동을 막고, 도구 오류는 모델에 알려 재시도를 허용한다.

모델 어댑터는 `async def model(messages, tool_specs)`이고 다음 정규화 응답을 반환한다.

```json
{
  "content": "선택적 설명",
  "tool_calls": [{"id": "호출별 고유 ID", "name": "calc_score", "arguments": {"item_id": "credit"}}],
  "usage": {"input_tokens": 123, "output_tokens": 20}
}
```

`arguments`는 dict 또는 JSON 문자열이다. usage는 선택 사항이고 어댑터가 제공한 실측값만 합산한다.
usage 없는 호출이 있으면 complete=false, 전혀 없으면 token_usage=null.
비용은 아직 단가·모델 연결이 없으므로 항상 null이다. 위 숫자는 응답 형식 예시이며 측정 결과가 아니다.
기존 TOOL_SPECS를 사용하며 특정 LLM SDK는 연결하지 않았다.

기본 제한: 모델 최대 8회, 도구 최대 20회, 전체 10초. model은 비동기 취소와 요청 타임아웃을 준수해야 한다.
동기 네트워크 호출을 이 어댑터 안에 넣으면 안 된다. 외부 데이터 읽기는 실행 전에 끝내야 한다.
취소를 무시하는 외부 SDK나 동기 CPU 실행을 강제로 중단하는 프로세스 격리 기능은 제공하지 않는다.
한계 상태(timeout/max_rounds/max_tool_calls/incomplete/model_error 등)는 완료 상태와 구분된다.
필수 프로필이 부족하면 needs_input과 추가 질문을 반환한다.

핵심 E2E 이후에 할 일: 실제 모델 어댑터, JWT가 적용된 `/agent/score`, 모델·단가·토큰 로그,
같은 검토 완료 정답에 대한 C4와 X2의 정확도·요청 전체 시간·원가 비교.
현재 가짜 모델 데모와 그 실행 시간은 실제 에이전트 성능/비용 비교 결과가 아니다.
