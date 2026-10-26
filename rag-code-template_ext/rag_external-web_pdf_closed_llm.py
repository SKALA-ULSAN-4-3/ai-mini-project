#### 다음 실습 코드는 학습 목적으로만 사용 바랍니다. 문의 : audit@korea.ac.kr 임성열 Ph.D.

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from sqlalchemy.ext.asyncio import create_async_engine
from fastapi.responses import JSONResponse
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel, Field
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from pypdf import PdfReader
from langchain_core.messages import HumanMessage

# 담당 기능의 구현은 bid_logic의 기능별 파일에서 관리합니다.
from bid_logic import load_bids_csv, faiss_hits, embedding_title_similarity
from bid_logic.api import create_bid_router


# 패키지는 저자 업데이트에 맞춰 해당 버전으로 맞추는 것을 권장
# 직접 저자의 site-packages/패키지명/을 직접 수정하는 것은 추천하지 않음
# 추후 pip install -U 시 원상 복구되며 버전 충돌 가능성 있음angchain.text_splitter 
# 참고로 다음은 Deprecated 패키지 또는 미사용 패키지 목록
# from langchain_community.embeddings import HuggingFaceEmbeddings
# from langchain.vectorstores import FAISS
# from langchain.chat_models import ChatOpenAI
# from langchain.embeddings import OpenAIEmbeddings
# from langchain_openai import OpenAIEmbeddings, ChatOpenAI
# from langchain_community.embeddings import OpenAIEmbeddings
# from langchain.chat_models import ChatOpenAI
# from langchain.schema import HumanMessage
# from langchain.embeddings import HuggingFaceEmbeddings  
# from pydantic import BaseModel

from typing import List, Dict, Any, Optional
import os
import re
import json
import asyncio
import tempfile
import time
from datetime import datetime, UTC
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 .env(1·3번과 공통)를 먼저 읽고, 옮기는 동안만 이 폴더의 .env도 보조로 읽는다 (이미 있는 값은 덮지 않음)
from knowledge_bridge import (StoreCache, sync_bids_csv, to_bid_logic_scoring, to_bid_logic_checklist, to_iso_due,
                              classify_attachment, search_results)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY가 설정되지 않았습니다.")

# ✅ DB 연결 정보
ASYNC_DB_URL = os.getenv("ASYNC_DB_URL", "mysql+aiomysql://root:password@127.0.0.1:53301/sql_db?charset=utf8mb4")
engine = create_async_engine(ASYNC_DB_URL)

# ✅ FastAPI 인스턴스
app = FastAPI(
    title="RAG 기반 Closed Source LLM API Server",
    description="외부 정보 기반 벡터화 + LLM 질의 응답",
    version="1.0.0"
)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174",
                   "http://127.0.0.1:5174",
                   "http://[::1]:5174",         # IPv6도 허용
                   "http://localhost:8001","*"],
    allow_methods=["*"], allow_headers=["*"], allow_credentials=True,
)

# ✅ 전역 벡터 저장소: 1번 데이터 파이프라인이 적재한 data/indexes/{pdf,web}를 읽는다.
#    적재(청크 분할 · 임베딩 · 마스킹)는 1번 담당이라 이 서버는 읽기만 하고, 업로드 API는 1번 라우터를 그대로 붙인다.
VECTORSTORE_WEB = None
VECTORSTORE_PDF = None
STORES = StoreCache()
STORE_STATE: dict[str, str | None] = {"pdf_generation": None, "web_generation": None, "embedding_model": None}
EXTRACT_CACHE: dict[tuple[str, str, str], dict] = {}  # (bid_no, revision, 종류) → {지문, 결과}. 같은 공고 재요청 시 LLM 비용 절감
BID_FINGERPRINTS: dict[tuple[str, str], int] = {}     # (bid_no, revision) → 적재된 조각 목록의 지문

def refresh_stores():
    # 요청마다 1번 저장소의 현재 세대를 확인해, 업로드로 세대가 바뀌었을 때만 다시 읽는다
    global VECTORSTORE_PDF, VECTORSTORE_WEB
    pdf, pdf_generation, manifest = STORES.get("pdf")
    web, web_generation, _ = STORES.get("web")
    if pdf_generation != STORE_STATE["pdf_generation"]:
        # 실시간 흐름에서는 공고를 자주 적재하므로 캐시를 통째로 지우지 않고, 공고별 문서 지문만 다시 계산한다.
        # 지문이 바뀐 공고(문서가 추가 · 교체된 공고)만 다음 요청 때 다시 추출된다.
        BID_FINGERPRINTS.clear()
        if pdf is not None:
            chunks: dict[tuple[str, str], list[str]] = {}
            for d in pdf.docstore._dict.values():
                if d.metadata.get("bid_no"):
                    chunks.setdefault((d.metadata["bid_no"], d.metadata.get("revision", "")), []).append(
                        d.metadata.get("chunk_id", ""))
            BID_FINGERPRINTS.update({k: hash(tuple(sorted(v))) for k, v in chunks.items()})
    STORE_STATE.update(pdf_generation=pdf_generation, web_generation=web_generation,
                       embedding_model=(manifest or {}).get("embedding_model"))
    VECTORSTORE_PDF, VECTORSTORE_WEB = pdf, web
    sync_bids_csv()  # 1번 bids.csv가 갱신되면 3번 형식(data/bids.csv)으로 다시 변환

refresh_stores()
print(f"{'✅' if VECTORSTORE_PDF else '❌'} PDF 저장소 (세대 {STORE_STATE['pdf_generation']}) · "
      f"{'✅' if VECTORSTORE_WEB else '❌'} 웹 저장소 (세대 {STORE_STATE['web_generation']})")

@app.middleware("http")
async def keep_stores_current(request, call_next):
    refresh_stores()
    return await call_next(request)

# ✅ 로그인 확인: BACKEND_URL(4번)이 있으면 /health 외 모든 API에 Bearer 토큰 필요 (기획서 03). 없으면 로컬 개발용으로 열어 둠
from fastapi import Depends
from backend_auth import require_login
AUTH = [Depends(require_login)]

# ✅ 검색 · 적재 API (/search-bids, /fetch-notices, /fetch-documents, /jobs, /upload-*, /data-status): 1번 라우터
from data_pipeline.api import router as data_pipeline_router
app.include_router(data_pipeline_router, tags=["데이터 적재 (1번)"], dependencies=AUTH)

# ✅ X3 음성 질의 (/stt, /tts): 화면이 STT → /rag-query → TTS 순서로 부른다
from voice_routes import router as voice_router
app.include_router(voice_router, dependencies=AUTH)

# ✅ 공고 추리기·예상 점수·체크리스트 API 연결
def register_bid_routes(*, profile_dependency, scoring_provider, checklist_provider,
                        bids_provider=None, search=None, clock=None, search_results_provider=None,
                        title_similarity=None, loaded_keys_provider=None, agent_model=None,
                        require_search_id=False):
    """팀원의 인증/추출 결과를 연결한 뒤 호출하면 기존 app에 C2·C4·C5를 등록합니다.

    profile_dependency: JWT 검증 후 현재 회사 프로필을 반환하는 FastAPI 의존성.
    scoring_provider/checklist_provider: (bid_no, revision) -> 구조화 결과 또는 None.
    기본 공고 CSV: 이 파일 기준 data/bids.csv (합성 fixture를 사용하지 않습니다).
    인증 공급자 없이 자동 등록하지 않으며, 기존 업로드/질의 API는 그대로 둡니다.
    """
    router = create_bid_router(
        profile_dependency=profile_dependency,
        bids_provider=(bids_provider if bids_provider is not None else
                       lambda: load_bids_csv(BASE_DIR / "data" / "bids.csv")),
        scoring_provider=scoring_provider,
        checklist_provider=checklist_provider,
        # 호출할 때의 전역 저장소를 사용해 업로드 이후 교체된 인덱스도 반영합니다.
        search=(search if search is not None else
                lambda query, keys: faiss_hits(VECTORSTORE_PDF, query, keys)),
        clock=clock,
        search_results_provider=search_results_provider,
        title_similarity=title_similarity,
        loaded_keys_provider=loaded_keys_provider,
        agent_model=agent_model,
        require_search_id=require_search_id,
    )
    # include_router의 내부 표현이 달라지는 FastAPI 버전에서도 공개 스키마로 확인합니다.
    existing_paths = set(app.openapi().get("paths", {}))
    if any(route.path in existing_paths for route in router.routes):
        raise RuntimeError("공고 API가 이미 등록되어 있습니다. 중복 연결을 확인해 주세요.")
    app.include_router(router)
    app.openapi_schema = None  # 연결 전 생성된 Swagger 캐시를 갱신합니다.
    return router


