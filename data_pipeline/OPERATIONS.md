# 데이터 파이프라인 운영 범위

현재 기본 동작은 **API 목록 → 공고문 PDF 준비 → 사업 요약이 포함된 추천 목록 → 사용자 1~2건 선택 → 선택 공고 전체 첨부**입니다. 초기 목록 생성과 사용자 선택에는 점수 평가가 필요하지 않습니다.

실행 방법은 [README](README.md), 외부 평가 담당자 연결은 [평가 연계 규약](EVALUATION_HANDOFF.md)을 참고하세요.

| 단계 | 구현 |
|---|---|
| API 목록·첨부 링크 탐색 | `collect_bids.py` CLI → `g2b_client.py` 통신 |
| 공고문 한 개 식별·수신·전처리 | `bid_workflow.py`, `convert_documents.py`, `prepare_documents.py` |
| 공고문 본문 기반 사전 후보 목록 | `bid_workflow.py`; 점수 미계산 |
| 사업 개요·과업·기간 발췌와 출처 | `recommendations.py`; 추가 첨부 다운로드·LLM 요약 호출 없음 |
| 외부 평가 입력·결과 저장 | `evaluation_inputs.jsonl`, `record_evaluation`; 후속 기능용 호환 계약만 유지 |
| 사용자 선택 후 해당 공고 전체 첨부 | `select_bid`, CLI `--select-bid` 또는 선택 API |
| 이름 마스킹·공개 연락처·출처·원문 메타데이터 보존 | `prepare_documents.py` |
| JSON/JSONL/CSV·해시·잠금·상태 계약 | `common.py` |
| 전처리 자료·데이터 적재 | `prepare_documents.py`, `knowledge.py`, `ingest.py` |

`build_dataset.py`는 탐색·사용자 선택을 `bid_workflow.py`에 위임하며, 기존 오프라인 자료의 메타데이터·출처표·대표 PDF만 별도로 조립합니다. PDF·웹 적재 실행은 `ingest.ingest_sources()`를 공유하고 FAISS 세대 저장은 `knowledge.py`가 담당합니다.

평가 결과가 저장되거나 점수가 높다는 이유로 전체 첨부를 자동 다운로드하지 않습니다. 초기 공고문을 식별할 수 없으면 제안요청서·서식으로 대체하지 않습니다. 평가 산식·최종 자격 판정·사용자 인증·프로필 DB·화면은 다른 담당 영역입니다.
