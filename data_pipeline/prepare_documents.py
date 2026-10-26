"""수집 실행 폴더의 선택된 첨부를 페이지/청크 JSONL로 정리한다.

원본과 연락처를 보존한다. 변환 기록이 있으면 PDF를 사용한다. OCR·임베딩은 수행하지 않는다.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import signal
from pathlib import Path
import time
import sys

if __package__:
    from .privacy import mask_personal, extract_contacts, official_names
    from . import convert_documents as converter
else:
    from privacy import mask_personal, extract_contacts, official_names
    import convert_documents as converter

PREPARATION_VERSION = hashlib.sha256(
    Path(__file__).read_bytes() + Path(__file__).with_name("privacy.py").read_bytes()
).hexdigest()


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def split_text(text, size=1000, overlap=200):
    """페이지 경계를 넘지 않는 문자 단위 청킹. 원문 공백/연락처 유지."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("청크 길이는 양수, 중첩은 0 이상 청크 길이 미만이어야 합니다.")
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = end - overlap


def write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def prepare(run_dir, chunk_size=1000, overlap=200, reader_factory=None):
    # 생성물을 덮어쓰기 전에 설정·입력 파일을 먼저 검사한다.
    list(split_text("test", chunk_size, overlap))
    run_dir = Path(run_dir).resolve()
    attachments = read_csv(run_dir / "attachments.csv")
    bids = {(r["bid_no"], r["bid_order"]): r for r in read_csv(run_dir / "bids.csv")}
    api_items = {}
    if (run_dir / "candidates.json").exists():
        saved = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
        api_items = {(str(r["bidNtceNo"]), str(r.get("bidNtceOrd") or "000")): r
                     for r in saved.get("items", [])}
    conversions = {}
    if (run_dir / "conversions.jsonl").is_file():
        conversions = {r["original_path"]: r for r in map(json.loads, (run_dir / "conversions.jsonl").read_text(encoding="utf-8").splitlines())}
    if reader_factory is None:
        from pypdf import PdfReader
        reader_factory = PdfReader

    output = run_dir / "processed"
    previous = {}
    try:
        old_documents = read_jsonl(output / "documents.jsonl")
        old_pages = read_jsonl(output / "pages.jsonl")
        old_chunks = read_jsonl(output / "chunks.jsonl")
        old_pages_by_url, old_chunks_by_url = {}, {}
        for record in old_pages:
            old_pages_by_url.setdefault(record.get("source_url"), []).append(record)
        for record in old_chunks:
            old_chunks_by_url.setdefault(record.get("source_url"), []).append(record)
        previous = {row.get("source_url"): (row, old_pages_by_url.get(row.get("source_url"), []),
                                              old_chunks_by_url.get(row.get("source_url"), []))
                    for row in old_documents if row.get("source_url")}
    except (OSError, ValueError, TypeError):
        previous = {}
    pages, chunks, documents = [], [], []
    for row in attachments:
        if row.get("selected", "").lower() != "true":
            continue
        bid = bids.get((row["bid_no"], row["bid_order"]), {})
        api_item = api_items.get((row["bid_no"], row["bid_order"]), {})
        local = row.get("local_path", "")
        path = Path(local) if local else None
        if path and not path.is_absolute():
            path = run_dir / path
        base = {
            "bid_no": row["bid_no"], "bid_order": row["bid_order"],
            "title": bid.get("title", ""), "file_name": row["file_name"],
            "local_path": str(path.resolve()) if path else "",
            "source_url": row.get("url", ""), "detail_url": bid.get("detail_url", ""),
            "collected_at": bid.get("collected_at", ""),
            "original_file_name": row["file_name"],
            "original_local_path": str(path.resolve()) if path else "",
            "requires_layout_review": False,
        }
        doc = {**base, "document_id": "", "sha256": "", "status": "",
               "page_count": 0, "empty_pages": [], "chunk_count": 0, "error": ""}
        documents.append(doc)
        if row.get("status") not in ("downloaded", "existing") or not path or not path.is_file():
            doc["status"] = "download_required"
            continue
        # 첨부 URL과 원본 해시를 포함해 같은 공고의 동명 파일도 구분한다.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        identity = "|".join((row["bid_no"], row["bid_order"], row.get("url", ""), digest))
        document_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
        doc.update(document_id=document_id, sha256=digest)
        if path.suffix.lower() in (".hwp", ".hwpx"):
            conversion = conversions.get(str(path.resolve()), {})
            if not conversion:
                doc["status"] = "conversion_required"
                continue
            pdf = Path(conversion.get("pdf_path") or "__missing_pdf__")
            if (conversion.get("status") not in ("converted", "existing")
                    or conversion.get("original_sha256") != digest or not pdf.is_file()
                    or hashlib.sha256(pdf.read_bytes()).hexdigest() != conversion.get("pdf_sha256")):
                doc.update(status="conversion_failed", error=conversion.get("error") or "변환 기록 불일치")
                continue
            path = pdf
            base.update(file_name=pdf.name, local_path=str(pdf), original_sha256=digest,
                        requires_layout_review=True)
            digest = conversion["pdf_sha256"]
            document_id = hashlib.sha256((identity + digest).encode()).hexdigest()[:24]
            doc.update(base, document_id=document_id, sha256=digest)
        if path.suffix.lower() != ".pdf":
            doc["status"] = "unsupported_format"
            continue
        doc["source_sha256"] = digest
        doc["preparation_version"] = PREPARATION_VERSION
        old = previous.get(row.get("url"))
        if old:
            old_doc, saved_pages, saved_chunks = old
            if (old_doc.get("source_sha256") == digest
                    and old_doc.get("document_id") == document_id
                    and old_doc.get("preparation_version") == PREPARATION_VERSION
                    and old_doc.get("status") in ("extracted", "review_empty_pages")):
                # 같은 해시·전처리 버전은 페이지 파싱·개인정보 마스킹·청킹을 다시 하지 않는다.
                doc.update({**old_doc, **base, "document_id": document_id, "sha256": digest,
                            "source_sha256": digest, "preparation_version": PREPARATION_VERSION,
                            "extraction_seconds": 0.0})
                documents[-1] = doc
                pages.extend({**record, **base, "document_id": document_id, "sha256": digest,
                              "source_sha256": digest, "preparation_version": PREPARATION_VERSION}
                             for record in saved_pages)
                chunks.extend({**record, **base, "document_id": document_id, "sha256": digest,
                               "source_sha256": digest, "preparation_version": PREPARATION_VERSION}
                              for record in saved_chunks)
                continue
        extraction_started = time.perf_counter()
        try:
            with path.open("rb") as source:
                reader = reader_factory(source)
                if reader.is_encrypted and not reader.decrypt(""):
                    doc["status"] = "password_required"
                    continue
                # 파일 중간의 오류가 나면 해당 문서의 불완전한 청크는 전달하지 않는다.
                texts = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            doc.update(status="extraction_failed", error=type(exc).__name__,
                       extraction_seconds=round(time.perf_counter() - extraction_started, 3))
            continue
        doc["page_count"] = len(texts)
        doc["empty_pages"] = [i for i, t in enumerate(texts, 1) if not t.strip()]
        doc["status"] = ("empty_text" if not any(t.strip() for t in texts)
                         else "review_empty_pages" if doc["empty_pages"] else "extracted")
        for page_no, text in enumerate(texts, 1):
            contacts = extract_contacts(text)
            text = mask_personal(text, official_names(api_item))
            metadata = {**base, "document_id": document_id, "sha256": digest, "page": page_no,
                        "source_sha256": digest, "preparation_version": PREPARATION_VERSION,
                        "contacts": contacts, "privacy_policy": "mask_names_preserve_contacts_v1",
                        "citation": f"{base['file_name']} p.{page_no}",
                        "document_status": doc["status"]}
            pages.append({**metadata, "text": text})
            if not text.strip():
                continue
            for index, (start, end, part) in enumerate(split_text(text, chunk_size, overlap), 1):
                chunks.append({**metadata, "chunk_id": f"{document_id}-p{page_no}-c{index}",
                               "char_start": start, "char_end": end, "text": part})
                doc["chunk_count"] += 1
        doc["extraction_seconds"] = round(time.perf_counter() - extraction_started, 3)

    output.mkdir(exist_ok=True)
    write_jsonl(output / "pages.jsonl", pages)
    write_jsonl(output / "chunks.jsonl", chunks)
    write_jsonl(output / "documents.jsonl", documents)
    pending = [d for d in documents if d["status"] != "extracted" or d["requires_layout_review"]]
    write_jsonl(output / "needs_attention.jsonl", pending)
    counts = {}
    for doc in documents:
        counts[doc["status"]] = counts.get(doc["status"], 0) + 1
    summary = {"prepared_at": datetime.now(timezone.utc).isoformat(), "run_dir": str(run_dir),
               "documents": len(documents), "pages": len(pages), "chunks": len(chunks),
               "statuses": counts, "chunk_size": chunk_size, "overlap": overlap,
               "layout_review_documents": sum(d["requires_layout_review"] for d in documents),
               "contacts_preserved": True, "personal_names_masked": True,
               "privacy_policy": "mask_names_preserve_contacts_v1",
               "page_numbering": "PDF physical page, 1-based"}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    def terminate(signum, frame):
        converter.cancel_active_conversion()
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path, help="attachments.csv가 있는 수집 실행 폴더")
    parser.add_argument("--convert-hwp", action="store_true", help="HWP/HWPX를 PDF로 변환한 후 정리")
    args = parser.parse_args()
    try:
        if args.convert_hwp:
            converter.convert_run(args.run_dir)
        result = prepare(args.run_dir)
    except ImportError:
        print("pypdf 설치 필요: python3 -m pip install -r data_pipeline/requirements.txt", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"정리 실패: 입력 폴더/CSV를 확인하세요 ({type(exc).__name__}).", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 일부 문서가 대기 중이면 호출자가 확인할 수 있도록 구분한다.
    return 0 if set(result["statuses"]) <= {"extracted"} and not result["layout_review_documents"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