# 백엔드 담당자의 실제 함수가 준비되면 서버 시작 전에 한 번 호출합니다.
# register_bid_routes(
#     profile_dependency=get_authenticated_profile,
#     scoring_provider=get_extracted_scoring_table,
#     checklist_provider=get_extracted_checklist,
# )

# ✅ 출처 표기: PDF는 "파일명 p.쪽", 웹은 "제목 | URL"
def source_label(meta: dict) -> str:
    # 웹 자료(1번이 file_name에 주제명을 넣음)는 원문을 열 수 있게 제목과 URL로 표기
    if meta.get("topic") and meta.get("source_url"):
        return f"{meta.get('title') or meta['topic']} | {meta['source_url']}"
    src = meta.get("source", "unknown")
    if meta.get("page"):
        return f"{src} p.{meta['page']}"
    if meta.get("title"):
        return f"{meta['title']} | {src}"
    return src

def source_ref(meta: dict) -> dict:
    # 3번 규격의 구조화 출처: 공고 · 차수 · 파일명 · 1부터 시작하는 쪽수
    return {"bid_no": meta.get("bid_no", ""), "revision": meta.get("revision", ""),
            "filename": meta.get("filename", ""), "page": meta.get("page"),
            "collected_at": meta.get("collected_at", "")}

def stored_sources(store) -> set[str]:
    if store is None:
        return set()
    return {d.metadata.get("source", "unknown") for d in store.docstore._dict.values()}

def stored_bids(store) -> set[tuple[str, str]]:
    if store is None:
        return set()
    return {(d.metadata["bid_no"], d.metadata.get("revision", "")) for d in store.docstore._dict.values()
            if d.metadata.get("bid_no")}

def resolve_revision(bid_no: str, revision: str | None) -> str:
    """공고번호의 차수를 정한다. 지정하지 않았으면 적재된 차수가 하나일 때만 그것을 쓴다."""
    loaded = stored_bids(VECTORSTORE_PDF)
    revisions = sorted(r for b, r in loaded if b == bid_no)
    if not revisions:
        raise HTTPException(status_code=404, detail=f"적재되지 않은 공고번호입니다: {bid_no} "
                                                    f"(적재된 공고: {sorted('-'.join(k) for k in loaded)})")
    if revision:
        if revision not in revisions:
            raise HTTPException(status_code=404, detail=f"{bid_no} 공고에 {revision} 차수가 없습니다 (적재된 차수: {revisions})")
        return revision
    if len(revisions) == 1:
        return revisions[0]
    raise HTTPException(status_code=400, detail=f"{bid_no} 공고는 차수가 여러 개입니다. revision을 지정하세요: {revisions}")

# ✅ 자격 · 배점처럼 사람이 최종 확인해야 하는 질문
REVIEW_KEYWORDS = ("자격", "참가", "제한", "면허", "업종", "지역", "배점", "점수", "평가")

def needs_review_for(question: str) -> bool:
    return any(k in question for k in REVIEW_KEYWORDS)

# ✅ PDF 질의 응답 형식: 답을 찾았는지(found)와 인용 문서(cited)를 답변 문장과 따로 받는다.
#    문장 속 표시("[명시 없음]", "근거: 1, 3")에 기대면 표현이 조금만 달라져도 handoff · 출처가 틀어졌다.
class RagAnswer(BaseModel):
    # 실제 공고 평가(A08, B08, 2026-01 Q17): "얼마"를 물었는데 원문이 "입찰금액의 5% 이상"처럼 비율로 정해 두면 답을 옮기고도 false로 판단했다.
    # 다만 "비율 · 조건도 답"이라고만 쓰면 E01(예상 낙찰가)에 사업금액 상한을 답으로 끌어와 추정했다 → 그 항목 자체의 규정만 인정
    found: bool = Field(description="질문이 묻는 항목의 답이 PDF에 직접 적혀 있으면 true. 질문한 바로 그 항목의 금액 · 기간을 PDF가 "
                                    "비율 · 산식으로 정해 두었다면(예: '입찰보증금: 입찰금액의 5% 이상') 그것이 답이므로 true. "
                                    "다른 항목의 상한 · 조건에서 값을 이끌어 내거나 추정해야 하면(예: 예상 낙찰가를 사업금액 상한으로 짐작) false. "
                                    "관련 내용만 있고 질문의 답 자체가 없으면 false")
    answer: str = Field(description="한국어 답변. found가 false면 '문서에 명시되어 있지 않습니다.'로 시작하고 PDF에 적힌 관련 사실만 덧붙이며, "
                                    "그 사실로부터 '따라서 ~일 것입니다' 같은 결론이나 추정을 만들지 않는다. "
                                    "'[문서 2]에 따르면'처럼 내부 문서 번호를 답변 문장에 쓰지 않는다 (출처는 cited로만 표시)")
    cited: List[int] = Field(description="답변의 근거로 사용한 [문서 n]의 번호 목록")

# 프롬프트를 지켜도 번호가 새어 나오는 경우를 대비해 답변 문장에서 지운다 (사용자에게 [문서 n]은 의미 없는 내부 번호)
DOC_REF_RE = re.compile(r"\s*\[문서\s*\d+(?:\s*[,|][^\]]*)?\]\s*(?:에\s*따르면|에서는|에서|에)?,?\s*")

def strip_doc_refs(text: str) -> str:
    text = re.sub(r"\s{2,}", " ", DOC_REF_RE.sub(" ", text))
    return re.sub(r"\s+([.,])", r"\1", text).strip()

# ✅ 글자마다 띄어 쓴 PDF 텍스트("계 약 보 증 금(계 약 금 액  10%이 상)")를 LLM에 넘기기 전에 붙인다.
#    이런 PDF는 글자 사이 1칸 · 단어 사이 2칸이라, 한 글자씩 떨어진 4글자 이상 또는 2칸 띄움이 섞인 구간만 고친다
#    ("할 수 있다"처럼 원래 한 글자 단어가 이어지는 정상 문장은 3글자 이하라 그대로 둔다). 저장된 원문은 바꾸지 않는다.
SPACED_RUN_RE = re.compile(r"(?<![가-힣])[가-힣](?: {1,2}[가-힣](?![가-힣]))+")

def _join_run(m: re.Match) -> str:
    run = m.group()
    parts = run.split("  ")
    if all(len(p) == 1 for p in parts) and len(parts) > 1:   # "개  찰  장  소"처럼 모든 글자를 2칸씩 띄운 제목
        return "".join(parts)
    if len(re.findall(r"[가-힣]", run)) < 4 and len(parts) == 1:
        return run
    return " ".join(p.replace(" ", "") for p in parts)

def join_spaced_letters(text: str) -> str:
    return SPACED_RUN_RE.sub(_join_run, text)

# 답을 찾지 못한 답변에서 LLM이 관련 사실로부터 덧붙인 추정 문장을 지운다 (프롬프트로는 2번 중 1번꼴로 남았음)
SPECULATION_RE = re.compile(r"따라서|그러므로|일 것|것으로 보|로 추정|해석될 수|예상됩니다")

