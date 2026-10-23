# 데이터 파이프라인 운영 범위

실행 방법과 산출물은 [README](README.md)를 기준으로 합니다.

| 담당 업무 | 구현 |
|---|---|
| 공고 20건 선정·다운로드 | `build_dataset.py`, `dataset_selection.json` |
| OpenAPI 자동 조회·다운로드(X1) | `collect_bids.py` |
| HWP/HWPX→PDF 변환 | `convert_documents.py` |
| 페이지 추출·마스킹·출처 보존 | `prepare_documents.py`, `privacy.py` |
| 공고 메타데이터·출처표 | `metadata.py`, `build_dataset.py` |
| 데이터 검수·중복 정리 | `audit_dataset.py` |
| 임베딩·FAISS 적재 | `knowledge.py`, `ingest.py` |
| `/upload-paper`·`/upload-topic` | `api.py`, `web_topics.py` |

기획서 역할 2~5의 자격 판정·요약·Q&A·점수·추천·체크리스트·인증·프론트엔드는 이 패키지에서 구현하지 않습니다. 기존 강의 템플릿과 다른 팀원 영역은 수정·삭제하지 않습니다.
