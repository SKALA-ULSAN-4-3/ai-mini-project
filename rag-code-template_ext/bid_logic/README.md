# 공고 추리기·예상 점수·체크리스트 (정하윤)

## 현재 상태

C2·C4·C5의 독립 Python 로직, CSV/FAISS 어댑터, 인증 의존성을 필수로 받는
FastAPI 라우터 팩토리와 합성 fixture 평가를 추가했다. Python 표준 라이브러리만으로
핵심 로직을 테스트할 수 있다. API 모듈은 기존 requirements-e.txt의 FastAPI/Pydantic을 사용한다.

담당 기능의 구현은 이 폴더의 기능별 Python 파일에서 관리한다.
기존 RAG 진입 파일에는 import와 `register_bid_routes()` 등록 함수만 추가했다.
공통 처리·추천·채점·체크리스트·API 로직을 원본 파일에 중복으로 넣지 않는다.
업로드·질의 API, Java 인증, 회원 DB, 화면, 음성 코드의 동작은 유지한다.
인증된 프로필 의존성이 연결될 때 라우터를 등록한다. 실시간 흐름에서는 저장된 검색 결과 공급자도
연결해야 한다. 실제 공고 20건과 평가 입력은 준비했으며, 정답은 AI 원문 검산 초안으로 사람 검토 대기다.
이 패키지 import만으로 API가 노출되거나 외부 API/DB/LLM이 초기화되지 않는다.

X2에 실제 OpenAI 비동기 어댑터와 선택 등록되는 인증 의존성 적용 `/agent/score`를 추가했다.
실제 GPT-4o로 5공고 × 3프로필의 고정 코드 대비 실측을 완료했다. 운영 JWT·화면 E2E와
사람 정답 검토 완료는 별도다. [실제 평가 보고서](../evaluation/real/REPORT.md),
[원문 검산 초안](../evaluation/real/REVIEW.md), [팀원 연결 규격](HANDOFF.md)을 참고한다.

## 파일과 책임

