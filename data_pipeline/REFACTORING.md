# 데이터 파이프라인 코드 구조와 리팩터링 검증

작업일: 2026-10-23. 변경 범위는 `data_pipeline/` 내부 코드·기존 테스트·문서다. 기능·평가 산식·API 계약을 추가하지 않았다. 실제 공고 조회·첨부 다운로드·운영 임베딩 호출은 실행하지 않았다.

## 변경 전후 구조

```text
변경 전                              변경 후
collect_bids.py                       collect_bids.py       CLI·기존 함수 import 호환
  HTTP 통신 + CLI 단계 제어           g2b_client.py         HTTP·첨부 목록·공고 행
bid_workflow.py                       bid_workflow.py       수집·사전 분류·평가 연계·선택
  collect_bids와 상호 참조
privacy.py          ┐
metadata.py         ├──────────────→ prepare_documents.py  마스킹·원문 조건·PDF 전처리
prepare_documents.py┘
각 파일의 JSON/CSV·해시·잠금 ──────→ common.py             공유 파일/상태 계약
build_dataset.py                      build_dataset.py      CLI·오프라인 산출물 조립
  RHWP 변환 포함       ───────────→ convert_documents.py  변환 도구와 두 변환 경로
knowledge.py                          knowledge.py          벡터 병합·세대 저장
ingest.py                             ingest.py             적재 실행·CLI
  build_dataset의 적재 코드 ──────→ ingest_sources()      PDF/웹 적재 실행 공유
api.py                                api.py                기존 HTTP 경로 유지
recommendations.py                    recommendations.py    기존 외부 추천 연결 유지
delivery.py                           delivery.py           선택 원본 ZIP/개별 전달
web_topics.py                         web_topics.py         공식 웹 원문 처리
audit_dataset.py                      audit_dataset.py      오프라인 검수
```

`__init__.py`를 포함한 최상위 Python 파일 수는 15개로 동일하다. 전처리 구현 3개를 1개로 줄인 대신 통신과 공통 입출력을 분리했다. 파일 개수 자체보다 중복 책임과 호출 방향을 정리했으며 모든 단계를 한 파일에 넣지 않았다. 기존 테스트 파일 두 개와 JSON 설정·Vue 클라이언트는 유지한다.

| 통합·이동 | 이유 |
|---|---|
| `privacy.py`, `metadata.py` 삭제 → `prepare_documents.py` | 같은 전처리 단계의 마스킹·연락처·페이지 출처·원문 조건 추출을 한 곳에서 읽기 위함 |
| `collect_bids.py`의 HTTP 함수 → `g2b_client.py` | CLI와 단계 제어의 상호 참조 해소. CLI는 통신과 단계 제어를 호출하는 진입점으로 유지 |
| JSON/JSONL/CSV·파일 해시·디렉터리 잠금 → `common.py` | 중복 구현과 기본 경로·성공 상태·CSV 필드 정의의 분산 해소 |
| `build_dataset.convert_rhwp()` 구현 → `convert_documents.py` | RHWP/LibreOffice 도구 처리를 수집 제어와 분리. 종전 함수 이름은 import로 유지 |
| PDF/웹 적재 실행 → `ingest.ingest_sources()` | `build_dataset --ingest`와 `ingest` CLI의 실행 중복 제거 |
| 긴 함수 분리 | 전처리는 원본 검증·PDF 읽기·페이지 생성·저장, 목록 발행은 평가 입력·기존 결과·응답 구성, 인덱스는 병합·세대 저장으로 나눔 |

`privacy`·`metadata`의 저장소 내부 import는 전부 `prepare_documents`로 옮겼다. 해당 두 파일에는 독립 CLI가 없었다. 외부 코드가 이 내부 모듈을 직접 import한다면 새 경로로 변경해야 한다. `collect_bids`의 기존 통신 함수 import와 모든 기존 CLI 명령은 유지한다.

## 주요 호출 방향

```text
collect_bids CLI / build_dataset CLI / api
  ├─ g2b_client.search_candidates         목록·링크 탐색
  └─ bid_workflow.prepare_discovery
       ├─ notice_attachment              공고문 한 개 식별
       ├─ _download_record               성공 파일 재사용·공고문 수신
       ├─ convert_documents              필요한 공고문의 내부 PDF 변환
       ├─ prepare_documents.prepare      마스킹·페이지·청크·해시·출처
       └─ _publish
            ├─ _evaluation_request       입력 버전·사전 후보·문서 근거
            ├─ _stored_evaluation        같은 입력 버전의 결과만 유지
            └─ _public_bid               목록과 첨부 대기 상태

외부 평가 결과 → record_evaluation        결과 저장만 수행
사용자 명시 선택 → select_bid/select_bids
  └─ _select_bid                          선택 공고의 전체 원본 첨부만 수신
       └─ delivery                       기존 ZIP/개별 파일 전달

전처리 자료 → ingest.ingest_sources
  ├─ knowledge.ingest_processed           PDF 적재 자료 구성
  ├─ web_topics.ingest_topics             웹 적재 실행
  └─ KnowledgeStore.upsert
       └─ _save_generation               벡터·출처를 쓴 후 current 포인터 교체
```

`recommendations.py`와 HTTP API의 기존 추천 호출은 유지했다. 추천은 외부 `bid_logic` 호출이며 점수 계산을 이 패키지에 추가하지 않았다. `bid_logic/`은 이 작업의 수정 대상이 아니다.

