"""데이터 파이프라인의 PDF·공식 웹 자료 누적 적재 API."""
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path

from fastapi import BackgroundTasks, APIRouter, FastAPI, File, Form, HTTPException, Query, UploadFile
from pypdf import PdfReader
from pydantic import AliasChoices, BaseModel, Field
from . import search_jobs
from . import collect_bids as collector

from project_env import load_env
from .build_dataset import DEFAULT_DATASET
from .knowledge import KnowledgeStore
from .prepare_documents import split_text
from .privacy import extract_contacts, mask_personal
from .web_topics import topic_records

load_env()
router = APIRouter()


class SearchBidsRequest(BaseModel):
    start: date = Field(alias="from", description="공고 게시 조회 시작일. 오늘까지 게시된 공고를 조회합니다.")
    end: date = Field(alias="to", description="입찰 마감 종료일. 오늘부터 이 날짜까지 마감하는 공고만 선택합니다.")
    queries: list[str] = Field(min_length=1)
    limit: int = Field(default=100, ge=1, le=100)


class SearchBidReference(BaseModel):
    bid_no: str = Field(min_length=1, max_length=40)
    bid_order: str = Field(pattern=r"^\d{3}$", validation_alias=AliasChoices("bid_order", "revision"))


class FetchBidsRequest(BaseModel):
    search_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    bids: list[SearchBidReference] = Field(min_length=1, max_length=20)


@router.post("/search-bids")
def search_bid_list(request: SearchBidsRequest):
    try:
        load_env()
        return search_jobs.search_bids(request.start, request.end, request.queries, request.limit,
                                      os.environ.get("DATA_GO_KR_SERVICE_KEY", ""))
    except collector.CollectionError as exc:
        raise HTTPException(502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    except (ImportError, RuntimeError):
        raise HTTPException(503, "검색 키 또는 RAG의 공통 문서 판별 함수 연결을 확인하세요.") from None


def enqueue_fetch(request, background_tasks, mode):
    try:
        load_env()
        key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
        if mode == "documents" and not key:
            raise HTTPException(503, "공고 차수 재확인에 필요한 API 키가 없습니다.")
        job = search_jobs.create_job(request.search_id, [b.model_dump() for b in request.bids], mode)
    except search_jobs.SearchNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    background_tasks.add_task(search_jobs.run_job, job["job_id"], key)
    return {"job_id": job["job_id"], "status": job["status"], "total": job["total"]}


@router.post("/fetch-notices", status_code=202)
def fetch_notices(request: FetchBidsRequest, background_tasks: BackgroundTasks):
    return enqueue_fetch(request, background_tasks, "notices")


@router.post("/fetch-documents", status_code=202)
def fetch_documents(request: FetchBidsRequest, background_tasks: BackgroundTasks):
    return enqueue_fetch(request, background_tasks, "documents")


@router.get("/jobs/{job_id}")
def fetch_progress(job_id: str):
    try:
        return search_jobs.get_job(job_id)
    except search_jobs.SearchNotFound as exc:
        raise HTTPException(404, str(exc)) from None



def dataset():
    return Path(os.environ.get("BID_DATASET_DIR", str(DEFAULT_DATASET)))


def store(kind):
    return KnowledgeStore(kind)


@router.get("/data-status")
def data_status():
    return {kind: store(kind).status() for kind in ("pdf", "web")}


@router.post("/upload-paper")
def upload_paper(file: UploadFile = File(...), bid_no: str = Form(""), bid_order: str = Form("000"),
                 source_url: str = Form(""), collected_at: str = Form(""), title: str = Form("")):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 허용됩니다.")
    raw = file.file.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(413, "PDF 50MB 제한")
    if not raw.startswith(b"%PDF-"):
        raise HTTPException(422, "유효한 PDF가 아닙니다.")
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("암호화 PDF")
        texts = [p.extract_text() or "" for p in reader.pages]
    except Exception:
        raise HTTPException(422, "PDF를 읽을 수 없습니다.") from None
    if not any(text.strip() for text in texts):
        raise HTTPException(422, "텍스트가 없습니다. 스캔 PDF는 교체 또는 OCR이 필요합니다.")
    digest = hashlib.sha256(raw).hexdigest()
    filename = Path(file.filename).name
    group = f"{bid_no}_{bid_order}:{source_url or filename}"
    contacts, records = [], []
    stamp = collected_at or datetime.now(timezone.utc).isoformat()
    # 공고 데이터셋의 API 담당자명도 업로드 경로에 동일하게 적용한다.
    names = []
    candidate_file = dataset() / "candidates.json"
    if bid_no and candidate_file.exists():
        from .privacy import official_names
        for item in json.loads(candidate_file.read_text()).get("items", []):
            if str(item.get("bidNtceNo")) == bid_no:
                names.extend(official_names(item))
    for page, text in enumerate(texts, 1):
        page_contacts = extract_contacts(text)
        contacts.extend({**c, "file_name": filename, "page": page, "source_url": source_url} for c in page_contacts)
        text = mask_personal(text, names)
        for offset, (_, _, part) in enumerate(split_text(text), 1):
            record = dict(text=part, group_id=group, bid_no=bid_no, bid_order=bid_order, title=title,
                          file_name=filename, page=page, source_url=source_url, collected_at=stamp,
                          citation=f"{filename} p.{page}", sha256=digest, contacts=page_contacts,
                          privacy_policy="mask_names_preserve_contacts_v1")
            record["chunk_id"] = hashlib.sha256((group+digest+str(page)+str(offset)+part).encode()).hexdigest()
            records.append(record)
    try:
        result = store("pdf").upsert(records)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"message": "PDF 누적 적재 완료", **result, "contacts": contacts, "pages": len(texts)}


@router.post("/upload-topic")
def upload_topic(topic: str = Query(...), url: str | None = Query(None), refresh: bool = Query(False)):
    try:
        records = topic_records(topic, url=url, refresh=refresh)
        return {"message": "웹 주제 누적 적재 완료", **store("web").upsert(records)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None



app = FastAPI(title="나라장터 데이터 적재 API")
app.include_router(router)
