"""데이터 파이프라인의 PDF·공식 웹 자료 누적 적재 API."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, UploadFile
from pypdf import PdfReader

from project_env import load_env
from .build_dataset import DEFAULT_DATASET
from .knowledge import KnowledgeStore
from .prepare_documents import split_text
from .privacy import extract_contacts, mask_personal
from .web_topics import topic_records

load_env()
router = APIRouter()


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