| 파일 | 역할 |
| --- | --- |
| `common.py` | 공고·차수, 출처 범위 검증, 서울 시각, Decimal 숫자 처리 |
| `recommendation.py` | C2 규칙 필터·청크 집계·순위, CSV와 기존 FAISS 어댑터 (③' 재확인) |
| `shortlist.py` | ② 목록 기반 추리기와 ③' 재확인 래퍼. 공고문 적재 전 단계 |
| `title_similarity.py` | 같은 모델의 공고명·프로필 질의를 코사인 유사도로 비교 |
| `scoring.py` | C4 구간표·등급표·명시적 비례식 계산, 실적 집계 |
| `checklist.py` | C5 보유 서류 표시·일정·D-day |
| `api.py` | 인증된 프로필 및 데이터 공급 함수를 주입하는 라우터 |
| `agent_tools.py` | X2 도구 4개와 호출 기록. 점수는 `scoring.py`에 위임 |
| `agent_runner.py` | 주입한 비동기 모델의 도구 실행 반복·제한·오류 처리 |
| `agent_model.py` | 실제 OpenAI SDK 어댑터·토큰 비용 계산 |
| `prepare_real.py`, `extract_pdf.swift` | 고정 공고 메타데이터·원문·가상 프로필·출처 준비 |
| `curate_real.py` | 코드 출력과 별도로 작성한 원문 기준 정답 초안 |
| `real_measurements.py` | 실제 임베딩·독립 추출 실험·X2 비교 측정 |
| `review_real.py`, `smoke_real.py` | 검토 보고서 생성·실제 입력의 라우터 점검 |
| `agent_demo.py` | 가짜 모델과 합성 데이터만으로 실행하는 시연 |
| `evaluate.py` | 합성 정답 초안과 추천·점수·체크리스트 비교 |
| `validation.py` | 실제 자료 작성 틀 생성·누락 검증·정답과 코드 결과 비교 |
| `HANDOFF.md` | 팀원별 데이터 계약, 평가 입력·모델 어댑터 형식 |
| `../evaluation/real/` | 실제 고정 20건 입력·정답 초안·실측·검토 보고서 |
| `../tests/` | 독립 로직 및 테스트 앱 API 검증, 합성 입력·정답 |
| `../evaluation/synthetic-report.json` | 실제 실행한 합성 평가 결과 |

## 실행과 검증

`rag-code-template_ext` 디렉터리에서 실행한다.

```sh
# 외부 패키지·키·DB 없이 핵심 로직 + ② 목록 추리기
python3 -B -m unittest discover -s tests -p test_bid_logic.py -v
python3 -B -m unittest discover -s tests -p test_shortlist.py -v

# 기존 FastAPI/Pydantic 및 httpx가 설치된 Python으로 API 포함 전체 검증
python3 -m unittest discover -s tests -v

# 합성 평가 보고서 생성. 실패하면 종료 코드 1
python3 -m bid_logic.evaluate --output evaluation/synthetic-report.json

# 가짜 모델 시연. 실제 LLM 성능 비교가 아님
python3 -B -m bid_logic.agent_demo --output evaluation/offline-agent-demo.json

# 공식 검증: 사람 검토 및 HWPX PDF 쪽수 대조가 남아 종료 코드 2
python3 -B -m bid_logic.validation --dataset evaluation/real --output evaluation/real-readiness.json

# AI 정답 초안과의 잠정 비교. human_verified=false를 유지한다.
python3 -B -m bid_logic.validation --dataset evaluation/real --draft --output evaluation/real/draft-report.json

# 실제 데이터·캐시된 실제 벡터로 API 점검 (테스트 앱 전용 인증)
python3 -B -m bid_logic.smoke_real

# 네트워크·OpenAI 키 필요. 모델 호출 비용 발생. 기존 결과는 evaluation/real에 있음.
python3 -B -m bid_logic.real_measurements embed
python3 -B -m bid_logic.real_measurements extract
python3 -B -m bid_logic.real_measurements compare
python3 -B -m bid_logic.review_real
```

2026-10-23 수정 후 Python 3.11 임시 API 검증 환경에서 **167개 중 158개 통과,
RAG 연동 9개는 FAISS/LangChain 미설치로 skip**했다. ②에서 본문 검색을 하지 않는지,
기본 20건, 저장된 검색 결과와 인증 전달, ③' 적재 대상·부적격 표시,
시간대·초 보존, 순위 잘림 회귀, 409 전달과 여러 건 체크리스트를 포함한다.
프로젝트 requirements와 기존 가상환경은 변경하지 않았다.

API 테스트의 `Bearer fixture-only`는 테스트 앱 전용 가짜 인증이다.
실제 JWT 서명·만료·사용자 DB 연동을 검증한 결과가 아니다.
기존 전체 RAG 서버 기동, 실제 FAISS 인덱스 실행 및 화면 E2E는 미검증이다.
평가에서는 실제 임베딩의 제곱 L2 완전탐색을 사용하고, PDFKit으로 PDF 253페이지를 읽었다.
별도로 실제 입력을 넣은 테스트 앱에서 목록·재확인·점수·체크리스트 37/37 점검을 통과했다.
실제 나라장터 수집은 별도 임시 경로에서 고정 20건·첨부 74개 다운로드까지 확인했다.
전체 HWP 변환은 환경 미설정으로 중단됐으며, 이번 평가는 확보된 PDF와 HWPX XML 원문을 사용했다.
[검증 기록](VERIFICATION.md)을 참고한다.

## 공통 입력 계약

- `bid_no`, `revision`은 공백 없는 문자열. `"00"` 같은 선행 0을 보존한다.
- 정정공고는 `(bid_no, revision)` 쌍으로 구분한다. 최신 차수를 임의 선택하지 않는다.
- 날짜는 `YYYY-MM-DD`, 마감은 `2026-10-23T18:00:00+09:00` 같은 ISO 일시.
  시간대가 없는 일시는 서울 시각으로 해석한다. 날짜만 있는 마감은 미확인 처리한다.
- `sources` 배열의 각 출처에도 같은 `bid_no`, `revision`이 필요하다.
  `filename`, `page`, `collected_at`, `url` 등 실제 존재하는 메타데이터를 그대로 전달한다.
  다른 공고·차수의 출처가 섞이면 거부한다. 없는 쪽수·수집일을 만들어 넣지 않는다.
- 운영 공통 Pydantic 스키마가 만들어지면 이 dict 계약을 변환하는 얇은 어댑터를 둔다.
  현재 API의 응답 모델은 최상위 필드를 검증하며, 내부 항목 계약은 아래와 테스트 예시에 정의한다.

회사 프로필 필드:

```json
{
  "industry": "SW", "licenses": ["SW"], "region": "서울",
  "company_size": "중소기업", "certs": ["벤처"], "credit_rating": "AA",
  "track_records": [
    {"completed_at": "2026-01-01", "category": "SW", "summary": "웹 구축",
     "amount": 1, "amount_unit": "억원"}
  ],
  "owned_docs": ["사업자등록증"],
  "budget_min": 100000000, "budget_max": 500000000, "keywords": ["웹", "앱"]
}
```

금액 비교는 원(KRW) 단위다. 숫자에 쉼표/통화 문자를 포함하지 않는다.
프로필 누락/null은 미확인, `licenses: []`, `track_records: []`, `owned_docs: []`는
각각 보유 면허·실적·서류가 없음을 명시한 값이다.

## C2 — 데이터 담당자 연결

필수 CSV 열은 `bid_no,revision,title,agency,published_at,budget,deadline`이다.
제한 열은 `regions,industries,licenses,company_sizes,certs`이고 CSV 셀에 JSON 배열을 넣는다.
예시는 `../tests/fixtures/bids.synthetic.csv`에 있다.

- `[]`: 제한 없음이 원문에서 확인됨. `null` 또는 빈 셀: 제한 여부 미확인.
- 같은 필드의 값은 OR, 서로 다른 필드는 AND다. 값은 코드·명칭을 사전 정규화하여 정확히 비교한다.
- 복잡한 공동수급/면허 AND·OR 예외나 지역명 계층을 자연어로 해석하지 않는다.
  단순 배열로 확정할 수 없는 조건은 null로 전달하고 사람 검토로 남긴다.
- 지역은 시·도 17개만 받는다. 정식·옛 명칭(`서울특별시`, `전라북도`)은 약칭(`서울`, `전북`)으로
  맞추고, 목록에 없는 표기(`서울 강남구`, `전국`)는 CSV에서는 적재 오류, 프로필에서는 422다.
  시·군·구 단위 제한은 null(미확인)로 전달한다. 업종·면허·인증명은 여전히 팀 공통 표기가 필요하다.
- `published_at`·`deadline`은 빈 칸(미확인)이거나 정해진 형식이어야 한다. `2026/10/15`나
  시각 없는 마감처럼 형식이 다르면 공고가 조용히 빠지지 않도록 CSV 적재 단계에서 실패한다.
- 마감과 금액은 경계를 포함하여 비교한다. `deadline <= now`이면 마감.
- 음수 공고 금액은 CSV 적재와 추천 양쪽에서 거부한다. 금액 필터를 건너뛴 채 추천하지 않는다.
  금액 셀이 비었거나 숫자로 읽을 수 없는 경우만 `금액 비교 정보 미확인`으로 남긴다.
  공고일은 시작·종료일을 모두 포함한다. 공고일 미확인은 결과에 섞지 않고
  `excluded`의 `status: unknown`으로 분리한다.
- 명백한 불일치는 `excluded`에 사유와 함께 반환한다. 나머지 미확인 조건은 각 후보의 `unknown`에 남긴다.
  명시적 제한이 없으면 관련 프로필 필드가 없어도 제외하지 않는다.

```python
from bid_logic import load_bids_csv, recommend_bids, faiss_hits

result = recommend_bids(
    load_bids_csv("data/bids.csv"), profile, "2026-10-01", "2026-10-31",
    search=lambda query, keys: faiss_hits(VECTORSTORE_PDF, query, keys),
)
```

핵심 함수에 `now`를 주입할 수 있다. `hits`를 직접 전달하면 임베딩 호출도 필요 없다.
query는 관심 키워드와 실적 요약을 합친 문자열이다.
`hits`는 `[{bid_no, revision, distance}]`이며 **작을수록 유사한 비음수 L2 거리**만 받는다.
코사인 유사도처럼 클수록 좋은 값을 그대로 넣으면 안 된다.

공고별 최소 청크 거리로 집계하고 거리 오름차순, 동점이면 공고번호·차수 문자열 오름차순으로 정렬한다.
임베딩 정보가 없는 후보는 마지막에 두고 `유사도 미확인`을 표시한다. 관련성이 높다고 주장하지 않는다.
추천 결과에는 항상 `needs_review: true`가 있다.

기존 FAISS 어댑터는 전체 청크 수를 k로 조회한 후 허용 공고를 고른다.
필터에 걸린 공고의 청크가 상위 k를 차지해 후보가 누락되는 것을 막기 위한 20건 규모 구현이다.
`index`는 L2 거리 인덱스여야 한다. 실제 FAISS 동작은 담당자 통합 검증이 필요하다.
생성형 LLM 호출은 없지만 OpenAIEmbeddings의 query 임베딩 호출은 발생할 수 있다.
임베딩 토큰/원가는 백엔드 계측에 별도 항목으로 연결해야 한다. 이 모듈은 비용을 추정하지 않는다.

**적재 관련 선행 조건:** 기존 `/upload-paper`는 저장소를 교체하고 파일명 중심 메타데이터를 만든다.
데이터 담당자가 누적 적재, 공고·차수·쪽수·수집일 메타데이터와 CSV 대응 관계를 제공해야 한다.
파일명뿐인 기존 인덱스를 새 공고 인덱스인 것처럼 사용하지 않는다.

## ② 목록 기반 추리기 — 공고문 적재 전

확정 흐름의 ② 시점에는 아직 공고문이 없어 본문 거리를 쓰는 `recommend_bids`를 쓸 수 없다.
1번 `/search-bids` 결과를 그대로 받아 목록 정보만으로 거르는 `shortlist_bids`를 따로 둔다.

```python
from bid_logic import shortlist_bids

result = shortlist_bids(search_results, profile, limit=20)
```

- 제외 규칙은 **마감 지남 · 희망 금액 범위 밖 · 지역 제한 불일치** 셋뿐이다.
- 업종 제한(`indstrytyLmtYn = Y`)은 **제외하지 않는다.** 목록에 대상 업종이 없어 맞는지 알 수 없으므로
  `업종 제한 있음, 대상 업종 미확인`으로 남긴다.
- `rgnLmtBidLocplcJdgmBssNm`는 제한이 있다는 신호일 뿐 지역명이 아니다. 지역명은
  `jntcontrctDutyRgnNm1~3`에서만 읽고, 신호만 있고 지역을 모르면 미확인으로 둔다.
- 정규화 이름(`bid_no`, `title`, `deadline`)과 API 원문 이름(`bidNtceNo`, `bidNtceNm`, `bidClseDt`)을
  모두 받는다. 금액은 `asignBdgtAmt` → `presmptPrce` 순으로 본다.
- 시각 없는 마감은 임의 시각을 만들지 않고 미확인이다.

순위는 공고명과 프로필 키워드의 유사도다. `similarity(query, titles)`를 주입하면 그것을 쓰고,
없으면 글자 2-gram Jaccard로 대체한다. **`recommend_bids`의 `hits`와 방향이 반대다** —
여기서는 클수록 유사한 점수를 받는다. 응답의 `ranking_kind`가 `injected`/`lexical`/`none`을 구분한다.

```python
from knowledge_bridge import PipelineEmbeddings   # 1번 저장소와 같은 모델·정규화

embeddings = PipelineEmbeddings(model)
def similarity(query, titles):
    q = embeddings.embed_query(query)
    return [sum(a * b for a, b in zip(q, v)) for v in embeddings.embed_documents(titles)]
```

어휘 점수만으로는 `시스템`이 `설치류 수면 시 글림프시스템 연구용역`에 걸리는 오매칭을 막지 못한다.
운영에서는 임베딩을 주입해야 하고, `ranking_kind: "lexical"`은 순위 근거가 약하다는 표시다.

`connect_bid_routes`는 `PipelineEmbeddings`와 `embedding_title_similarity`를 자동으로 연결한다.
적재 저장소의 모델이 있으면 해당 모델, 없으면 `KnowledgeStore`의 설정 모델을 사용한다.
②는 본문 인덱스가 없어도 실행되며, 임베딩 실패를 어휘 순위로 조용히 대체하지 않는다.
공고 마감의 초·소수초·시간대를 보존한다. 선택 기간은 공고일 기준 양 끝을 포함한다.

### ③' 공고문 적재 후 재확인

```python
from bid_logic import recheck_after_ingest

reviewed = recheck_after_ingest(result["bids"], load_bids_csv(path), profile, start, end,
                                search=lambda q, keys: faiss_hits(VECTORSTORE_PDF, q, keys))
```

기존 `recommend_bids`를 그대로 다시 돌려 공고마다 `recheck`를 붙인다.
`confirmed`(여전히 적격) · `disqualified`(본문·CSV에서 드러난 부적격) ·
`unknown`(공고일 미확인 등) · `not_evaluated`(아직 적재 안 됨)로 구분한다.
②에서 고른 건수를 모두 평가하도록 `limit` 기본값을 자동으로 맞춘다.

재확인 대상 공고·차수만 평가하며 외부 `limit`으로 잘리지 않는다.
`confirmed`도 최종 참가자격 확정이 아니며 `needs_review`와 `recheck.unknown`을 확인해야 한다.

### 화면·백엔드 연결 계약 (확정 흐름)

```python
connect_bid_routes(
    get_authenticated_profile,
    search_results_provider=get_saved_search_results,
    # bids_provider=get_notice_metadata,  # 생략 시 변환된 data/bids.csv
)
```

`get_saved_search_results(search_id, profile)`는 동기 함수다. ①에서 저장한 검색 결과를
공고 배열 또는 `{bids: [...]}` / `{items: [...]}` / `{results: [...]}`로 반환한다.
인증된 프로필을 사용해 검색 소유권·접근을 검증하고, 미존재면 None/404,
접근 거절이면 HTTPException(403)을 반환한다. 새 검색을 실행하지 않는다.
검색 결과에는 첨부 링크와 차수·제한 필드를 유지한다. 공급자는 API 담당자와 연결해야 한다.

- ②: `GET /bids?from=2026-10-01&to=2026-10-31&search_id=검색ID`
  — 기본 20건, `stage: list_only`, `ranking_kind`, `search_id`, 첨부 링크 유지.
  검색 공급자가 있으면 search_id 필수(422). 공급자 없이 search_id를 보내면 503.
  search_id 없는 CSV 방식은 고정 평가·개발용 호환 경로다.
- ③': 공고문 적재 작업이 끝난 후 `POST /bids/recheck`.
  요청은 `{"from":"2026-10-01","to":"2026-10-31","bids":[{"bid_no":"공고번호","revision":"000"}]}`.
  최대 20건이며 클라이언트는 자격 조건·프로필을 전달하지 않는다.
  서버의 정규화 메타데이터와 본문 검색을 사용한다. `connect_bid_routes`는 현재 적재된
  공고·차수만 평가해 아직 적재되지 않은 공고는 `not_evaluated`로 남긴다.
  부적격도 배열에서 삭제하지 않아 ④의 20건 요약 흐름에 표시할 수 있다.
- ⑦·⑨: 기존 `GET /bids/{bid_no}/score?revision=000`,
  `GET /bids/{bid_no}/checklist?revision=000`을 공고별 호출한다. 제안요청서 미적재 409 유지.

① `/search-bids`, ③·⑥ 적재 작업 API, 사용자별 선택·승인 저장, JWT와 화면 폴링은
각 담당자의 연결이 필요하다. 이 패키지가 대체 구현하거나 로그인 없이 활성화하지 않는다.

## C4 — RAG 담당자 연결

`calculate_scores(table, profile, bid_no, revision)`에 구조화 추출 결과를 전달한다.
각 항목은 공고별 원문 기준을 포함한다. 예시의 규칙은 **합성 기준**이다.

```json
{
  "bid_no": "SYN-01", "revision": "00",
  "items": [{
    "bid_no": "SYN-01", "revision": "00", "id": "credit",
    "item": "신용등급", "kind": "quantitative", "max": 10,
    "basis": "[가상] AA 10점, BBB 6점, B 2점",
    "metric": {"field": "credit_rating"},
    "rule": {"type": "category", "values": {"AA": 10, "BBB": 6, "B": 2}},
    "sources": [{"bid_no": "SYN-01", "revision": "00", "filename": "SYNTHETIC.txt", "page": 1}]
  }]
}
```

지원하는 규칙:

- `category`: 등급명 → 점수 정확 매핑. 신용등급 순서를 임의로 추정하지 않는다.
- `bands`: `[{min, max, min_inclusive, max_inclusive, score}]`.
  하한 포함·상한 제외가 기본값이고 경계 포함 여부는 원문대로 명시할 수 있다.
  경계 누락은 무한 구간. 겹침·잘못된 범위·매칭 구간 없음은 수동 검토로 돌린다.
- `ratio`: `denominator`, `multiplier`, 선택적 `cap`으로 비례식을 표현한다.
  원문이 그 비례식을 명시한 경우만 전달한다. 임의 문자열 수식/eval은 지원하지 않는다.
- 반올림은 `rule.rounding: {places: 2, mode: "half_up"}`처럼 명시한다.
  `down`, `half_even`도 지원한다. 없으면 별도 반올림하지 않는다. 내부 연산은 Decimal이다.
  `cap`이 없으면 임의로 상한 보정하지 않으며, 배점 밖의 결과는 수동 검토한다.

실적 집계 `metric`:

```json
{"field": "track_records", "aggregate": "sum", "unit": "KRW",
 "from": "2024-01-01", "to": "2026-10-23", "categories": ["SW"]}
```

`aggregate`는 `count`/`sum`. 인정 기간은 RAG 담당자가 원문에서 확정한 절대 날짜로 주며
양쪽 경계를 포함한다. `categories` 생략은 전체 분야, 빈 배열은 인정 분야 없음이다.
지원 단위는 `KRW`, `천원`, `백만원`, `억원`. 인정 실적의 금액·단위·일자가 빠지면
부분 합산 점수를 반환하지 않고 필요한 필드를 질문한다.
일반 숫자 지표는 `metric: {field: "employee_count"}`처럼 확정된 동일 단위 값만 받는다.
금액형 일반 지표는 `metric: {field: "revenue", unit: "KRW"}`와
프로필 `revenue: {value: 150, unit: "백만원"}` 형태로 변환한다.
증빙의 인정 여부, 원문 해석의 타당성, 공고별 복잡한 실적 인정 규정은 사람이 확인해야 한다.
현재 지원하지 않는 규칙을 억지로 단순 규칙으로 변환하면 안 된다.

출력 예시:

```json
{
  "bid_no": "SYN-01", "revision": "00", "needs_review": true,
  "items": [{
    "id": "credit", "item": "신용등급", "max": 10, "expected": 10,
    "status": "calculated", "needs_review": true,
    "basis": "[가상] AA 10점, BBB 6점, B 2점", "used_profile": {"credit_rating": "AA"},
    "rule": {"type": "category", "values": {"AA": 10, "BBB": 6, "B": 2}},
    "sources": [{"bid_no": "SYN-01", "revision": "00", "filename": "SYNTHETIC.txt", "page": 1}],
    "missing_fields": [], "reason": "원문 기준에 따라 코드로 계산한 예상 점수"
  }],
  "missing_fields": [], "questions": []
}
```

총점 필드는 없다. `qualitative`·`price` 항목은 `expected: "담당자 판단"`, `status: "manual"`.
프로필 부족은 `missing_profile`과 질문으로 구분하며 0점을 부여하지 않는다.
채점 기준·출처·지원 규칙 부족도 `manual`로 반환한다.

## C5 — RAG·프론트엔드 연결

입력은 `{bid_no, revision, documents: [...], schedule: [...]}`.
모든 서류/일정에 `id, bid_no, revision, sources`가 필요하다.
서류에는 `doc`, 일정에는 `event`, 각각 선택적 `due`, `notes`를 둔다.
구체적인 전체 입력 예시는 `evaluate.extracted_checklist()`를 참조한다.

`build_checklist(extracted, profile, bid_no, revision, now=...)`의 출력은 다음과 같다.

- 서류: `doc, owned, submitted, due, d_day, remaining_seconds, status, sources, notes, needs_review`.
- 일정: `event, due, d_day, remaining_seconds, status, sources, notes, needs_review`.
- 보유 문서는 Unicode NFKC와 공백 제거 후 정확 일치한다. '사본', 연도, 괄호 등은 제거하지 않는다.
  필요하면 사람이 확인한 `aliases={별칭: 정식명}`을 양쪽에 한 번 적용한다.
- `owned: true`는 보유 표시이고 제출 완료가 아니다. `submitted` 초기값은 false다.
  제출 상태 저장·변경 API는 이번 담당 범위에 포함하지 않았다.
- owned_docs 미등록이면 `owned: null`, 검토 필요. 서류 유효기간·발급기관 검증은 별도 담당자 확인이다.
- D-day는 서울 달력 날짜 차이. 당일은 0이고, 시간 경과는 `status`로 구분한다.
  마감 순간부터 expired, 남은 초는 0. 기한 누락 unknown, 날짜만 있거나 해석 불가하면 needs_review.
  마감 시간을 보충하지 않는다. 출처가 없거나 다른 공고·차수이면 입력을 거부한다.

## 백엔드 연결 위치

원래 RAG 파일은 `bid_logic`에서 CSV·검색 어댑터와 라우터 팩토리를 불러온다.
`register_bid_routes()`가 기능별 모듈의 구현을 기존 app에 등록한다.
아래 예시는 해당 RAG 파일에서 app 생성 이후, 서버 실행 이전에 호출할 코드다.
표시한 공급 함수는 팀 백엔드/RAG 담당자의 실제 구현으로 연결해야 한다.

```python
register_bid_routes(
    profile_dependency=get_authenticated_profile,
    scoring_provider=get_extracted_scoring_table,
    checklist_provider=get_extracted_checklist,
)
```

기본 CSV는 `BASE_DIR / "data" / "bids.csv"`이고 기본 검색은 현재 `VECTORSTORE_PDF`를 사용한다.
저장소는 요청 시 조회하므로 업로드 이후 교체된 인덱스도 반영된다.
필요하면 bids_provider/search/clock을 명시적으로 주입할 수 있다.
동일 경로에 연결 함수를 다시 호출하면 중복 등록을 거부한다.
원본 파일 검증은 해당 파일의 실제 모듈 import와 등록 함수를 읽어 테스트 앱에서 실행했으며,
전체 RAG 서버의 LLM·DB 초기화까지 검증한 것은 아니다.

계약:

1. `get_authenticated_profile`: FastAPI Depends용 sync/async 함수.
   Bearer JWT의 서명·만료 검증 후 sub로 프로필을 조회하여 dict 반환.
   잘못된 토큰/만료는 401, 프로필 없음은 404. 요청에서 임의 사용자 ID를 받지 않는다.
2. `get_extracted_scoring_table(bid_no, revision)` / `get_extracted_checklist(...)`:
   동기 데이터 공급자. 정확한 공고·차수의 추출 결과를 반환, 없으면 None.
3. 요청·프로필 값 오류(기간 역전, 희망 금액, 지역 표기, owned_docs 형식)만 422.
   CSV 형식, 벡터 인덱스 메타데이터, 공급자가 준 공고·차수 불일치 등 데이터 문제는 503이며
   응답에는 원문 메시지를 넣지 않고 서버 로그에만 남긴다. 추출 데이터 없음은 404.
   백엔드 담당자의 중앙 오류 처리·관측 체계가 준비되면 맞춰 연결한다.
4. 생성되는 경로:
   - `GET /bids?from=2026-10-01&to=2026-10-31&limit=5`
   - `GET /bids/{bid_no}/score?revision=00`
   - `GET /bids/{bid_no}/checklist?revision=00`
   - `POST /bids/recheck`
5. `revision`은 차수 혼동을 막기 위해 추가한 필수 query다. 프론트와 API 담당자가 합의해야 한다.
   추천 목록은 기획서 개략 배열에 더해 `{bids, excluded, candidate_count, needs_review}`로 감쌌다.
   기존에 동일 경로가 구현되면 중복 등록하지 말고 해당 핸들러에서 핵심 함수를 호출한다.

기획서는 Java `POST /login`을 표기하지만 실제 코드는 `/api/login`을 사용하며,
기존 `/rag-query`도 기획서와 달리 prompt/response 계약이다. 이번 변경에서는 수정하지 않았다.

## X2 — 채점 에이전트 (오프라인 사전 준비)

기획서의 도구 4개를 `ScoringTools`로 묶었다. **점수를 만드는 주체는 여전히
`calculate_scores`**이고, 에이전트는 항목마다 계산할지 사람에게 넘길지 고르기만 한다.
같은 함수를 쓰므로 X2와 C4 고정 경로의 점수가 갈라지지 않는다.

```python
from bid_logic import ScoringTools, TOOL_SPECS

tools = ScoringTools(
    scoring_provider=get_extracted_scoring_table,   # C4와 같은 공급자
    profile_provider=get_authenticated_profile,
    bid_no="20251000123", revision="00",
)
tools.dispatch("calc_score", {"item_id": "credit"})   # LLM이 고른 도구 실행
```

`TOOL_SPECS`는 OpenAI function calling 형식이다. 기존 `langchain-openai` 스택에 맞췄다.

안전 장치:

- 도구는 생성 시점의 **한 공고·차수에 고정**된다. 에이전트가 다른 공고를 조회할 수 없다.
- 공급자가 잘못된 채점표를 반환해도 표·항목·출처의 공고·차수를 확인한 후 거부한다.
- 도구는 `item_id`만 받는다. 채점 규칙·배점을 인자로 받지 않으므로
  에이전트가 기준을 지어내 점수를 만들 수 없다.
- `get_scoring_table`은 판단에 필요한 `id, item, kind, max, basis, sources`만 보여 준다.
  실행용 `rule`·`metric`은 숨긴다. 에이전트는 **라우팅**, 코드는 **계산**을 맡는다.
- 모르는 도구 이름과 명세 밖 인자는 `dispatch`가 거부한다.
- 채점표와 프로필은 인스턴스당 한 번만 읽고 복사한다. 반환값 변경도 내부 입력에 영향을 주지 않는다.
- 호출 기록은 `tools.calls`에 남는다. 기획서의 `tool_calls[]`와 X2 비교에 쓴다.
- 프로필 부족은 `calc_score`가 `missing_profile`과 `questions`로 돌려준다.
  에이전트의 되묻기는 이 값을 쓰고, 0점을 부여하지 않는다.

`agent_runner.py`는 비동기 모델 어댑터를 받아 도구 실행을 반복한다.
모델 8회·도구 20회·전체 10초가 기본 제한이며, 잘못된 인자는 오류로 돌려 재시도를 허용한다.
모델 서술에서 점수를 읽지 않고 도구 결과만 사용한다. 미처리 항목과 부족 정보 질문을 반환한다.
데이터는 실행 전에 읽어 두어야 하고, 모델 어댑터는 비동기 취소를 준수해야 한다.
가짜 모델 실행 기록은 `evaluation/offline-agent-demo.json`에 별도 표시했다.

`agent_model.OpenAIChatModel(client, model="gpt-4o")`를 `connect_bid_routes(..., agent_model=...)`에
주입하면 `POST /agent/score`가 등록된다. JSON은 `{bid_no, revision}`이고 프로필은 인증 의존성에서만 받는다.
모델 미주입 시 경로는 노출되지 않는다. 제안요청서 미적재 409를 그대로 전달한다.
실제 비교는 `evaluation/real/x2-measurements.json`에 있다. AI 정답 초안 기준이므로
공식 검토 완료 결과와 구분한다. 기존 합성 보고서의 미실행 X2 값은 그대로 null이다.

## 평가와 남은 작업

현재 합성 거리와 독립 정답 초안 기준:

- 추천 관련 공고: 프로필별 3건/3건/2건 전부 반환, 오추천 없음.
  Precision@5는 분모를 항상 5로 두어 0.6/0.6/0.4.
  반환 수가 5 미만임을 숨기지 않도록 반환 건수 기준 precision과 정답 recall도 함께 제공한다.
  결과가 0건이면 precision_returned는 0, 정답이 없으면 recall은 null이다.
- 점수: 5개 가상 공고 × 3개 프로필 = 15조합, 정량 항목 30/30 일치.
- 체크리스트: 합성 원문 대비 서류·일정 누락/추가 0.
- `synthetic_cases.json`에 사람이 검산할 수 있는 근거와 정답 초안을 고정했다.
  계산 함수 결과에서 정답을 생성하지 않는다. `human_verified: false`.
- 보고서 지연은 추출·검색·인증을 제외한 고정 채점 함수 실행 시간만 측정한다.
  실제 서비스 지연, 모델 성능, 토큰 비용이나 실제 공고 정확도의 증거가 아니다.

남은 통합 순서:

1. 데이터 담당자가 CSV와 누적 인덱스, RAG 담당자가 실제 채점표·서류·일정 추출 결과를 제공한다.
2. 백엔드 담당자의 인증된 프로필 조회와 연결하고 실제 공고·차수로 Swagger 검증한다.
3. 프론트에서 기간→추천→점수→체크리스트 E2E를 확인한다.
4. 실제 공고 5건 × 프로필 3개를 원문 기준으로 사람이 검산하고 정답 검토 상태를 기록한다.
   팀 전체 Q&A 평가셋 20쌍과 체크리스트 원문 검증에도 필요한 사례를 제공한다.
5. X2 실제 어댑터·엔드포인트 코드는 준비됐으며, 핵심 화면 E2E 후 운영 JWT·로그와 함께 검증한다.
6. X2 비교는 같은 입력·같은 원문 정답·모델/버전·호출 조건으로 측정한다.
   C4 함수만의 지연과 에이전트 전체 지연을 혼동하지 않도록 측정 범위를 기록하고,
   공통 추출 비용/캐시 유무를 양쪽에 동일 적용한다. 입력·출력 토큰, 임베딩 토큰,
   측정일의 단가·통화, 요청별 비용·정확도를 남긴다. 미실행 값은 null로 둔다.

실제 평가와 X2 선행 실측은 완료했다. 정답 사람 검토·HWPX PDF 쪽수 대조·운영 연결은 대기 상태다.
재생 기준 시각, 정답 초안의 한계, 독립 서류 추출의 누락·출처 문제는 실제 평가 보고서에 기록했다.
