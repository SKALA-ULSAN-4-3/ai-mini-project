"""RAG 서비스(2번)와 데이터 파이프라인(1번) · 공고 로직(3번)을 잇는 연결 계층.

- 1번이 적재한 인덱스(data/indexes/{pdf,web})를 다시 임베딩하지 않고 LangChain FAISS로 감싼다.
  1번은 정규화 벡터의 내적(IndexFlatIP, 클수록 유사)을 쓰지만 3번 추천은 "작을수록 유사"를
  가정하므로, 같은 벡터를 L2 인덱스에 담는다. 정규화 벡터는 L2² = 2 - 2·코사인이라 순위가 같다.
- 질문 임베딩도 1번 Embedder를 그대로 써서 문서와 질문의 임베딩 모델이 어긋나지 않게 한다.
- 메타데이터 이름을 3번 규격(bid_no, revision, filename, page)으로 맞춘다.
- 1번 bids.csv와 2번 추출 결과를 3번 입력 형식으로 바꾼다.
"""
import csv
import json
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_env import load_env  # noqa: E402  (프로젝트 루트 .env를 1·3번과 같은 방식으로 읽는다)

load_env()

import faiss  # noqa: E402
from langchain_community.docstore.in_memory import InMemoryDocstore  # noqa: E402
from langchain_community.vectorstores import FAISS  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_core.embeddings import Embeddings  # noqa: E402

from data_pipeline.knowledge import Embedder, KnowledgeStore  # noqa: E402

BIDS_SOURCE = ROOT / "data" / "corpus" / "bids.csv"                 # 1번 산출물
BIDS_FOR_BID_LOGIC = Path(__file__).resolve().parent / "data" / "bids.csv"  # 3번 기본 경로


# ---------------------------------------------------------------- 인덱스 어댑터
class PipelineEmbeddings(Embeddings):
    """1번 Embedder를 LangChain 인터페이스로 감싼다 (정규화 포함)."""

    def __init__(self, model: str):
        self.embedder = Embedder(model)

    def embed_documents(self, texts):
        return self.embedder.embed(list(texts)).tolist()

    def embed_query(self, text):
        return self.embedder.embed([text])[0].tolist()


def normalize_metadata(record: dict) -> dict:
    # 1번 이름(bid_order, file_name)을 3번 규격(revision, filename)으로. 기존 2번 코드가 쓰는 source도 유지.
    filename = record.get("file_name") or ""
    url = record.get("resolved_url") or record.get("source_url") or record.get("url") or ""
    meta = {
        "bid_no": record.get("bid_no") or "",
        "revision": record.get("bid_order") or "",
        "filename": filename,
        "page": record.get("page"),
        "collected_at": record.get("collected_at") or "",
        "source_url": url,
        "title": record.get("title") or "",
        "topic": record.get("topic") or "",
        "chunk_id": record.get("chunk_id") or "",
        "source": filename or url,
    }
    if record.get("equivalent_sources"):
        meta["equivalent_sources"] = record["equivalent_sources"]
    return meta


def build_langchain_store(index, records, manifest) -> FAISS | None:
    if index is None or not records:
        return None
    vectors = index.reconstruct_n(0, index.ntotal)
    l2 = faiss.IndexFlatL2(vectors.shape[1])
    l2.add(vectors)
    ids = [r.get("chunk_id") or str(i) for i, r in enumerate(records)]
    docstore = InMemoryDocstore({cid: Document(page_content=r["text"], metadata=normalize_metadata(r))
                                 for cid, r in zip(ids, records)})
    return FAISS(embedding_function=PipelineEmbeddings(manifest["embedding_model"]), index=l2,
                 docstore=docstore, index_to_docstore_id=dict(enumerate(ids)), normalize_L2=True)