내부 모듈은 통신/변환/공통 처리 방향으로만 참조하고 정적 순환 import는 없다. 외부 SDK의 선택적 로딩과 외부 `bid_logic` 패키지 로더는 유지하되, 수집↔변환↔데이터셋 순환을 피하려고 쓰던 함수 내부 import는 제거했다.

## 유지하는 진입점

| 명령/진입점 | 역할 |
|---|---|
| `python -m data_pipeline.collect_bids` | 검색·재개·명시 단건 선택 |
| `python data_pipeline/collect_bids.py` | 동일 CLI의 직접 실행 호환 |
| `python -m data_pipeline.build_dataset` | 탐색 또는 기존 오프라인 자료 후처리 |
| `python -m data_pipeline.prepare_documents` | 기존 수집 폴더 전처리 |
| `python data_pipeline/prepare_documents.py` | 동일 전처리 CLI의 직접 실행 호환 |
| `python -m data_pipeline.convert_documents` | 변환 설정·기존 폴더 변환 |
| `python data_pipeline/convert_documents.py` | 동일 변환 CLI의 직접 실행 호환 |
| `python -m data_pipeline.ingest` | PDF/웹 적재 CLI |
| `python -m data_pipeline.audit_dataset` | 기존 오프라인 자료 검수 |
| `data_pipeline.api:app` | 기존 11개 HTTP 경로·요청/응답 스키마 유지 |

## 유지한 동작과 검증

| 항목 | 검증 |
|---|---|
| 최초 공고문만 확보 | 모의 다운로드 요청이 공고문 URL에 한정되는지 확인 |
| 공고문 미식별 | 제안요청서·신청서·ZIP으로 대체하지 않고 첨부를 deferred로 유지 |
| 사전 후보 분류·평가 입력 | 기존 JSON/JSONL/CSV와 사전 결과·입력 버전 비교 |
| 외부 결과 저장 | 전달받은 점수만 저장하며 선택 기록·다운로드 요청을 만들지 않음 |
| 미평가 점수 | 초기 및 입력 변경 후 score/max_score가 null인지 확인 |
| 선택한 공고만 전체 첨부 수신 | 1~2건 선택·다른 공고 제외·잘못된 선택 부작용 없음 확인 |
| 재개·부분 실패 | 성공 파일 재사용·실패만 재시도·불완전한 ZIP 거부 확인 |
| 원본·마스킹·출처 | 연락처 보존·이름 마스킹·원본 HWP 바이트·쪽수·해시 확인 |
| 버전 | 기업정보 변경 시 추천/평가 무효화·과거 평가 결과 거부 확인 |
| 인터페이스 | 전후 OpenAPI 전체 스키마 및 CLI 6종 도움말 비교 |

기존 테스트 파일은 삭제하지 않았고 새 테스트 파일도 추가하지 않았다. 기존 파일에 공고문 미식별 시 대체 수신 금지, 외부 결과 저장 시 다운로드 금지·프로필 변경 무효화 검사를 보강했다.

검증은 임시 디렉터리와 모의 다운로드로 진행했다. 네트워크 연결을 차단하고 운영 임베딩 모델 호출을 금지했으며, FAISS 검사는 임시 인덱스와 기존 오프라인 테스트 벡터만 사용했다. 전후 비교는 실행 시각과 임시 절대 경로만 정규화했다. 공고·평가 입력 버전·해시·파일 순서·첨부 상태 등은 비교 대상에서 제외하지 않았다.

- 자동 테스트: 29개 통과.
- 산출물·원본·ZIP·모의 요청 24항목 비교: 동일.
- OpenAPI 11개 경로의 전체 명세: 동일.
- CLI 6개 모듈의 도움말: 동일. 기존 직접 실행 CLI 3개도 정상 확인.
- 오프라인 CSV 메타데이터·출처표·대표 PDF·검수 보고서: 임시 자료에 변경 전/후 구현을 적용해 동일 확인.
- 범위 밖 파일 검사: 시작 시 기록한 20,054개 중 나머지 20,053개의 크기·수정시각이 동일했고, 로컬 변환 도구 설치 파일을 제외한 파일은 내용 해시도 동일했다. 기존 데이터·FAISS와 bid_logic 원본도 포함한다. 교재 PDF 1개(`AI서비스개발_Mini-project_교재_v3.1_임성열.pdf`)는 검사 시점에 없어졌다. 이 정리 작업은 해당 경로를 쓰거나 삭제하지 않았으며, 범위 밖이므로 복원하지 않았다.

## 남은 제약

외부 API·실제 변환 도구·운영 임베딩 연결의 재검증은 이번 작업에서 수행하지 않는다. 공고문 식별, 변환 품질, 모호한 참가 조건, 추천 품질의 기존 한계를 개선하는 기능 변경도 포함하지 않는다. 실제 자료·기존 FAISS를 재처리하지 않으며 데이터 마이그레이션도 필요하지 않다.

`build_dataset --prepare-only`의 기존 분기에서 도달할 수 없던 자동 변환 조건은 제거했다. 기존에 실행되던 명시적 `--rhwp` 경로는 유지한다. 잠금 파일명과 인덱스 세대/current 교체 순서도 유지한다.