def drop_speculation(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(s for s in sentences if not SPECULATION_RE.search(s))

# ✅ 키워드 보강: 의미 검색은 질문 단어가 원문에 그대로 있어도 조각에 다른 정보가 섞여 있으면 놓친다
#    (평가셋 Q02 "용역 기간" ↔ 원문 "용역기간", Q03 "계약방법"). 띄어쓰기를 무시하고 질문 단어가 든 조각을 함께 넘긴다.
PARTICLES = ("에서", "으로", "에게", "까지", "부터", "이나", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "야")
STOPWORDS = {"얼마", "어떻게", "언제", "무엇", "뭐", "뭐야", "알려줘", "있어", "있나", "있는지", "되나", "돼", "해", "하나",
             "이번", "해당", "어디", "몇"}

def query_terms(question: str) -> list[str]:
    words = []
    for w in re.findall(r"[가-힣A-Za-z0-9]+", question):
        for p in PARTICLES:
            if len(w) > 2 and w.endswith(p):
                w = w[: -len(p)]
                break
        if len(w) >= 2 and w not in STOPWORDS:
            words.append(w)
    # 질문은 띄어 쓰고 원문은 붙여 쓴 경우("용역 기간" → "용역기간")를 잡도록 이웃한 두 단어를 이은 것도 넣는다
    return list(dict.fromkeys(words + [a + b for a, b in zip(words, words[1:])]))

def keyword_chunks(store, question: str, bid_no: str | None, revision: str | None, exclude: set,
                   n: int = 3) -> list[Document]:
    terms = query_terms(question)
    scored = []
    for d in store.docstore._dict.values():
        if bid_no and (d.metadata.get("bid_no"), d.metadata.get("revision")) != (bid_no, revision):
            continue
        if (d.metadata.get("source"), d.metadata.get("page"), d.page_content) in exclude:
            continue
        text = _squash(d.page_content)
        score = sum(len(t) for t in terms if t in text)  # 길고 구체적인 단어가 맞을수록 높게
        if score:
            scored.append((score, d))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:n]]

def elapsed_ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)

# ✅ 엔진 · 적재 상태 확인
@app.get("/health", summary="엔진 · 벡터 저장소 상태", tags=["운영"])
async def health():
    def count(store):
        return len(store.docstore._dict) if store is not None else 0
    return {
        "status": "ok",
        "pdf_chunks": count(VECTORSTORE_PDF),
        "pdf_files": sorted(stored_sources(VECTORSTORE_PDF)),
        "bids": [{"bid_no": b, "revision": r} for b, r in sorted(stored_bids(VECTORSTORE_PDF))],
        "web_chunks": count(VECTORSTORE_WEB),
        "pdf_generation": STORE_STATE["pdf_generation"],
        "embedding_model": STORE_STATE["embedding_model"],
    }

# 질의 요청/응답 모델 정의
# ✅ 질의 요청 모델
class RAGRequest(BaseModel):
    prompt: str = Field(default=..., description="질문 프롬프트")
    source: str = Field(default=..., description="web | pdf")
    # 평가셋 26문항 기준 top_k 5 → 10에서 정확 16/22 → 20/22, 응답 시간 변화 0.1초 (eval/results)
    top_k: int = Field(default=10, ge=1, description="검색할 결과 수 (기본값 10)")
    bid_no: Optional[str] = Field(default=None, description="공고번호 (지정하면 그 공고 PDF에서만 검색)")
    revision: Optional[str] = Field(default=None, description="공고 차수. 생략하면 적재된 차수가 하나일 때 자동 선택")

    class Config:
        validate_by_name = True

# ✅ 응답 모델 (설명만 필요하면 Field 생략 가능)
class AnswerResponse(BaseModel):
    prompt: str
    response: str
    sources: List[str] = Field(default_factory=list, description="근거 위치 (PDF: 파일명 p.쪽, 웹: 제목 | URL)")
    needs_review: bool = Field(default=False, description="자격 · 배점 등 담당자 확인이 필요한 답변")
    handoff: bool = Field(default=False, description="문서에서 근거를 찾지 못해 담당자에게 넘김")
    latency_ms: int = 0

# ✅ RAG 기반 질의 응답 처리
from fastapi import Body

# 유틸
def extract_by_marker(text: str,
                      start: str = "### ANSWER_START",
                      end: str = "### ANSWER_END") -> str | None:
    i = text.find(start)
    if i == -1:
        return None
    j = text.find(end, i + len(start))
    if j == -1:
        return None
    return text[i + len(start): j].strip()

# 컨텍스트가 "id:\n title:\n content:" 형태일 때의 간단 백업 파서(옵션)
import re
def fallback_extract_from_context(context: str, question: str) -> str | None:
    q = re.sub(r"[^\w가-힣A-Za-z0-9 ]", "", question).strip()
        # []: 문자 클래스 (이 안의 문자 중 하나와 매칭)
        # ^: 문자 클래스 앞에 있으면 "not"의 의미 → 이 안에 포함되지 않은 문자를 의미
        # \w: 알파벳 + 숫자 + 밑줄 → [A-Za-z0-9_]와 동일
        # 가-힣: 한글 완성형 유니코드 범위
        # A-Za-z0-9: 영문자와 숫자 (중복이긴 하지만 명시적 표현)
        # 공백( ): 띄어쓰기 허용
    blocks = re.split(r"\n\s*\n", context.strip())
    for b in blocks:
        m_title = re.search(r"^title:\s*(.+)$", b, flags=re.MULTILINE | re.IGNORECASE)
        m_content = re.search(r"^content:\s*(.+)$", b, flags=re.MULTILINE | re.IGNORECASE)
                    # ^content:
                    # → 줄의 처음이 content:로 시작해야 함
                    # (줄의 시작임을 의미하는 ^는 re.MULTILINE이 설정된 경우 각 줄마다 적용됨)
                    # \s*
                    # → content: 뒤에 공백이 0개 이상 있어도 허용
                    # (.+)
                    # → 공백을 제외한 내용이 최소 1자 이상 존재해야 함
                    # → 이 부분이 캡처 그룹 1번으로 추출됨
                    # $
                    # → 줄의 끝까지 매칭
        if m_title and m_content:
            t = re.sub(r"[^\w가-힣A-Za-z0-9 ]", "", m_title.group(1)).strip()
            if q.lower() in t.lower():
                return m_content.group(1).strip()
    m_any = re.search(r"^content:\s*(.+)$", context, flags=re.MULTILINE | re.IGNORECASE)
    return m_any.group(1).strip() if m_any else None

