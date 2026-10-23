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

# 현재 Python 파일과 같은 위치에 있는 .env 파일 로드
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

# ✅ 전역 벡터 저장소
VECTORSTORE_WEB = None
VECTORSTORE_PDF = None

# 벡터 스토어 전역 변수
VECTORSTORE_WEB = None
VECTORSTORE_PDF = None

# ✅ 외부 (웹검색, OpenAI 전용)
web_path = "faiss_db/web"
if os.path.exists(f"{web_path}/index.faiss") and os.path.exists(f"{web_path}/index.pkl"):
    VECTORSTORE_WEB = FAISS.load_local(
        web_path,
        embeddings=OpenAIEmbeddings(),
        allow_dangerous_deserialization=True
    )
    print("✅ VECTORSTORE_WEB 로드 완료")
else:
    print("❌ VECTORSTORE_WEB 벡터화된 파일이 없습니다.")

# ✅ PDF (업로드용, OpenAI 전용)
pdf_path = "faiss_db/pdf"
if os.path.exists(f"{pdf_path}/index.faiss") and os.path.exists(f"{pdf_path}/index.pkl"):
    VECTORSTORE_PDF = FAISS.load_local(
        pdf_path,
        embeddings=OpenAIEmbeddings(),  # ← 오타 수정
        allow_dangerous_deserialization=True
    )
    print("✅ VECTORSTORE_PDF 로드 완료")
else:
    print("❌ VECTORSTORE_PDF 벡터화된 파일이 없습니다.")

# ✅ PDF 텍스트 추출 (쪽 단위: 출처에 "파일명 p.쪽"을 남기기 위해)
def load_paper(file_path: str) -> list[tuple[int, str]]:
    reader = PdfReader(file_path)
    return [(i, text) for i, page in enumerate(reader.pages, start=1) if (text := page.extract_text())]

# ✅ 공고문 담당자 연락처 마스킹 (전화번호 · 이메일)
PHONE_RE = re.compile(r"\b0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

def mask_contacts(text: str) -> str:
    text = PHONE_RE.sub("[전화번호]", text)
    return EMAIL_RE.sub("[이메일]", text)

# ✅ 출처 표기: PDF는 "파일명 p.쪽", 웹은 "제목 | URL"
def source_label(meta: dict) -> str:
    src = meta.get("source", "unknown")
    if meta.get("page"):
        return f"{src} p.{meta['page']}"
    if meta.get("title"):
        return f"{meta['title']} | {src}"
    return src

# ✅ 업로드할 때마다 덮어쓰지 않고 기존 저장소에 누적
def add_to_store(store, docs):
    if store is None:
        return FAISS.from_documents(docs, OpenAIEmbeddings())
    store.add_documents(docs)
    return store

def stored_sources(store) -> set[str]:
    if store is None:
        return set()
    return {d.metadata.get("source", "unknown") for d in store.docstore._dict.values()}

def stored_bid_nos(store) -> set[str]:
    if store is None:
        return set()
    return {b for d in store.docstore._dict.values() if (b := d.metadata.get("bid_no"))}

# ✅ 자격 · 배점처럼 사람이 최종 확인해야 하는 질문
REVIEW_KEYWORDS = ("자격", "참가", "제한", "면허", "업종", "지역", "배점", "점수", "평가")

def needs_review_for(question: str) -> bool:
    return any(k in question for k in REVIEW_KEYWORDS)

# ✅ PDF 질의 응답 형식: 답을 찾았는지(found)와 인용 문서(cited)를 답변 문장과 따로 받는다.
#    문장 속 표시("[명시 없음]", "근거: 1, 3")에 기대면 표현이 조금만 달라져도 handoff · 출처가 틀어졌다.
class RagAnswer(BaseModel):
    found: bool = Field(description="질문이 묻는 내용의 답이 PDF에 직접 적혀 있으면 true. 관련 내용만 있고 질문의 답 자체가 없으면 false")
    answer: str = Field(description="한국어 답변. found가 false면 '문서에 명시되어 있지 않습니다.'로 시작하고 PDF에 적힌 관련 사실만 덧붙이며, "
                                    "그 사실로부터 '따라서 ~일 것입니다' 같은 결론이나 추정을 만들지 않는다")
    cited: List[int] = Field(description="답변의 근거로 사용한 [문서 n]의 번호 목록")

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

def keyword_chunks(store, question: str, bid_no: str | None, exclude: set, n: int = 3) -> list[Document]:
    terms = query_terms(question)
    scored = []
    for d in store.docstore._dict.values():
        if bid_no and d.metadata.get("bid_no") != bid_no:
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
        "bid_nos": sorted(stored_bid_nos(VECTORSTORE_PDF)),
        "web_chunks": count(VECTORSTORE_WEB),
    }

