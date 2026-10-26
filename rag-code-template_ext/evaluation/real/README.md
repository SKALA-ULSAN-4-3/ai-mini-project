# 공식 평가셋: 고정 20건

`bids.csv`와 `manifest.json`을 공식 평가셋으로 사용한다. 서비스 실시간 검색과 분리한다.
검색 기간은 2026-08-01~2026-10-07, 재생 시각은 2026-10-07 16:00 KST다.
`profiles.json`의 3개 프로필은 가상이며 현재 유효 공고 추천 정확도를 뜻하지 않는다.

## 새 PC에서 실행

Python 3.10 이상에서 프로젝트 루트 기준:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install fastapi httpx pypdf openai faiss-cpu langchain-community==0.4.1
cd rag-code-template_ext
../.venv/bin/python -m bid_logic.restore_sources
../.venv/bin/python -m unittest discover -s tests
../.venv/bin/python -m bid_logic.evaluate_recommendation_change
```

`source-manifest.json`의 공개 URL로 첨부 74개를 `data/evaluation-source-20261023/raw/`에
복원하며 모두 SHA-256을 확인한다. API 키 없이 실행 가능하다. 일시 오류는 3회까지 재시도하고,
계속 해시가 다르면 중단한다. 성공 파일은 재사용하므로 같은 명령으로 이어서 실행할 수 있다.
공유받은 원문 검증만 할 때는 `--offline`을 사용한다.

새 `evidence.json`에는 PDF 253페이지의 pypdf 추출 결과를 담는다. 기존 파일이 있으면 원래
HWPX 근거와 모델 응답의 doc_no 참조를 보존하기 위해 덮어쓰지 않는다. 원본 HWP/HWPX도
다운로드하지만 과거 PDFKit/HWPX 추출·임베딩·모델 응답 캐시 전체를 복원하는 명령은 아니다.

`metadata-corrections.json`은 원문에서 확인한 마감 누락 1건의 전후 값과 출처다.
`bids.csv`는 보정 적용본이다. 재측정 코드는 보정 전 값을 메모리에서 복원하고 같은 정답,
프로필, 저장 임베딩으로 비교하여 `recommendation-improvement.json`을 만든다.
`gold.json`은 변경하지 않는다. 사람의 실제 검토와 다른 팀원 PC에서의 재현 확인은 별도로 필요하다.

## 원문 확인 메타데이터 보완

`bid_logic/notice_metadata.json`에 두 공고의 출처·지역·단계별 기한을 보존한다.
`notice_metadata.py`가 정확히 일치하는 공고번호·차수에만 적용하며, 다른 차수에는 전파하지 않는다.
마산의 regions는 경남 OR 부산이다. 원문의 주된 영업소 유지기간 등 자격 증빙은 여전히 사람 확인이 필요하다.
영진의 CSV deadline은 신규 참가신청 기한(2026-10-08 18:00 KST)이다. 제안서 파일·제본 제출 기한과 다르다.
추천 API의 deadline_kind=participation, deadline_event, deadlines 배열로 의미와 세 일정을 전달한다.
이미 신청한 업체는 신규 참가 필터의 제외를 제안서 제출 종료로 해석하지 말고 체크리스트의 개별 기한을 확인한다.
체크리스트는 중복 별칭을 합치고 모호한 제안서 제출 일정에는 임의 날짜를 부여하지 않는다.
10월7일 재생 시각의 평가 정답과 P@5에는 변화가 없으며 상세 검증은 notice-metadata-verification.json에 있다.
