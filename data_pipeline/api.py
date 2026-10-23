"""데이터 파이프라인의 PDF·공식 웹 자료 누적 적재 API."""
from datetime import datetime, timezone
import hashlib
import io
import logging
import os
from pathlib import Path
from datetime import date
import uuid
import re
from .common import read_json, DEFAULT_DATASET, read_jsonl, write_json

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pypdf import PdfReader
from pydantic import BaseModel, Field, model_validator

from project_env import load_env
from .knowledge import KnowledgeStore
from .prepare_documents import split_text, extract_contacts, mask_personal, official_names
from .web_topics import topic_records
from . import g2b_client as collector
from .bid_workflow import prepare_discovery, record_evaluation, validate_profile
from .recommendations import recommend_run, read_recommendations, validate_company_profile, ProfileError
from .delivery import select_for_delivery, build_archive, find_attachment, DeliveryIncomplete

load_env()
router = APIRouter()


def discovery_root():
    return Path(os.environ.get("BID_DISCOVERY_ROOT", str(DEFAULT_DATASET.parent / "discoveries"))).resolve()


def discovery_run(run_id):
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise HTTPException(404, "탐색 실행이 없습니다.")
    path = discovery_root() / run_id
    if not (path / "bid_list.json").is_file():
        raise HTTPException(404, "탐색 실행이 없습니다.")
    return path


class DiscoveryRequest(BaseModel):
    start: date
    end: date
    queries: list[str] = Field(default_factory=lambda: ["개발"], min_length=1)
    limit: int = Field(20, ge=1, le=100)
    company_profile: dict = Field(default_factory=dict)
    search_only: bool = False


class BidSelection(BaseModel):
    bid_ids: list[str] | None = Field(None, min_length=1, max_length=2)
    bid_id: str | None = None

    @model_validator(mode="after")
    def selected(self):
        if (self.bid_ids is None) == (self.bid_id is None):
            raise ValueError("bid_ids에 공고 1~2개를 지정하세요. 단건 bid_id와 함께 쓰지 않습니다.")
        ids = self.bid_ids if self.bid_ids is not None else [self.bid_id]
        if any(not value.strip() for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("중복 없는 공고 1~2개를 선택하세요.")
        return self


def evaluate_run(root):
    try:
        return recommend_run(root)
    except ProfileError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception as exc:
        # 외부 SDK 오류 본문이나 인증키를 HTTP 응답에 노출하지 않는다.
        logging.getLogger(__name__).error("추천 생성 실패 run=%s error_type=%s", root.name, type(exc).__name__)
        raise HTTPException(503, {"message": "추천 준비에 실패했습니다. 임베딩 설정을 확인하세요.",
                                 "run_id": root.name,
                                 "retry_url": f"/bid-runs/{root.name}/recommendations"}) from None


@router.post("/bid-runs", status_code=201)
def discover_bids(request: DiscoveryRequest):
    if request.start > request.end or not all(q.strip() for q in request.queries):
        raise HTTPException(422, "검색 기간과 검색어를 확인하세요.")
    try:
        validate_profile(request.company_profile)
        if not request.search_only:
            validate_company_profile(request.company_profile, request.start, request.end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    load_env()
    key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
    if not key:
        raise HTTPException(503, "공고 조회 API 키가 설정되지 않았습니다.")
    try:
        items, truncated = collector.search_candidates(key, request.start, request.end, request.queries, request.limit)
        run_id = uuid.uuid4().hex
        root = discovery_root() / run_id
        root.mkdir(parents=True)
        write_json(root / "candidates.json", {"request": {
            "start": str(request.start), "end": str(request.end), "queries": request.queries,
            "candidate_limit": request.limit, "collected_at": datetime.now(timezone.utc).isoformat(),
            "page_limit_reached": truncated}, "items": items})
        result = prepare_discovery(root, request.company_profile, request.search_only)
        recommendations = evaluate_run(root) if not request.search_only else None
        return {"run_id": run_id, **result,
                "recommended_bid_ids": recommendations["recommended_bid_ids"] if recommendations else [],
                "recommendations": recommendations}
    except collector.CollectionError as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/bid-runs/{run_id}/bids")
def bid_list(run_id: str, suitable_only: bool = False):
    root = discovery_run(run_id)
    listing = read_json(root / "bid_list.json")
    recommendations = read_recommendations(root)
    listing["recommended_bid_ids"] = recommendations["recommended_bid_ids"] if recommendations else []
    listing["recommendations"] = recommendations
    if suitable_only:
        listing["items"] = [r for r in listing["items"] if r["bid_id"] in listing["recommended_bid_ids"]]
    return listing


@router.post("/bid-runs/{run_id}/recommendations")
def evaluate_bids(run_id: str):
    return evaluate_run(discovery_run(run_id))


@router.get("/bid-runs/{run_id}/recommendations")
def recommendations(run_id: str):
    result = read_recommendations(discovery_run(run_id))
    if result is None:
        raise HTTPException(409, "현재 입력의 추천이 없습니다. 추천 생성 요청이 필요합니다.")
    return result


@router.get("/bid-runs/{run_id}/evaluation-inputs")
def evaluation_inputs(run_id: str):
    return {"evaluation_implemented": False, "items": read_jsonl(discovery_run(run_id) / "evaluation_inputs.jsonl")}


@router.put("/bid-runs/{run_id}/bids/{bid_id}/evaluation")
def save_evaluation(run_id: str, bid_id: str, payload: dict):
    try:
        return record_evaluation(discovery_run(run_id), bid_id, payload)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/bid-runs/{run_id}/selection")
def user_selection(run_id: str, request: BidSelection):
    try:
        ids = request.bid_ids if request.bid_ids is not None else [request.bid_id]
        result = select_for_delivery(discovery_run(run_id), ids)
        base = f"/bid-runs/{run_id}"
        result["download_url"] = f"{base}/download" if result["complete"] else None
        for item in result["items"]:
            for attachment in item["attachments"]:
                attachment["download_url"] = (f"{base}/bids/{item['bid_id']}/attachments/{attachment['file_id']}"
                                              if attachment["available"] else None)
        return result
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/bid-runs/{run_id}/download")
def download_selection(run_id: str):
    try:
        path = build_archive(discovery_run(run_id))
        return FileResponse(path, media_type="application/zip", filename=f"bids-{run_id}.zip")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/bid-runs/{run_id}/bids/{bid_id}/attachments/{file_id}")
def download_attachment(run_id: str, bid_id: str, file_id: str):
    try:
        path, name = find_attachment(discovery_run(run_id), bid_id, file_id)
        return FileResponse(path, media_type="application/octet-stream", filename=name)
    except DeliveryIncomplete as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
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
        for item in read_json(candidate_file).get("items", []):
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
app.add_middleware(CORSMiddleware,
    allow_origins=[s.strip() for s in os.environ.get("BID_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if s.strip()],
    allow_methods=["GET", "POST", "PUT"], allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Disposition"])
app.include_router(router)