# ✅ 웹 검색 → 외부 정보 벡터화
@app.post("/upload-topic", summary="웹 검색 → 외부 정보 벡터화", tags=["외부 정보"])
async def upload_topic(topic: str = Query(..., description="검색할 주제")):
    try:
        import os, re, aiohttp
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_community.vectorstores import FAISS
        from langchain_openai import OpenAIEmbeddings

        # ---- 1) 네이버 뉴스 검색: headers/params 전달 + 페이지네이션 ----
        NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
        NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

        search_url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        }

        want = 20          # 수집 목표 건수
        display = 20       # 요청 건수(최대 100 가능, 요금/정책 고려)
        start = 1
        items = []

        async with aiohttp.ClientSession() as session:
            while len(items) < want:
                params = {
                    "query": topic,
                    "display": display,
                    "start": start,     # 1, 21, 41 … (display에 맞춰 증가)
                    "sort": "date",
                }
                async with session.get(search_url, headers=headers, params=params) as resp:
                    # 상태 코드 확인 (401/429 등 조기 감지)
                    resp.raise_for_status()
                    data = await resp.json()

                batch = data.get("items", [])
                if not batch:
                    break

                # 네이버는 <b>…</b> 태그를 포함 → 제거
                def strip_tags(s: str) -> str:
                    return re.sub(r"</?b>", "", s or "")

                for it in batch:
                    it["title"] = strip_tags(it.get("title", ""))
                    it["description"] = strip_tags(it.get("description", ""))
                items.extend(batch)

                start += display
                if start > 1000:  # API 한계 보호
                    break

        if not items:
            return {"message": "검색 결과가 없습니다.", "collected": 0}

        # ---- 2) 텍스트 구성(제목+요약 위주) ----
        texts = [
            f"title: {it.get('title','')}\nlink: {it.get('link','')}\ndesc: {it.get('description','')}"
            for it in items
        ]
        # 너무 긴 텍스트는 잘라서 임베딩 안정화
        texts = [t[:3000] for t in texts]
        collected_at = datetime.now(UTC).strftime("%Y-%m-%d")
        metadatas = [{"source": it.get("link", ""), "title": it.get("title", ""),
                      "topic": topic, "collected_at": collected_at} for it in items]

        # ---- 3) 텍스트 분할 ----
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)
        docs = splitter.create_documents(texts, metadatas=metadatas)

        if not docs:
            return {"message": "벡터화할 문서가 없습니다.", "collected": len(items)}

        # ---- 4) 벡터화 (키워드 3~5개를 차례로 넣으므로 누적) ----
        global VECTORSTORE_WEB
        VECTORSTORE_WEB = add_to_store(VECTORSTORE_WEB, docs)

        # ---- 5) 디스크 저장 ----
        save_path = "faiss_db/web"
        os.makedirs(save_path, exist_ok=True)
        VECTORSTORE_WEB.save_local(save_path)

        return {
            "message": f"{len(docs)}개의 웹 문서(청크) 벡터화 및 저장 완료",
            "collected": len(items),
            "sample_titles": [it.get("title", "") for it in items[:3]],
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ✅ PDF 업로드 및 벡터화
@app.post("/upload-paper", summary="PDF 업로드 및 벡터화", tags=["PDF 처리"]) 
async def upload_pdf(file: UploadFile = File(...),
                     bid_no: str = Form(default="", description="공고번호 (질의 시 공고별 검색 범위 지정용, 선택)")):
    global VECTORSTORE_PDF
    bid_no = bid_no.strip()
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 허용됩니다.")
    if file.filename in stored_sources(VECTORSTORE_PDF):
        raise HTTPException(status_code=409, detail=f"이미 적재된 파일입니다: {file.filename}")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        try:
            pages = load_paper(tmp_path)
        finally:
            os.unlink(tmp_path)
        paper_text = "\n".join(text for _, text in pages)
        if not paper_text.strip():
            raise HTTPException(status_code=422, detail="PDF에서 텍스트를 추출하지 못했습니다. 스캔 PDF라면 OCR이 필요합니다.")
        # [Q01] PDF 청크 설계
        # [설계 판단] PDF 전체 텍스트를 임베딩하기 전에 검색 가능한 작은 단위로 나누되, 청크 경계에서 정보가 끊어지지 않도록 일부 중첩을 둡니다. 이 서버의 PDF 청크 크기와 중첩 크기를 설정하세요.
        # [TODO Q01] 아래 ... 부분을 적절한 코드로 교체하세요.
        # 쪽 단위로 나눈 뒤 청크로 자르므로 모든 청크가 자기 쪽 번호를 가진다
        # 1000자 청크에서는 공고문 1쪽(계약방법·예산·자격이 한 덩어리)이 "입찰 방식" 질문에 검색되지 않아 500자로 줄임
        splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=80)
        collected_at = datetime.now(UTC).strftime("%Y-%m-%d")
        docs = splitter.create_documents(
            [mask_contacts(text) for _, text in pages],
            metadatas=[{"source": file.filename, "page": page, "bid_no": bid_no, "collected_at": collected_at}
                       for page, _ in pages],
        )

        # [Q02] PDF 임베딩과 벡터 저장소 연결
        # [설계 판단] 분할한 PDF 문서(docs)를 OpenAI 임베딩 모델로 벡터화하여 FAISS 검색 저장소로 만드세요.
        # [TODO Q02] 아래 ... 부분을 적절한 코드로 교체하세요.
        # 공고 20건을 차례로 올리므로 덮어쓰지 않고 누적한다
        VECTORSTORE_PDF = add_to_store(VECTORSTORE_PDF, docs)
        # 같은 공고에 문서가 추가되면 저장해 둔 추출 결과는 낡은 것이므로 버린다
        for key in [k for k in EXTRACT_CACHE if k[0] == bid_no]:
            del EXTRACT_CACHE[key]

        # ✅ 디스크에 저장
        os.makedirs("faiss_db/pdf", exist_ok=True)
        VECTORSTORE_PDF.save_local("faiss_db/pdf")

        return JSONResponse(content={
            "message": f"{len(docs)}개의 PDF 청크 벡터화 및 저장 완료",
            "pages": len(pages),
            "bid_no": bid_no,
            "total_files": len(stored_sources(VECTORSTORE_PDF)),
            "extracted_characters": len(paper_text),
            "preview": paper_text[:300]
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 질의 요청/응답 모델 정의
# ✅ 질의 요청 모델
class RAGRequest(BaseModel):
    prompt: str = Field(default=..., description="질문 프롬프트")
    source: str = Field(default=..., description="web | pdf")
    # 평가셋 26문항 기준 top_k 5 → 10에서 정확 16/22 → 20/22, 응답 시간 변화 0.1초 (eval/results)
    top_k: int = Field(default=10, ge=1, description="검색할 결과 수 (기본값 10)")
    bid_no: Optional[str] = Field(default=None, description="공고번호 (지정하면 그 공고 PDF에서만 검색)")

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
@app.post("/rag-query", response_model=AnswerResponse, summary="Closed Source LLM + 벡터 DB 질의", tags=["질의 응답"])
async def rag_query(rag_request: RAGRequest = Body(...)):
    t0 = time.perf_counter()
    review = needs_review_for(rag_request.prompt)

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

        # 없는 공고번호로 검색하면 "문서에 답이 없음"과 구분되지 않으므로 오류로 알린다
        if rag_request.bid_no and rag_request.bid_no not in stored_bid_nos(VECTORSTORE_PDF):
            raise HTTPException(
                status_code=404,
                detail=f"적재되지 않은 공고번호입니다: {rag_request.bid_no} (적재된 공고번호: {sorted(stored_bid_nos(VECTORSTORE_PDF))})",
            )

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
            # bid_no를 주면 그 공고의 청크만 검색 (fetch_k개를 먼저 찾은 뒤 필터)
            search_kwargs = {"filter": {"bid_no": rag_request.bid_no}, "fetch_k": 100} if rag_request.bid_no else {}
            docs_scores = vectorstore.similarity_search_with_score(rag_request.prompt, k=top_k, **search_kwargs)
            print(f"[PDF 검색] 질문={rag_request.prompt!r}, 검색 문서 수={len(docs_scores)}")
            for i, (doc, score) in enumerate(docs_scores, start=1):
                print(f"[PDF 검색 {i}] 거리={score:.5f}, 출처={source_label(doc.metadata)}, 내용={doc.page_content[:300]!r}")

            # 의미 검색이 놓친, 질문 단어가 그대로 든 조각을 최대 3개 덧붙인다 (LLM 호출 수는 그대로)
            seen = {(d.metadata.get("source"), d.metadata.get("page"), d.page_content) for d, _ in docs_scores}
            for d in keyword_chunks(vectorstore, rag_request.prompt, rag_request.bid_no, seen):
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
                content = (doc.page_content or "").strip()
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
            final = (result.answer or "").strip()
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
# ✅ 공고별 구조화 추출 (채점표 · 제출서류 · 요약)
#    3번(점수 · 체크리스트)과 5번(화면)이 쓰는 JSON을 만든다.
#    검색 순위에 기대면 정답 조각이 빠질 수 있으므로, 해당 공고에서 키워드가 나온 쪽을
#    통째로 모아 LLM에 넘기고 LLM은 표를 옮겨 적기만 한다(점수 계산은 3번 코드가 담당).
# =====================================================================
from typing import Literal

EXTRACT_CACHE: dict[tuple[str, str], dict] = {}  # (bid_no, 종류) → 결과. 같은 공고 재요청 시 LLM 비용 절감

def bid_chunks(bid_no: str, keywords: tuple[str, ...] | None = None) -> list[Document]:
    if bid_no not in stored_bid_nos(VECTORSTORE_PDF):
        raise HTTPException(
            status_code=404,
            detail=f"적재되지 않은 공고번호입니다: {bid_no} (적재된 공고번호: {sorted(stored_bid_nos(VECTORSTORE_PDF))})",
        )
    docs = [(i, d) for i, d in enumerate(VECTORSTORE_PDF.docstore._dict.values()) if d.metadata.get("bid_no") == bid_no]
    if keywords:
        hit = {(d.metadata["source"], d.metadata["page"]) for _, d in docs if any(k in d.page_content for k in keywords)}
        # 표가 다음 쪽으로 이어질 수 있어 키워드가 나온 쪽의 다음 쪽까지 포함
        pages = hit | {(src, page + 1) for src, page in hit}
        docs = [(i, d) for i, d in docs if (d.metadata["source"], d.metadata["page"]) in pages]
    docs.sort(key=lambda x: (x[1].metadata["page"], x[1].metadata["source"], x[0]))
    return [d for _, d in docs]

def numbered_context(docs: list[Document], limit_chars: int = 24000) -> tuple[str, dict[int, str], dict[int, str]]:
    parts, labels, texts, total = [], {}, {}, 0
    for i, d in enumerate(docs, start=1):
        if total + len(d.page_content) > limit_chars:
            break
        labels[i] = source_label(d.metadata)
        texts[i] = d.page_content
        parts.append(f"[문서 {i} | {labels[i]}]\n{d.page_content}")
        total += len(d.page_content)
    return "\n\n".join(parts), labels, texts

def _squash(s: str) -> str:
    return re.sub(r"[\s()·,]", "", s)

def verified_source(name: str, doc_no: int | None, labels: dict[int, str], texts: dict[int, str],
                    siblings: list[str] | None = None) -> tuple[str, bool]:
    # LLM이 고른 [문서 n]을 그대로 믿지 않는다: 이름이 실제로 들어 있는 조각만 후보로 두고
    # (줄바꿈 · 띄어쓰기 · 괄호 차이는 무시), "제안서"처럼 짧은 이름이 일정표 등에도 나오는 경우를 막기 위해
    # 함께 추출된 이름(siblings)을 가장 많이 담은 조각, 즉 목록 표가 있는 조각을 우선한다
    key = _squash(name)
    candidates = [n for n, text in texts.items() if key in _squash(text)]
    if not candidates:
        return labels.get(doc_no or 0, "unknown"), False
    if siblings:
        keys = [_squash(s) for s in siblings]
        def score(n):
            return sum(k in _squash(texts[n]) for k in keys)
        best = max(score(n) for n in candidates)
        candidates = [n for n in candidates if score(n) == best]
    return labels[doc_no if doc_no in candidates else candidates[0]], True

def run_extraction(schema, instruction: str, context: str):
    llm = ChatOpenAI(model="gpt-4o", temperature=0).with_structured_output(schema, method="function_calling")
    return llm.invoke([HumanMessage(content=f"{instruction}\n\n{context}")])

def cached(bid_no: str, kind: str, refresh: bool, build) -> dict:
    key = (bid_no, kind)
    if refresh or key not in EXTRACT_CACHE:
        EXTRACT_CACHE[key] = build()
    return EXTRACT_CACHE[key]

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

@app.get("/bids/{bid_no}/scoring-table", summary="공고 채점표 추출 (3번 점수 계산용)", tags=["공고 추출"])
async def scoring_table(bid_no: str, refresh: bool = Query(False, description="true면 저장된 결과를 무시하고 다시 추출")):
    def build():
        t0 = time.perf_counter()
        docs = bid_chunks(bid_no, ("배점", "평가항목", "평가 항목", "기술능력평가", "입찰가격평가", "합 계", "합계"))
        if not docs:
            return {"bid_no": bid_no, "items": [], "needs_review": True, "handoff": True,
                    "message": "채점표를 찾지 못했습니다. 제안요청서가 적재되었는지 확인하세요."}
        context, labels, texts = numbered_context(docs)
        result = run_extraction(ScoringExtraction,
            "아래는 한 공고의 공고문 · 제안요청서 일부입니다. 제안서 평가 채점표의 평가 항목과 배점을 빠짐없이 옮기세요. "
            "세부 항목이 있으면 세부 항목 단위로 넣고, 소계 · 합계 행은 items에 넣지 마세요. 입찰가격평가도 하나의 항목으로 넣으세요. "
            "협상적격자 · 적격 통과 기준이 적혀 있으면 pass_rule에 원문 그대로 넣으세요. "
            + EXTRACT_RULES, context)
        items = []
        for it in result.items:
            source, ok = verified_source(it.item, it.doc_no, labels, texts)
            items.append({**it.model_dump(exclude={"doc_no"}), "source": source, "source_verified": ok})
        total = round(sum(it["max_score"] for it in items), 2)
        # 옮겨 적은 배점의 합이 문서의 합계와 다르면 누락 · 중복이 있다는 뜻이므로 표시
        consistent = result.declared_total is None or abs(total - result.declared_total) < 0.01
        return {"bid_no": bid_no, "items": items, "total_max_score": total,
                "declared_total": result.declared_total, "consistent": consistent,
                "pass_rule": result.pass_rule, "pass_rule_source": labels.get(result.pass_rule_doc_no or 0, ""),
                "needs_review": True, "handoff": False, "latency_ms": elapsed_ms(t0)}
    try:
        return cached(bid_no, "scoring", refresh, build)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---- 제출서류 ----
class RequiredDoc(BaseModel):
    doc_name: str = Field(description="서류명, 원문 그대로")
    note: str = Field(description="비고 · 형식 · 서식 번호, 없으면 빈 문자열")
    mandatory: bool = Field(description="필수 제출이면 true, '해당 시' 등 조건부면 false")
    doc_no: int = Field(description="이 서류가 적힌 [문서 n]의 번호")

class RequiredDocsExtraction(BaseModel):
    docs: List[RequiredDoc]
    due: str = Field(description="제출 기한, 원문 그대로. 없으면 빈 문자열")
    method: str = Field(description="제출 방법, 원문 그대로. 없으면 빈 문자열")
    due_doc_no: Optional[int] = Field(default=None, description="제출 기한이 적힌 [문서 n]의 번호")

@app.get("/bids/{bid_no}/required-docs", summary="공고 제출서류 추출 (3번 체크리스트용)", tags=["공고 추출"])
async def required_docs(bid_no: str, refresh: bool = Query(False, description="true면 저장된 결과를 무시하고 다시 추출")):
    def build():
        t0 = time.perf_counter()
        docs = bid_chunks(bid_no, ("제출 서류", "제출서류", "서류명", "제출 기한", "제출기한", "제출 방법"))
        if not docs:
            return {"bid_no": bid_no, "docs": [], "needs_review": True, "handoff": True,
                    "message": "제출서류 목록을 찾지 못했습니다."}
        context, labels, texts = numbered_context(docs)
        result = run_extraction(RequiredDocsExtraction,
            "아래는 한 공고의 공고문 · 제안요청서 일부입니다. 입찰 시 제출해야 하는 서류 목록과 제출 기한 · 방법을 옮기세요. "
            "공고문과 제안요청서에 같은 서류가 중복으로 나오면 한 번만 넣되, 두 문서의 비고를 빠짐없이 합쳐 note에 적고 "
            "doc_no는 서류 목록 표가 더 자세한 쪽의 번호로 하세요. " + EXTRACT_RULES, context)
        out_docs = []
        names = [d.doc_name for d in result.docs]
        for d in result.docs:
            source, ok = verified_source(d.doc_name, d.doc_no, labels, texts, siblings=names)
            out_docs.append({**d.model_dump(exclude={"doc_no"}), "source": source, "source_verified": ok})
        due_source, _ = verified_source(result.due, result.due_doc_no, labels, texts) if result.due else ("", False)
        return {"bid_no": bid_no, "docs": out_docs,
                "due": result.due, "method": result.method,
                "due_source": due_source,
                "needs_review": False, "handoff": False, "latency_ms": elapsed_ms(t0)}
    try:
        return cached(bid_no, "required_docs", refresh, build)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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

@app.get("/bids/{bid_no}/summary", summary="공고 요약 (항목별 출처 포함)", tags=["공고 추출"])
async def bid_summary(bid_no: str, refresh: bool = Query(False, description="true면 저장된 결과를 무시하고 다시 추출")):
    def build():
        t0 = time.perf_counter()
        context, labels, _ = numbered_context(bid_chunks(bid_no))  # 앞쪽부터 담아 공고 개요가 먼저 들어가게 한다
        result = run_extraction(BidSummary,
            "아래는 한 공고의 공고문 · 제안요청서입니다. 각 항목을 1~3문장으로 요약하세요. " + EXTRACT_RULES, context)
        fields = {name: {"value": f.value, "source": labels.get(f.doc_no or 0, "")}
                  for name, f in result}
        missing = [name for name, f in fields.items() if not f["value"]]
        return {"bid_no": bid_no, "summary": fields, "missing": missing,
                "needs_review": False, "handoff": bool(missing), "latency_ms": elapsed_ms(t0)}
    try:
        return cached(bid_no, "summary", refresh, build)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 실행 명령어 예시:
# python -m uvicorn rag_external-web_pdf_closed_llm:app --port 8001 --reload