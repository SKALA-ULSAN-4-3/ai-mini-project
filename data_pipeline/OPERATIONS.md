# 데이터 파이프라인 운영 범위

실행 방법과 산출물은 [README](README.md)를 기준으로 합니다.

| 담당 업무 | 구현 |
|---|---|
| 검색 스냅샷·공고문 확보·선택 첨부 준비·진행률 | `api.py`, `search_jobs.py`, `common.py` |
| 기존 오프라인 데이터셋 도구 | `build_dataset.py` (고정 목록 파일 삭제) |
| OpenAPI 검색·선택 공고 차수 조회·다운로드 | `collect_bids.py` |
| HWP/HWPX→PDF 변환 | `convert_documents.py` |
| 페이지 추출·마스킹·출처 보존 | `prepare_documents.py`, `privacy.py` |
| 공고 메타데이터·출처표 | `metadata.py`, `build_dataset.py` |
| 데이터 검수·중복 정리 | `audit_dataset.py` |
| 임베딩·FAISS 적재 | `knowledge.py`, `ingest.py` |
| `/upload-paper`·`/upload-topic` | `api.py`, `web_topics.py` |

기획서 역할 2~5의 자격 판정·요약·Q&A·점수·추천·체크리스트·인증·프론트엔드는 이 패키지에서 구현하지 않습니다. 기존 강의 템플릿과 다른 팀원 영역은 수정·삭제하지 않습니다.

확정 흐름의 API 계약·검증·남은 제약은 [MD 적용 결과](MD_DATA_GUIDE.md)를 확인합니다. 운영 서버는 기존 RAG 서버(:8001) 한 개이며 worker 1개입니다. 실시간 적재는 upsert만 사용하고 기존 오프라인 전체 교체는 별도 인덱스에서 실행합니다.