# ✅ 질의 응답 라우터
@app.post("/rag-query", dependencies=AUTH, response_model=AnswerResponse, summary="Closed Source LLM + 벡터 DB 질의", tags=["질의 응답"])
async def rag_query(rag_request: RAGRequest = Body(...)):
    t0 = time.perf_counter()
    review = needs_review_for(rag_request.prompt)
    revision = None

    def not_found(message: str) -> AnswerResponse:
        # 근거가 없으면 LLM이 지어내지 않도록 답하지 않고 담당자에게 넘긴다
        return AnswerResponse(prompt=rag_request.prompt, response=message,
                              handoff=True, latency_ms=elapsed_ms(t0))

    # 1. 벡터스토어 및 LLM 결정
    if rag_request.source == "web":
        if VECTORSTORE_WEB is None:
            raise HTTPException(
                status_code=400,
                detail="❗ 외부 WEB 벡터값이 로딩되지 않았습니다. 먼저 외부 정보를 수집해서 벡터화를 진행해주세요.",
            )
        vectorstore = VECTORSTORE_WEB
        llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
        llm_type = "openai" # huggingface

    elif rag_request.source == "pdf":
        if VECTORSTORE_PDF is None:
            raise HTTPException(
                status_code=400,
                detail="❗ PDF 벡터값이 로딩되지 않았습니다. 먼저 PDF 파일을 벡터화해주세요.",
            )
        # [Q03] 요청 출처와 검색 저장소 연결
        # [설계 판단] 사용자가 source="pdf"를 선택하면 웹 저장소가 아니라 PDF 저장소를 검색하도록 연결하세요.
        # [TODO Q03] 아래 ... 부분을 적절한 코드로 교체하세요.
        vectorstore = VECTORSTORE_PDF
        llm = ChatOpenAI(model="gpt-4o", temperature=0.3)
        llm_type = "openai"

        # 없는 공고번호 · 차수로 검색하면 "문서에 답이 없음"과 구분되지 않으므로 오류로 알린다
        revision = resolve_revision(rag_request.bid_no, rag_request.revision) if rag_request.bid_no else None

    else:
        raise HTTPException(
            status_code=400,
            detail="❗ 외부 source는 'web', 'pdf' 중 하나여야 합니다.",
        )

    # 2. 검색 및 LLM 응답 생성
    try:
        source = rag_request.source
        top_k = max(5, (rag_request.top_k or 5))

        # -------------------- PDF: 검색 결과 확인 + 안정적인 응답 처리 --------------------
        if source == "pdf":
            # [Q04] 질문과 유사 문서 검색 연결
            # [설계 판단] 사용자 질문을 기준으로 선택된 벡터 저장소에서 상위 top_k개 문서와 거리 점수를 가져오세요.
            # [TODO Q04] 아래 ... 부분을 적절한 코드로 교체하세요.
            # bid_no를 주면 그 공고 · 차수의 청크만 검색. 공고 20건이 섞여 있으므로 전체를 후보로 본 뒤 필터해야
            # 다른 공고 조각에 밀려 해당 공고 결과가 k개보다 적게 나오는 일이 없다 (2,849청크 규모라 부담 없음)
            search_kwargs = ({"filter": {"bid_no": rag_request.bid_no, "revision": revision},
                              "fetch_k": vectorstore.index.ntotal} if rag_request.bid_no else {})
            docs_scores = vectorstore.similarity_search_with_score(rag_request.prompt, k=top_k, **search_kwargs)
            print(f"[PDF 검색] 질문={rag_request.prompt!r}, 검색 문서 수={len(docs_scores)}")
            for i, (doc, score) in enumerate(docs_scores, start=1):
                print(f"[PDF 검색 {i}] 거리={score:.5f}, 출처={source_label(doc.metadata)}, 내용={doc.page_content[:300]!r}")

            # 의미 검색이 놓친, 질문 단어가 그대로 든 조각을 최대 3개 덧붙인다 (LLM 호출 수는 그대로)
            seen = {(d.metadata.get("source"), d.metadata.get("page"), d.page_content) for d, _ in docs_scores}
            for d in keyword_chunks(vectorstore, rag_request.prompt, rag_request.bid_no, revision, seen):
                docs_scores.append((d, float("nan")))
                print(f"[키워드 보강] 출처={source_label(d.metadata)}, 내용={d.page_content[:120]!r}")

            if not docs_scores:
                return not_found("PDF 지식베이스에서 검색 결과를 찾을 수 없습니다.")

            # 임의의 거리 임계값을 제거하고 상위 검색 결과를 사용합니다.
            # 기존 로직은 0.12 마진으로 문서를 과도하게 배제할 수 있었습니다.
            MAX_CONTEXT_CHARS = 12000
            chunks, sources, total = [], [], 0
            doc_labels = {}  # 프롬프트의 [문서 i] 번호 → 출처
            for i, (doc, _) in enumerate(docs_scores, start=1):
                content = join_spaced_letters((doc.page_content or "").strip())
                if not content:
                    continue
                remaining = MAX_CONTEXT_CHARS - total
                if remaining <= 0:
                    break
                excerpt = content[:remaining]
                label = source_label(doc.metadata)
                chunks.append(f"[문서 {i} | {label}]\n{excerpt}")
                doc_labels[i] = label
                if label not in sources:
                    sources.append(label)
                total += len(excerpt)
            context = "\n\n".join(chunks)
            if not context.strip():
                return not_found("PDF에서 검색된 텍스트가 비어 있습니다.")

            full_prompt = (
                "아래는 업로드된 PDF에서 검색한 내용입니다. PDF 내용에 근거해 한국어로 답변하세요. "
                "질문이 한 단어 또는 주제명이라면 그 주제를 PDF에 근거해 설명하세요. "
                "PDF에 없는 사실을 만들어 내지 마세요.\n"
                "날짜 · 시각 · 금액 · 배점은 PDF에 적힌 그대로 옮기고 계산하거나 바꾸지 마세요.\n"
                "PDF에 직접 적혀 있지 않은 내용을 일반 상식이나 법령 해석으로 추론하지 말고, "
                "'~일 것입니다', '~로 해석될 수 있습니다' 같은 추측을 덧붙이지 마세요.\n\n"
                f"PDF 검색 내용:\n{context}\n\n"
                f"질문: {rag_request.prompt}"
            )
            # [Q05] 검색 근거를 LLM 답변으로 연결
            # [설계 판단] 검색한 PDF 내용이 포함된 full_prompt를 LLM에 전달하여 응답을 받아오세요.
            # [TODO Q05] 아래 ... 부분을 적절한 코드로 교체하세요.
            # 답 · 근거 유무 · 인용 번호를 정해진 칸으로 받는다 (문장 속 표시를 해석하지 않음)
            result = llm.with_structured_output(RagAnswer, method="function_calling").invoke(
                [HumanMessage(content=full_prompt)])
            print(f"[PDF LLM 응답] found={result.found} cited={result.cited} answer={result.answer[:1500]}")
            final = strip_doc_refs(result.answer or "")
            if not result.found:
                final = drop_speculation(final)
            if not final:
                return not_found("PDF 지식베이스에서 답을 찾을 수 없습니다. 공고 담당 기관에 문의하거나 질문을 구체적으로 작성해 보세요.")
            cited = []
            for n in result.cited:
                if (label := doc_labels.get(n)) and label not in cited:
                    cited.append(label)
            # 답을 찾지 못했으면 관련 사실만 보여 주고 담당자에게 넘긴다.
            # 이때 인용이 없으면 출처도 비운다 (검색된 조각 전체를 출처로 붙이면 근거가 있는 것처럼 보임)
            if not cited and result.found:
                cited = sources
            return AnswerResponse(prompt=rag_request.prompt, response=final, sources=cited,
                                  needs_review=review or not result.found, handoff=not result.found,
                                  latency_ms=elapsed_ms(t0))

        # -------------------- WEB 검색 --------------------
        elif source == "web":
            q = rag_request.prompt or ""
            # 한글 포함 여부 간단 판별
            has_korean = any('\uac00' <= ch <= '\ud7a3' for ch in q)
            merged = []

            def limited_context(docs, limit_chars=4000):
                buf, used, total = [], [], 0
                for d in docs:
                    pc = getattr(d, "page_content", "") or ""
                    if not pc.strip():
                        continue
                    if total + len(pc) > limit_chars:
                        break
                    buf.append(pc); total += len(pc)
                    label = source_label(d.metadata)
                    if label not in used:
                        used.append(label)
                return "\n\n".join(buf), used

            # 1차: 원문 질의
            docs1 = vectorstore.similarity_search(q, k=top_k)
            merged.extend(docs1)

            # 2차: 한국어 → 영어 번역 질의(실 서비스에서는 번역 API 사용 권장)
            q_en = q
            try:
                if has_korean:
                    q_en = q  # TODO: 실제 번역 적용
                    docs2 = vectorstore.similarity_search(q_en, k=top_k)
                    merged.extend(docs2)
            except Exception:
                pass  # 번역/검색 실패 시 무시

            # 중복 제거(간단히 page_content 기준)
            seen, merged_uniq = set(), []
            for d in merged:
                key = getattr(d, "page_content", "")
                if key and key not in seen:
                    seen.add(key); merged_uniq.append(d)

            if not merged_uniq:
                return not_found("웹 검색 기반 지식베이스에서 충분한 결과를 찾지 못했습니다. 키워드를 달리하여 다시 시도해 주십시오.")

            context, sources = limited_context(merged_uniq, limit_chars=4000)
            if not context.strip():
                return not_found("웹 검색 기반 지식베이스에서 충분한 결과를 찾지 못했습니다. 키워드를 달리하여 다시 시도해 주십시오.")

            # 인용 유도, N/A 강제는 사용하지 않음
            full_prompt = (
                "아래 컨텍스트에서만 답변을 작성하시오. 컨텍스트에 없는 내용은 추측하지 마시오. "
                "가능하면 문장 끝에 간단한 출처 표기를 괄호로 덧붙이시오(예: (출처 1), (출처 2)).\n"
                f"{context}\n\n"
                f"질문: {rag_request.prompt}\n\n"
                "### ANSWER_START\n"
                "<정답(간결한 한국어, 필요 시 간단한 출처 표기)>\n"
                "### ANSWER_END"
            )

            if llm_type == "huggingface": # Embedding 시, bge_embedder 사용한 경우에 선택 권고
                out = text_generator(full_prompt, max_new_tokens=200, do_sample=False, return_full_text=False) #  temperature=0.0 제거
                raw = (out[0].get("generated_text") or "").strip()
                answer = extract_by_marker(raw)
                if not answer and 0 < len(raw) <= 500 and '###' not in raw:
                    answer = raw
            else:
                raw = llm.invoke([HumanMessage(content=full_prompt)]).content.strip()
                answer = extract_by_marker(raw) or raw

            final = (answer or "").strip()
            if final == "":
                return not_found("웹 검색 기반 지식베이스에서 충분한 결과를 찾지 못했습니다. 키워드를 달리하여 다시 시도해 주십시오.")
            return AnswerResponse(prompt=rag_request.prompt, response=final, sources=sources,
                                  needs_review=review, latency_ms=elapsed_ms(t0))

        # -------------------- 기타 --------------------
        else:
            return AnswerResponse(prompt=rag_request.prompt, response="지원하지 않는 소스입니다.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================================
# ✅ 공고별 구조화 추출 (채점표 · 제출서류 · 일정 · 요약)
#    3번(점수 · 체크리스트)과 5번(화면)이 쓰는 JSON을 만든다.
#    검색 순위에 기대면 정답 조각이 빠질 수 있으므로, 해당 공고에서 키워드가 많이 나온 쪽부터
#    통째로 모아 LLM에 넘기고 LLM은 표를 옮겨 적기만 한다(점수 계산은 3번 코드가 담당).
# =====================================================================
from typing import Literal
from bid_logic.common import calendar_date
from bid_logic.scoring import _validate_bands

def bid_chunks(bid_no: str, revision: str, keywords: tuple[str, ...] | None = None) -> list[Document]:
    docs = [(i, d) for i, d in enumerate(VECTORSTORE_PDF.docstore._dict.values())
            if (d.metadata.get("bid_no"), d.metadata.get("revision")) == (bid_no, revision)]
    if not keywords:
        docs.sort(key=lambda x: (x[1].metadata["page"], x[1].metadata["source"], x[0]))
        return [d for _, d in docs]
    # 실제 제안요청서는 100쪽이 넘어 "평가" 같은 단어가 여러 쪽에 나온다. 키워드가 많이 나온 쪽부터 담아
    # 글자 수 한도에 걸려도 표가 있는 쪽이 먼저 들어가게 하고, 표가 이어질 수 있는 다음 쪽을 바로 뒤에 붙인다
    score: dict[tuple, int] = {}
    for _, d in docs:
        key = (d.metadata["source"], d.metadata["page"])
        score[key] = score.get(key, 0) + sum(d.page_content.count(k) for k in keywords)
    order: list[tuple] = []
    for key in sorted((k for k, v in score.items() if v), key=lambda k: (-score[k], k[1])):
        for page_key in (key, (key[0], key[1] + 1)):
            if page_key in score and page_key not in order:
                order.append(page_key)
    rank = {k: n for n, k in enumerate(order)}
    picked = [(i, d) for i, d in docs if (d.metadata["source"], d.metadata["page"]) in rank]
    picked.sort(key=lambda x: (rank[(x[1].metadata["source"], x[1].metadata["page"])], x[0]))
    return [d for _, d in picked]

def numbered_context(docs: list[Document], limit_chars: int = 24000):
    parts, labels, texts, refs, total = [], {}, {}, {}, 0
    for i, d in enumerate(docs, start=1):
        if total + len(d.page_content) > limit_chars:
            break
        labels[i], texts[i], refs[i] = source_label(d.metadata), d.page_content, source_ref(d.metadata)
        parts.append(f"[문서 {i} | {labels[i]}]\n{join_spaced_letters(d.page_content)}")
        total += len(d.page_content)
    return "\n\n".join(parts), labels, texts, refs

def _squash(s: str) -> str:
    return re.sub(r"[\s()·,]", "", s)

def verified_source(name: str, doc_no: int | None, texts: dict[int, str],
                    siblings: list[str] | None = None) -> tuple[int | None, bool]:
    # LLM이 고른 [문서 n]을 그대로 믿지 않는다: 이름이 실제로 들어 있는 조각만 후보로 두고
    # (줄바꿈 · 띄어쓰기 · 괄호 차이는 무시), "제안서"처럼 짧은 이름이 일정표 등에도 나오는 경우를 막기 위해
    # 함께 추출된 이름(siblings)을 가장 많이 담은 조각, 즉 목록 표가 있는 조각을 우선한다
    key = _squash(name)
    candidates = [n for n, text in texts.items() if key and key in _squash(text)]
    if not candidates:
        # LLM이 "(서식 2)" 같은 부분을 빼고 옮기면 통째 비교는 실패한다. 이름의 낱말(2자 이상)이 모두 든 조각을 찾는다
        words = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", name)]
        candidates = [n for n, text in texts.items() if words and all(w in _squash(text) for w in words)]
    if not candidates:
        return doc_no, False
    if siblings:
        keys = [_squash(s) for s in siblings]
        def score(n):
            return sum(k in _squash(texts[n]) for k in keys)
        best = max(score(n) for n in candidates)
        candidates = [n for n in candidates if score(n) == best]
    return (doc_no if doc_no in candidates else candidates[0]), True

def run_extraction(schema, instruction: str, context: str):
    llm = ChatOpenAI(model="gpt-4o", temperature=0).with_structured_output(schema, method="function_calling")
    return llm.invoke([HumanMessage(content=f"{instruction}\n\n{context}")])

def cached(bid_no: str, revision: str, kind: str, refresh: bool, build) -> dict:
    key = (bid_no, revision, kind)
    fingerprint = BID_FINGERPRINTS.get((bid_no, revision))
    entry = EXTRACT_CACHE.get(key)
    # 그 공고의 문서가 바뀌었을 때만 다시 추출 (다른 공고 적재로는 지워지지 않음)
    if refresh or entry is None or entry["fingerprint"] != fingerprint:
        entry = EXTRACT_CACHE[key] = {"fingerprint": fingerprint, "data": build()}
    return entry["data"]

def bid_documents(bid_no: str, revision: str) -> dict:
    """그 공고에 적재된 파일과 종류. 공고문만 적재(흐름 ③)인지, 제안요청서까지 적재(흐름 ⑥)인지 판단한다."""
    files = sorted({d.metadata.get("filename", "") for d in VECTORSTORE_PDF.docstore._dict.values()
                    if (d.metadata.get("bid_no"), d.metadata.get("revision")) == (bid_no, revision)})
    typed = [{"filename": f, "kinds": sorted(classify_attachment(f))} for f in files]
    kinds = {k for t in typed for k in t["kinds"]}
    return {"bid_no": bid_no, "revision": revision, "files": typed,
            "has_notice": "notice" in kinds, "has_rfp": "rfp" in kinds,
            "stage": "full" if "rfp" in kinds else ("notice_only" if files else "none")}

def require_rfp(bid_no: str, revision: str, partial_hint: bool = True):
    # 채점표는 대부분 제안요청서에 있다. 공고문만으로 추출하면 "기술 90 : 가격 10" 비율만 나와 빈 채점표가 되므로 막는다
    if not bid_documents(bid_no, revision)["has_rfp"]:
        hint = " (공고문만으로 추출하려면 allow_partial=true)" if partial_hint else ""
        raise HTTPException(status_code=409, detail="제안요청서가 아직 적재되지 않았습니다. 이 공고를 선택해 나머지 첨부를 "
                                                    f"적재한 뒤 다시 요청하세요.{hint}")

def run_endpoint(bid_no: str, revision: str | None, kind: str, refresh: bool, builder, needs_rfp: bool = False) -> dict:
    revision = resolve_revision(bid_no, revision)
    if needs_rfp:
        require_rfp(bid_no, revision)
    try:
        return cached(bid_no, revision, kind, refresh, lambda: builder(bid_no, revision))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

EXTRACT_RULES = (
    "규칙: 문서에 적힌 내용만 원문 그대로 옮기고, 없는 항목을 만들거나 숫자를 계산 · 변경하지 마세요. "
    "각 항목에는 그 내용이 적힌 [문서 n]의 번호를 doc_no로 넣으세요."
)

# ---- 채점표 ----
class ScoringItem(BaseModel):
    category: str = Field(description="평가 구분 (예: 기술능력평가, 입찰가격평가)")
    section: str = Field(description="평가부문, 원문 그대로 (예: 웹툰 산업 및 서비스 이해). 부문이 없으면 category와 같게")
    item: str = Field(description="평가 항목명, 원문 그대로")
    max_score: float = Field(description="배점, 원문 숫자 그대로")
    criteria: str = Field(description="평가 기준 · 산식, 없으면 빈 문자열")
    eval_type: Literal["정량", "정성", "가격"] = Field(
        description="정량: 실적 · 인력 · 인증 · 신용등급처럼 제출 서류로 점수를 계산할 수 있음, 정성: 평가위원이 판단, 가격: 입찰가격 산식")
    doc_no: int = Field(description="이 항목이 적힌 [문서 n]의 번호")

class ScoringExtraction(BaseModel):
    items: List[ScoringItem]
    declared_total: Optional[float] = Field(default=None, description="문서에 적힌 전체 배점 합계(예: 기술 90 + 가격 10 = 100). 없으면 null")
    pass_rule: str = Field(default="", description="협상적격자 · 적격 통과 기준 원문 (예: 기술능력평가 배점한도의 85% 이상). 없으면 빈 문자열")
    pass_rule_doc_no: Optional[int] = Field(default=None, description="통과 기준이 적힌 [문서 n]의 번호")

# 정량 항목의 계산 규칙: 3번 scoring.py가 계산할 수 있는 형식(구간표 · 등급표)으로만 옮긴다
class Band(BaseModel):
    min: Optional[float] = Field(default=None, description="구간 하한, 없으면 null")
    max: Optional[float] = Field(default=None, description="구간 상한, 없으면 null")
    min_inclusive: bool = Field(default=True, description="하한 포함(이상)이면 true, 초과면 false")
    max_inclusive: bool = Field(default=False, description="상한 포함(이하)이면 true, 미만이면 false")
    score: float

class CategoryScore(BaseModel):
    value: str = Field(description="등급 표기 원문 그대로 (예: AAA, A+)")
    score: float

class QuantRule(BaseModel):
    explicit: bool = Field(description="이 항목의 점수 산정표(구간표 또는 등급표)가 숫자로 원문에 명시되어 있으면 true, 아니면 false")
    metric_field: Literal["credit_rating", "track_records", "none"] = Field(
        description="신용등급 등급표면 credit_rating, 수행 실적 건수 · 금액 구간표면 track_records, 그 외 none")
    aggregate: Literal["count", "sum", "none"] = Field(description="실적이면 건수(count) 또는 금액 합계(sum)")
    unit: Literal["KRW", "천원", "백만원", "억원", "none"] = Field(description="금액 구간의 단위")
    period_from: str = Field(description="실적 인정 시작일 YYYY-MM-DD. 원문에 절대 날짜로 적혀 있을 때만, 아니면 빈 문자열")
    period_to: str = Field(description="실적 인정 종료일 YYYY-MM-DD. 원문에 절대 날짜로 적혀 있을 때만, 아니면 빈 문자열")
    rule_type: Literal["bands", "category", "none"]
    bands: List[Band] = Field(default_factory=list)
    categories: List[CategoryScore] = Field(default_factory=list)

def build_rule(q: QuantRule, maximum: float) -> tuple[dict | None, str]:
    """LLM이 옮긴 규칙을 3번 형식으로 바꾸고, 3번 계산기가 거부할 규칙은 미리 걸러 '담당자 판단'으로 둔다."""
    if not q.explicit or q.rule_type == "none" or q.metric_field == "none":
        return None, "원문에 계산 가능한 산정표가 명시되지 않음"
    try:
        if q.metric_field == "credit_rating" and q.rule_type == "category" and q.categories:
            values = {c.value: c.score for c in q.categories}
            if any(not 0 <= v <= maximum for v in values.values()):
                return None, "등급표 점수가 배점 범위를 벗어남"
            return {"metric": {"field": "credit_rating"}, "rule": {"type": "category", "values": values}}, ""
        if q.metric_field == "track_records" and q.rule_type == "bands" and q.bands and q.aggregate != "none":
            if not (q.period_from and q.period_to):
                return None, "실적 인정 기간이 절대 날짜로 명시되지 않음 (상대 기간은 추정하지 않음)"
            calendar_date(q.period_from)  # 형식이 틀리면 ValueError
            calendar_date(q.period_to)
            bands = [b.model_dump() for b in q.bands]
            _validate_bands(bands, maximum)
            metric = {"field": "track_records", "aggregate": q.aggregate, "from": q.period_from, "to": q.period_to}
            if q.aggregate == "sum":
                if q.unit == "none":
                    return None, "금액 구간의 단위가 명시되지 않음"
                metric["unit"] = q.unit
            return {"metric": metric, "rule": {"type": "bands", "bands": bands}}, ""
    except (ValueError, KeyError, TypeError) as e:
        return None, f"산정표 형식 검증 실패: {e}"
    return None, "지원하지 않는 산정 방식"

SCORING_KEYWORDS = ("배점", "평가항목", "평가 항목", "기술능력평가", "입찰가격평가", "합 계", "합계")

def build_scoring(bid_no: str, revision: str) -> dict:
    t0 = time.perf_counter()
    docs = bid_chunks(bid_no, revision, SCORING_KEYWORDS)
    if not docs:
        return {"bid_no": bid_no, "revision": revision, "items": [], "needs_review": True, "handoff": True,
                "message": "채점표를 찾지 못했습니다. 제안요청서가 적재되었는지 확인하세요."}
    context, labels, texts, refs = numbered_context(docs)
    result = run_extraction(ScoringExtraction,
        "아래는 한 공고의 공고문 · 제안요청서 일부입니다. 제안서 평가 채점표의 평가 항목과 배점을 빠짐없이 옮기세요. "
        "세부 항목이 있으면 세부 항목 단위로 넣고, 소계 · 합계 행은 items에 넣지 마세요. 입찰가격평가도 하나의 항목으로 넣으세요. "
        "협상적격자 · 적격 통과 기준이 적혀 있으면 pass_rule에 원문 그대로 넣으세요. "
        + EXTRACT_RULES, context)
    items = []
    for it in result.items:
        n, ok = verified_source(it.item, it.doc_no, texts)
        row = {**it.model_dump(exclude={"doc_no"}), "source": labels.get(n or 0, "unknown"),
               "source_refs": [refs[n]] if ok and n in refs else [], "source_verified": ok,
               "rule": None, "rule_note": ""}
        if it.eval_type == "정량":
            q = run_extraction(QuantRule,
                f"아래 문서에서 평가 항목 '{it.item}'(배점 {it.max_score})의 점수 산정표를 찾아 옮기세요. "
                "원문에 숫자로 된 구간표나 등급표가 없으면 explicit을 false로 하고, 추정하거나 계산하지 마세요.", context)
            row["rule"], row["rule_note"] = build_rule(q, it.max_score)
        items.append(row)
    total = round(sum(it["max_score"] for it in items), 2)
    # 옮겨 적은 배점의 합이 문서의 합계와 다르면 누락 · 중복이 있다는 뜻이므로 표시
    consistent = result.declared_total is None or abs(total - result.declared_total) < 0.01
    return {"bid_no": bid_no, "revision": revision, "items": items, "total_max_score": total,
            "declared_total": result.declared_total, "consistent": consistent,
            "pass_rule": result.pass_rule, "pass_rule_source": labels.get(result.pass_rule_doc_no or 0, ""),
            "needs_review": True, "handoff": False, "latency_ms": elapsed_ms(t0)}

@app.get("/bids/{bid_no}/scoring-table", dependencies=AUTH, summary="공고 채점표 추출 (3번 점수 계산용)", tags=["공고 추출"])
async def scoring_table(bid_no: str, revision: Optional[str] = Query(None, description="공고 차수"),
                        refresh: bool = Query(False, description="true면 저장된 결과를 무시하고 다시 추출"),
                        allow_partial: bool = Query(False, description="true면 제안요청서 없이 공고문만으로 추출 (채점표가 비거나 불완전할 수 있음)")):
    return run_endpoint(bid_no, revision, "scoring", refresh, build_scoring, needs_rfp=not allow_partial)

# ---- 제출서류 · 일정 ----
class RequiredDoc(BaseModel):
    doc_name: str = Field(description="서류명, 원문 그대로")
    note: str = Field(description="비고 · 형식 · 서식 번호, 없으면 빈 문자열")
    mandatory: bool = Field(description="필수 제출이면 true, '해당 시' 등 조건부면 false")
    doc_no: int = Field(description="이 서류가 적힌 [문서 n]의 번호")

class ScheduleEvent(BaseModel):
    event: str = Field(description="일정 이름, 원문 그대로 (예: 제안서 제출, 개찰, 입찰참가자격 등록 마감)")
    when: str = Field(description="일시, 원문 그대로 (기간이면 시작~끝 모두)")
    doc_no: int = Field(description="이 일정이 적힌 [문서 n]의 번호")

class RequiredDocsExtraction(BaseModel):
    docs: List[RequiredDoc]
    due: str = Field(description="제출 기한, 원문 그대로. 없으면 빈 문자열")
    method: str = Field(description="제출 방법, 원문 그대로. 없으면 빈 문자열")
    due_doc_no: Optional[int] = Field(default=None, description="제출 기한이 적힌 [문서 n]의 번호")
    schedule: List[ScheduleEvent] = Field(default_factory=list, description="입찰 일정표의 일정들 (공고 · 제출 · 등록 마감 · 개찰 · 평가 · 협상 등)")

REQUIRED_DOCS_KEYWORDS = ("제출 서류", "제출서류", "서류명", "제출 기한", "제출기한", "제출 방법", "개찰", "일시", "일정")

def build_required_docs(bid_no: str, revision: str) -> dict:
    t0 = time.perf_counter()
    docs = bid_chunks(bid_no, revision, REQUIRED_DOCS_KEYWORDS)
    if not docs:
        return {"bid_no": bid_no, "revision": revision, "docs": [], "schedule": [], "needs_review": True,
                "handoff": True, "message": "제출서류 목록을 찾지 못했습니다."}
    context, labels, texts, refs = numbered_context(docs)
    result = run_extraction(RequiredDocsExtraction,
        "아래는 한 공고의 공고문 · 제안요청서 일부입니다. 입찰 시 제출해야 하는 서류 목록과 제출 기한 · 방법, "
        "그리고 입찰 일정표의 일정을 옮기세요. 공고문과 제안요청서에 같은 서류 · 일정이 중복으로 나오면 한 번만 넣되, "
        "두 문서의 비고를 빠짐없이 합쳐 note에 적고 doc_no는 목록 표가 더 자세한 쪽의 번호로 하세요. " + EXTRACT_RULES, context)
    names = [d.doc_name for d in result.docs]
    out_docs = []
    for d in result.docs:
        n, ok = verified_source(d.doc_name, d.doc_no, texts, siblings=names)
        out_docs.append({**d.model_dump(exclude={"doc_no"}), "source": labels.get(n or 0, "unknown"),
                         "source_refs": [refs[n]] if ok and n in refs else [], "source_verified": ok})
    events = [e.event for e in result.schedule]
    schedule = []
    for e in result.schedule:
        n, ok = verified_source(e.event, e.doc_no, texts, siblings=events)
        schedule.append({"event": e.event, "when": e.when, "due_iso": to_iso_due(e.when),
                         "source": labels.get(n or 0, "unknown"),
                         "source_refs": [refs[n]] if ok and n in refs else [], "source_verified": ok})
    due_n, _ = verified_source(result.due, result.due_doc_no, texts) if result.due else (None, False)
    return {"bid_no": bid_no, "revision": revision, "docs": out_docs,
            "due": result.due, "due_iso": to_iso_due(result.due), "method": result.method,
            "due_source": labels.get(due_n or 0, ""), "schedule": schedule,
            "needs_review": False, "handoff": False, "latency_ms": elapsed_ms(t0)}

@app.get("/bids/{bid_no}/required-docs", dependencies=AUTH, summary="공고 제출서류 · 일정 추출 (3번 체크리스트용)", tags=["공고 추출"])
async def required_docs(bid_no: str, revision: Optional[str] = Query(None, description="공고 차수"),
                        refresh: bool = Query(False, description="true면 저장된 결과를 무시하고 다시 추출")):
    return run_endpoint(bid_no, revision, "required_docs", refresh, build_required_docs)

# ---- 공고 요약 ----
class SummaryField(BaseModel):
    value: str = Field(description="원문 근거 값. 문서에 없으면 빈 문자열")
    doc_no: Optional[int] = Field(default=None, description="근거가 적힌 [문서 n]의 번호, 없으면 null")

class BidSummary(BaseModel):
    title: SummaryField = Field(description="사업명")
    agency: SummaryField = Field(description="발주기관")
    period: SummaryField = Field(description="사업(용역) 기간")
    budget: SummaryField = Field(description="사업예산 · 추정가격 (부가세 포함 여부 포함)")
    contract_method: SummaryField = Field(description="계약방법")
    evaluation_ratio: SummaryField = Field(description="평가 비율 (기술 : 가격)")
    eligibility: SummaryField = Field(description="입찰 참가자격 요약")
    joint_and_subcontract: SummaryField = Field(description="공동수급 · 하도급 허용 여부")
    schedule: SummaryField = Field(description="주요 일정 (제출 기간, 개찰, 평가, 협상)")
    main_tasks: SummaryField = Field(description="주요 과업")

def build_summary(bid_no: str, revision: str) -> dict:
    t0 = time.perf_counter()
    context, labels, _, refs = numbered_context(bid_chunks(bid_no, revision))  # 앞쪽부터 담아 공고 개요가 먼저 들어가게 한다
    result = run_extraction(BidSummary,
        "아래는 한 공고의 공고문 · 제안요청서입니다. 각 항목을 1~3문장으로 요약하세요. " + EXTRACT_RULES, context)
    fields = {name: {"value": f.value, "source": labels.get(f.doc_no or 0, ""),
                     "source_refs": [refs[f.doc_no]] if f.doc_no in refs else []}
              for name, f in result}
    missing = [name for name, f in fields.items() if not f["value"]]
    return {"bid_no": bid_no, "revision": revision, "summary": fields, "missing": missing,
            "needs_review": False, "handoff": bool(missing), "latency_ms": elapsed_ms(t0)}

@app.get("/bids/{bid_no}/summary", dependencies=AUTH, summary="공고 요약 (항목별 출처 포함)", tags=["공고 추출"])
async def bid_summary(bid_no: str, revision: Optional[str] = Query(None, description="공고 차수"),
                      refresh: bool = Query(False, description="true면 저장된 결과를 무시하고 다시 추출")):
    return run_endpoint(bid_no, revision, "summary", refresh, build_summary)

# ---- 흐름 ③ · ⑥ 진행 확인: 공고별로 무엇이 적재되었는지 ----
@app.get("/bids/{bid_no}/documents", dependencies=AUTH, summary="공고별 적재 문서 · 단계 (none / notice_only / full)", tags=["공고 추출"])
async def bid_documents_status(bid_no: str, revision: Optional[str] = Query(None, description="공고 차수")):
    return bid_documents(bid_no, resolve_revision(bid_no, revision))

# ---- 흐름 ④: 추린 공고 20건을 한 번에 요약 ----
class BidKey(BaseModel):
    bid_no: str
    revision: Optional[str] = None

class SummaryBatchRequest(BaseModel):
    bids: List[BidKey] = Field(min_length=1, max_length=20, description="요약할 공고 (최대 20건)")
    refresh: bool = False

@app.post("/bids/summaries", dependencies=AUTH, summary="공고 여러 건 요약 (흐름 ④, 최대 20건 · 동시 5건)", tags=["공고 추출"])
def bid_summaries(req: SummaryBatchRequest):
    # LLM 호출을 공고마다 순서대로 하면 20건에 1분 이상 걸려 5건씩 동시에 처리한다. 한 건이 실패해도 나머지는 돌려준다
    from concurrent.futures import ThreadPoolExecutor
    t0 = time.perf_counter()

    def one(key: BidKey) -> dict:
        try:
            revision = resolve_revision(key.bid_no, key.revision)
            data = cached(key.bid_no, revision, "summary", req.refresh, lambda: build_summary(key.bid_no, revision))
            return {"status": "ok", **data, "documents": bid_documents(key.bid_no, revision)["stage"]}
        except HTTPException as e:
            return {"bid_no": key.bid_no, "revision": key.revision, "status": "error", "code": e.status_code, "detail": e.detail}
        except Exception as e:
            return {"bid_no": key.bid_no, "revision": key.revision, "status": "error", "code": 500, "detail": str(e)}

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(one, req.bids))
    return {"results": results, "ok": sum(r["status"] == "ok" for r in results),
            "failed": sum(r["status"] != "ok" for r in results), "latency_ms": elapsed_ms(t0)}

