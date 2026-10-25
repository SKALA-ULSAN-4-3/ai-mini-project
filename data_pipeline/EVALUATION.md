# 평가 원문 확보·재현

## 기준과 저장 위치

공식 목록은 `rag-code-template_ext/evaluation/real/bids.csv` 및 `manifest.json`이다.
20개 공고·차수를 과거 고정 시각 `2026-10-07T16:00:00+09:00`에 평가한다.
원문 URL·파일명·차수·SHA-256 기준은 같은 폴더의 `source-manifest.json` 74개 항목이다.
이미 모든 파일에 해시가 있어 새 해시를 임의로 합의·덮어쓰지 않는다. 해시가 없거나 달라지면
3번이 공식 원문·차수와 기준 해시를 확인해야 하며 스크립트는 실패 처리한다.

선택 방식은 **공식 URL 재다운로드 스크립트**다. 공유 드라이브 권한이나 원문 바이너리의 Git 커밋이 필요 없다.
운영 실시간 검색·인덱스와 분리하며 `dataset_selection.json`을 복원하거나 생성하지 않는다.
이 모듈을 운영 API에서 호출하지 않는다.

기본 저장 위치(모두 `/data/` 아래이므로 Git 제외):

| 경로 | 용도 |
| --- | --- |
| `data/evaluation-source-20261023/raw/{공고번호}_{차수}/` | 검증된 PDF/HWP/HWPX 등 원문 74개 |
| `data/evaluation-source-20261023/attachments.json` | 검증 성공한 첨부와 이 PC의 실제 저장 경로 |
| `data/evaluation-source-20261023/evidence.json` | PDF 페이지·HWPX 표의 근거 258개, 추천 테스트 입력 |
| `data/evaluation-source-20261023/download-failures.json` | 실패 원문 및 원인, 정상 완료 시 빈 배열 |
| `data/evaluation-source-20261023/verification.json` | 파일 수·입력 manifest 해시·검증 결과 |

## 받는 방법

배포 브랜치 develop에 아직 병합 전이면 [PR #18](https://github.com/SKALA-ULSAN-4-3/ai-mini-project/pull/18)의
`feat/data-evaluation-reproduction` 브랜치를 받아 실행한다.

저장소 루트에서 Python 3.10 이상과 기존 데이터 환경을 사용한다. 원문 다운로드와 추천 라벨 테스트에는
나라장터 API 키·OpenAI 키·LibreOffice·Java가 필요 없다. 최소 Python 의존성은 `pypdf>=6.10,<7`이며,
Windows 등 시스템 시간대 데이터가 없는 환경은 `tzdata`도 설치한다.

```bash
python3 -m venv .venv-evaluation
.venv-evaluation/bin/python -m pip install 'pypdf>=6.10,<7' tzdata
.venv-evaluation/bin/python -m data_pipeline.evaluation_sources
.venv-evaluation/bin/python -m data_pipeline.evaluation_sources --verify-only
```

Windows는 `.venv-evaluation/bin/python` 대신 `.venv-evaluation\Scripts\python.exe`를 사용한다.
파일명에는 공고번호와 차수가 포함된 상위 폴더를 유지한다.
기존 전체 환경이면 위 Python 대신 `data_pipeline/.venv/bin/python`을 사용한다.

파일마다 SHA-256이 맞는 성공 파일은 재사용하고 실패 파일만 다시 시도한다.
다운로드는 기존 `collect_bids.download_file`을 재사용하므로 공식 도메인·리다이렉트·오류 HTML·크기 제한 검사를 유지한다.
임시 폴더에 받은 뒤 기준 해시가 일치해야 최종 파일로 교체한다.
다른 차수, 누락, 해시 불일치가 있으면 종료 코드 1 또는 입력 오류로 중단하므로 다음 단계로 넘어가지 않는다.
외부 시스템 장애는 실패 목록을 보고 같은 명령으로 재시도한다.

기존 1번 수집 파일이 있는 PC는 선택적으로 아래처럼 같은 공고·차수·URL·파일명·해시가 일치하는 파일만 재사용할 수 있다.

```bash
data_pipeline/.venv/bin/python -m data_pipeline.evaluation_sources --reuse-manifest data/corpus/attachments.csv
```

다운로드 성공 후 검증된 원문에서 `evidence.json`을 생성한다. 기존 `prepare_real`의 전체 초기화를 실행하지 않아
공식 `bids.csv`, 프로필, 정답, 평가 시각을 변경하지 않는다. HWPX는 실제 XML 위치를 보존하고 PDF 쪽수로 바꾸지 않는다.
재생성한 근거의 텍스트 추출 결과가 기존 평가자의 캐시와 바이트 단위로 동일하다는 뜻은 아니다.

## 추천 라벨 재현 확인

다운로드와 `--verify-only`가 성공한 뒤 실행한다. 저장소 루트 기준 명령이다.

```bash
cd rag-code-template_ext
../.venv-evaluation/bin/python -m unittest discover -s tests -p test_recommendation_labels.py -v
```

완료 조건은 `Ran 2 tests`, `OK`, `skipped` 0개다. `evidence.json` 누락으로 skip되면 완료가 아니다.
테스트는 임시 폴더에서 정답 재생성을 검사하며 공식 정답 파일을 수정하지 않는다.
다른 평가 전체에 필요한 FAISS·임베딩·LLM 검증 환경은 별도이고 이 명령의 통과와 구별한다.

## 2026-10-25 검증

- 공식 목록 20개, 원문 74개, 공고번호·차수·대표 파일명·URL 대응 일치.
- 기존 로컬 원문 74개가 모두 기준 SHA-256과 일치. 근거 258개 생성.
- 별도 깨끗한 체크아웃에서 기존 파일 없이 URL로 74개 새 다운로드. 누락·해시 불일치 0개.
- 새 다운로드와 로컬 재사용의 근거 결과가 동일. SHA-256: `db99c53508bd973b6d3c110fc358393ca7c2b39ad2b8dfbe2e0df32f409efae5`.
- 별도 체크아웃의 `test_recommendation_labels` 2개 통과, skip 0개.
- 차수·URL 차수·해시 누락·변조·원문 누락·연결 실패·성공 파일 재사용 자동검사 4개 통과.
- [검증 기록](verification/evaluation-20261025.json).

이는 같은 PC의 격리 재현이다. **3번의 다른 PC에서 다운로드→검증→테스트 통과 확인은 남아 있다.**
원문 검증 성공은 사람이 정답을 승인했다는 뜻이 아니다. 사람 검토 상태는 변경하지 않았다.

## 2번·3번에게 전달할 내용

2번 기획서에는 공식 평가셋 경로, 평가 전용 20건·3프로필·60판정, 과거 고정 시각,
원문 74개·해시 검증·위 다운로드 명령을 적는다. 운영의 실시간 검색 성능이나 사람 승인 정확도와 혼용하지 않는다.
3번은 같은 기준 목록·원문 차수·해시를 확인하고 본인 PC에서 위 두 명령과 테스트를 실행해
파일 수, 실패 수, `Ran 2 tests / OK / skipped 0` 결과를 회신한다. 실제 메시지 전송은 하지 않았다.