class StoreCache:
    """1번 저장소의 현재 세대를 읽고, 업로드로 세대가 바뀌면 다시 감싼다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[str | None, FAISS | None, dict | None]] = {}

    @staticmethod
    def generation(kind: str) -> str | None:
        pointer = KnowledgeStore(kind).path / "current.json"
        return json.loads(pointer.read_text())["generation"] if pointer.exists() else None

    def get(self, kind: str) -> tuple[FAISS | None, str | None, dict | None]:
        current = self.generation(kind)
        with self._lock:
            cached = self._cache.get(kind)
            if cached and cached[0] == current:
                return cached[1], cached[0], cached[2]
            index, records, manifest = KnowledgeStore(kind).load()
            store = build_langchain_store(index, records, manifest)
            self._cache[kind] = (current, store, manifest)
            return store, current, manifest


# ---------------------------------------------------------------- 첨부 종류 판별 (흐름 ③ 공고문만 / ⑥ 나머지)
# 실제 API 결과 파일명 예: "(공고문) …pdf", "입찰공고(2026-249) ….hwp", "입찰공고서_….hwpx",
#                          "[제안요청서] ….hwp", "(과업내용서) ….hwpx", "3. 과업지시서(…).hwp"
NOTICE_WORDS = ("공고문", "공고서", "입찰공고", "재공고")
RFP_WORDS = ("제안요청서", "제안요청", "과업지시서", "과업내용서", "규격서", "RFP")


def classify_attachment(filename: str) -> set[str]:
    """파일명으로 공고문(notice) · 제안요청서류(rfp)를 판별. 둘 다 아니면 {"other"}. 둘 다 해당할 수 있다."""
    import unicodedata
    name = unicodedata.normalize("NFC", filename or "")  # macOS 파일명(NFD)도 같게 비교
    kinds = {k for k, words in (("rfp", RFP_WORDS), ("notice", NOTICE_WORDS)) if any(w in name for w in words)}
    if "취소" in name:
        kinds.add("cancel")
    return kinds or {"other"}


# ---------------------------------------------------------------- 1번 bids.csv → 3번 형식
REGION_SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천",
                "광주광역시": "광주", "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종",
                "경기도": "경기", "강원특별자치도": "강원", "강원도": "강원", "충청북도": "충북", "충청남도": "충남",
                "전북특별자치도": "전북", "전라북도": "전북", "전라남도": "전남", "경상북도": "경북",
                "경상남도": "경남", "제주특별자치도": "제주"}
BID_LOGIC_FIELDS = ["bid_no", "revision", "title", "agency", "published_at", "budget", "deadline",
                    "regions", "industries", "licenses", "company_sizes", "certs", "filename", "url"]


def _date(raw: str) -> str:
    m = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", raw or "")
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else ""


def _deadline(raw: str) -> str:
    # 시각이 없는 마감은 임의 시각을 만들지 않고 비워 둔다 (3번 계약)
    m = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})[ T](\d{1,2}):(\d{2})", raw or "")
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}T{int(m[4]):02d}:{m[5]}+09:00" if m else ""


def _budget(row: dict) -> str:
    for key in ("allocated_budget", "estimated_price"):
        digits = re.sub(r"[^\d.]", "", row.get(key) or "")
        if digits:
            return str(int(float(digits)))
    return ""


def _regions(row: dict) -> str:
    # 확정된 지역 제한만 배열로. 제한 없음 명시는 [], 미명시 · 모호 · 시군구 제한 · 검토 필요는 null(미확인)
    status = (row.get("region_status") or "").strip()
    if status == "explicit_none":
        return "[]"
    if status == "restricted" and str(row.get("metadata_needs_review", "")).lower() not in ("true", "1", "yes"):
        names = [REGION_SHORT.get(t.strip(), t.strip()) for t in re.split(r"\s*/\s*", row.get("region_restriction") or "")]
        names = [n for n in names if n in REGION_SHORT.values()]
        if names:
            return json.dumps(list(dict.fromkeys(names)), ensure_ascii=False)
    return ""


def convert_bids_csv(src: Path = BIDS_SOURCE, dst: Path = BIDS_FOR_BID_LOGIC) -> int:
    """1번 bids.csv를 3번 load_bids_csv가 읽는 형식으로 쓴다. 업종 · 면허 · 기업규모 · 인증은
    1번이 자유 텍스트로만 기록하므로 확정하지 않고 null(미확인)로 둔다. 쓴 행 수를 반환."""
    with Path(src).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    out = []
    for row in rows:
        # downloaded_files는 파일 이름이 아니라 받은 개수(예: "0")이므로 쓰지 않는다
        files = [f for f in re.split(r"[;|\n]", row.get("file_names") or "") if f.strip()]
        out.append({"bid_no": row["bid_no"].strip(), "revision": (row.get("bid_order") or "").strip(),
                    "title": row.get("title", ""), "agency": row.get("agency", ""),
                    "published_at": _date(row.get("published_at", "")), "budget": _budget(row),
                    "deadline": _deadline(row.get("deadline", "")), "regions": _regions(row),
                    "industries": "", "licenses": "", "company_sizes": "", "certs": "",
                    "filename": files[0].strip() if files else "", "url": row.get("detail_url", "")})
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=BID_LOGIC_FIELDS)
        writer.writeheader()
        writer.writerows(out)
    return len(out)


def sync_bids_csv() -> bool:
    """1번 산출물이 있고 변환본보다 새로우면 다시 변환. 변환했으면 True."""
    if not BIDS_SOURCE.exists():
        return False
    if BIDS_FOR_BID_LOGIC.exists() and BIDS_FOR_BID_LOGIC.stat().st_mtime >= BIDS_SOURCE.stat().st_mtime:
        return False
    convert_bids_csv()
    return True


# ---------------------------------------------------------------- 2번 추출 결과 → 3번 형식
KIND = {"정량": "quantitative", "정성": "qualitative", "가격": "price"}


def to_bid_logic_scoring(extraction: dict, bid_no: str, revision: str) -> dict:
    items = []
    for i, it in enumerate(extraction["items"], start=1):
        kind = KIND.get(it["eval_type"], "qualitative")
        rule = it.get("rule")
        items.append({
            "bid_no": bid_no, "revision": revision, "id": f"item{i:02d}", "item": it["item"],
            "section": it.get("section", ""), "kind": kind, "max": it["max_score"],
            "basis": it.get("criteria") or f"{it.get('section', '')} · {it['item']}",
            "sources": it.get("source_refs", []),
            # 원문에 계산 규칙이 명시된 정량 항목만 metric · rule을 채운다. 없으면 3번이 '담당자 판단'으로 처리
            "metric": rule["metric"] if rule else None, "rule": rule["rule"] if rule else None,
        })
    return {"bid_no": bid_no, "revision": revision, "items": items}


def to_bid_logic_checklist(extraction: dict, bid_no: str, revision: str) -> dict:
    documents = [{"id": f"doc{i:02d}", "doc": d["doc_name"], "bid_no": bid_no, "revision": revision,
                  "due": d.get("due_iso"), "sources": d.get("source_refs", []),
                  "needs_review": d.get("needs_review", False),
                  "notes": [n for n in (d.get("note"), extraction.get("due_note")) if n]}
                 for i, d in enumerate(extraction["docs"], start=1)]
    schedule = [{"id": f"evt{i:02d}", "event": s["event"], "bid_no": bid_no, "revision": revision,
                 "due": s.get("due_iso"), "sources": s.get("source_refs", []),
                 "needs_review": s.get("needs_review", False),
                 "notes": [s["when"]] if s.get("when") else []}
                for i, s in enumerate(extraction.get("schedule", []), start=1)]
    return {"bid_no": bid_no, "revision": revision, "documents": documents, "schedule": schedule,
            "needs_review": extraction.get("needs_review", False),
            "quality_warnings": extraction.get("quality_warnings", [])}


_DATETIME = re.compile(r"(?:(\d{4})\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?\s*(?:\([^)]*\))?\s*"
                       r"(?:(\d{1,2})\s*[:시]\s*(\d{2})?)?")


def to_iso_due(text: str) -> str | None:
    """마감 시각을 ISO로. '2026. 11. 3.(화) 10:00' → '2026-11-03T10:00+09:00'.
    기간('A ~ B')이면 끝 시각 B를 쓰고, B에 연도가 없으면 A의 연도를 이어받는다.
    시각이 없으면 None (3번 계약: 임의 마감 시각을 만들지 않음)."""
    parts = re.split(r"\s*[~∼～]\s*", text or "")
    year = None
    for part in parts:
        m = _DATETIME.search(part)
        if m and m[1]:
            year = m[1]
    m = _DATETIME.search(parts[-1]) if parts else None
    if not m or not (m[1] or year) or m[4] is None:
        return None
    return f"{m[1] or year}-{int(m[2]):02d}-{int(m[3]):02d}T{int(m[4]):02d}:{m[5] or '00'}+09:00"
