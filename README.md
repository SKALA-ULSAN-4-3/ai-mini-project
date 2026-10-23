# AI Service Mini Project

기존 강의 예제와 나라장터 데이터 파이프라인을 포함합니다.

## 나라장터 데이터 파이프라인 (역할 1)

[실행 안내](data_pipeline/README.md)에 따라 공고 수집·PDF 변환·마스킹·메타데이터·출처표 작성·FAISS 적재를 수행합니다. 구현 범위는 역할 1과 OpenAPI 수집 확장 X1입니다.

수집 원본·변환 PDF·출처표·인덱스는 실행 후 로컬 `data/`에 생성합니다. 인증키, 데이터 산출물, 변환 도구와 가상환경은 커밋하지 않습니다.

## 공통 환경변수

`.env.example`을 참고하여 프로젝트 루트 `.env`에 실제 키를 설정합니다. 데이터 파이프라인은 실행 위치와 무관하게 루트 `.env`를 읽고 기존 환경변수가 있으면 우선합니다.

다른 하위 프로그램은 공통 실행 도우미로 실행할 수 있습니다.

```bash
python3 project_env.py --cwd workplace -- ./gradlew :app:run
python3 project_env.py --cwd rag-code-template_ext -- python3 -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001
```

공통 실행 도우미는 단일 행 `KEY=value`, 따옴표, 주석을 지원하며 셸 명령 치환이나 변수 보간을 실행하지 않습니다. 서비스별 의존성과 설정은 별도로 준비합니다.