# =====================================================================
# ✅ 3번(공고 로직) 공급 함수: (bid_no, revision) → 3번 입력 형식. 없거나 추출 실패면 None(3번이 404 처리)
# =====================================================================
def get_extracted_scoring_table(bid_no: str, revision: str) -> dict | None:
    if (bid_no, revision) not in stored_bids(VECTORSTORE_PDF):
        return None
    require_rfp(bid_no, revision, partial_hint=False)  # 409: 3번 라우터는 HTTPException을 그대로 전달한다 (흐름 ⑥ 전에는 점수 불가)
    data = cached(bid_no, revision, "scoring", False, lambda: build_scoring(bid_no, revision))
    table = to_bid_logic_scoring(data, bid_no, revision)
    return table if table["items"] else None  # 출처가 확인된 항목이 하나도 없으면 404 (빈 점수표를 내지 않음)

def get_extracted_checklist(bid_no: str, revision: str) -> dict | None:
    if (bid_no, revision) not in stored_bids(VECTORSTORE_PDF):
        return None
    data = cached(bid_no, revision, "required_docs", False, lambda: build_required_docs(bid_no, revision))
    # 3번 공급 경계에서 원문과 대조한다. 2번의 추출 모델/캐시는 변경하지 않는다.
    from bid_logic.checklist_quality import reconcile_required_docs
    evidence = bid_chunks(bid_no, revision)
    texts = {i: doc.page_content for i, doc in enumerate(evidence, 1)}
    refs = {i: source_ref(doc.metadata) for i, doc in enumerate(evidence, 1)}
    labels = {i: source_label(doc.metadata) for i, doc in enumerate(evidence, 1)}
    data = reconcile_required_docs(data, texts, refs, labels)
    if not data.get("docs") and not data.get("schedule"):
        return None
    # 3번 원문 대조 뒤에도 출처가 없는 항목은 빠지므로, 남은 항목이 없으면 404 (빈 체크리스트를 내지 않음)
    payload = to_bid_logic_checklist(data, bid_no, revision)
    return payload if payload["documents"] or payload["schedule"] else None

def connect_bid_routes(profile_dependency, *, bids_provider=None, search_results_provider=None,
                       title_similarity=None, agent_model=None):
    """4번(JWT 검증 + 회사 프로필 조회)이 준비되면 서버 시작 전에 한 번 호출한다.
    GET /bids, /bids/{bid_no}/score, /bids/{bid_no}/checklist(3번)가 실제 데이터 · 추출 결과로 등록된다.
    search_results_provider(search_id, profile)는 저장된 ① 목록을 반환하고 사용자 접근을 검증한다.
    ②는 공고명 임베딩만 사용하고, POST /bids/recheck는 적재된 공고만 본문으로 재확인한다.
    bids_provider는 ③'용 정규화 메타데이터 공급자(기본: 변환된 data/bids.csv)다."""
    def pipeline_similarity(query, titles):
        from knowledge_bridge import PipelineEmbeddings
        from data_pipeline.knowledge import KnowledgeStore
        model = STORE_STATE.get("embedding_model") or KnowledgeStore("pdf").model
        return embedding_title_similarity(PipelineEmbeddings(model), query, titles)

    router = register_bid_routes(profile_dependency=profile_dependency,
                               scoring_provider=get_extracted_scoring_table,
                               checklist_provider=get_extracted_checklist,
                               bids_provider=bids_provider,
                               search_results_provider=search_results_provider,
                               title_similarity=title_similarity or pipeline_similarity,
                               agent_model=agent_model,
                               require_search_id=search_results_provider is not None,
                               loaded_keys_provider=lambda: stored_bids(VECTORSTORE_PDF))
    return router

# 4번 백엔드 주소가 있으면 토큰을 백엔드 /api/profile로 확인하는 의존성으로 바로 연결한다 (backend_auth.py)
from backend_auth import backend_url, get_authenticated_profile
from bid_logic.agent_config import configured_agent_model
if backend_url():
    # ③ 화면이 보내는 search_id로 1번 검색 결과를 3번 추리기에 넘긴다 (search_id 없는 /bids는 422)
    connect_bid_routes(get_authenticated_profile, search_results_provider=search_results,
                       agent_model=configured_agent_model())
    print(f"[공고 API 연결] /bids · /bids/{{bid_no}}/score · /bids/{{bid_no}}/checklist ← 프로필: {backend_url()}/api/profile")


# 실행 명령어 예시:
# python -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001 --reload
