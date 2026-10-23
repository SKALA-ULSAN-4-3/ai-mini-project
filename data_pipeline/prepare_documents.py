"""수집 실행 폴더의 선택된 첨부를 페이지/청크 JSONL로 정리한다.

원본과 연락처를 보존한다. 변환 기록이 있으면 PDF를 사용한다. OCR·임베딩은 수행하지 않는다.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "data_pipeline"

from . import convert_documents as converter
from .common import (read_csv, read_json, read_jsonl, write_json, write_jsonl,
                     file_sha256, DOWNLOAD_SUCCESS, HWP_SUFFIXES)

# 1. 연락처 보존과 개인정보 마스킹
PHONE = re.compile(r"(?<!\d)(?:0\d{1,2}|1[568]\d{2})[- .)]?\s*\d{3,4}[- .]?\d{4}(?!\d)")

EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")

NAME = re.compile(r"((?:담당자|담당직원|성\s*명|대표자|담당관)\s*[:：]?\s*)([가-힣]{2,4})(?=\s|[,(/]|$)")

def mask_personal(text, names=()):
    text = re.sub(r"(?<!\d)\d{6}\s*[-–]\s*[1-8]\d{6}(?!\d)", "[주민번호 비공개]", text)
    text = re.sub(r"(계좌(?:번호)?\s*[:：]\s*)[\d -]{8,}", r"\1[계좌번호 비공개]", text)
    # 연락처를 먼저 보호한다. 이름이 이메일 로컬파트에 포함돼도 보존한다.
    protected = []
    def keep(match):
        protected.append(match.group())
        return f"\ue000{len(protected)-1}\ue001"
    text = EMAIL.sub(keep, text)
    text = PHONE.sub(keep, text)
    for name in sorted(set(names), key=len, reverse=True):
        if name and len(name.strip()) >= 2:
            text = re.sub(r"[ \t]*".join(re.escape(char) for char in name.strip()), "[이름 비공개]", text)
    text = NAME.sub(lambda m: m[1] + "[이름 비공개]" if m[2] not in
                    {"전화", "연락처", "이메일", "문의", "성명", "소속", "직위", "에게", "에게서", "에게는", "통해", "확인", "연락"} else m[0], text)
    text = re.sub(r"(?<![가-힣])([가-힣]{2,4})(팀장|주무관|차장|주임|대리)(?=\s|[,(☎]|$)",
                  r"[이름 비공개]\2", text)
    return re.sub(r"\ue000(\d+)\ue001", lambda m: protected[int(m[1])], text)

def extract_contacts(text, metadata=None):
    metadata = metadata or {}
    result = []
    for kind, regex, key in (("phone", PHONE, "ntceInsttOfclTelNo"),
                              ("email", EMAIL, "ntceInsttOfclEmailAdrs")):
        values = list(dict.fromkeys(([str(metadata[key])] if metadata.get(key) else []) + regex.findall(text)))
        result.extend({"type": kind, "value": value} for value in values)
    extra_email = metadata.get("dminsttOfclEmailAdrs")
    if extra_email and {"type": "email", "value": extra_email} not in result:
        result.append({"type": "email", "value": extra_email})
    return result

def official_names(item):
    return [item[k] for k in ("ntceInsttOfclNm", "exctvNm", "dminsttOfclNm") if item.get(k)]

# 2. 원문 날짜·지역 조건과 출처 추출
def extract_deadlines(pages):
    """등록 마감과 제안서 제출 마감을 구분하고 기간은 종료 일시를 쓴다."""
    labels=[("bid",r"(?:전자)?입찰서(?:제출|접수)?(?:마감일시|제출기간|제출마감일시)"),
            ("proposal",r"제안서(?:및가격입찰서)?(?:제출(?:기간|기한)?|마감)(?:파일|제본)?"),
            ("registration",r"입찰(?:참가신청|참가자격등록마감일시|등록마감)")]
    date_time=r"(20\d{2})[.년/-](\d{1,2})[.월/-](\d{1,2})[.일]?(?:\([가-힣]\))?[~～]?(\d{1,2}):(\d{2})"
    results=[]
    for page in pages:
        text=re.sub(r"\s+","",page["text"])
        for kind,pattern in labels+[("proposal",r"제출기간")]:
            for label in re.finditer(pattern,text):
                if label.group()=="제출기간" and "제안서제출" not in text[max(0,label.start()-300):label.start()]:
                    continue
                rest=text[label.end():label.end()+180]
                found=re.match(r"[:：]?(?:파일|제본)?"+date_time,rest)
                if not found:continue
                second=re.match(r"[~～부터까지]{1,4}"+date_time,rest[found.end():])
                chosen=second if second else found
                groups=chosen.groups()
                try:value=datetime(*(int(g) for g in groups)).strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:continue
                end=label.end()+found.end()+(second.end() if second else 0)
                row=dict(kind=kind,deadline=value,text=text[label.start():end],file_name=page["file_name"],page=page["page"],source_url=page["source_url"])
                if not any(r["kind"]==kind and r["deadline"]==value for r in results):results.append(row)
    return results

def extract_deadline(pages):
    structured=extract_deadlines(pages)
    for kind in ("bid","proposal","registration"):
        values=[r for r in structured if r["kind"]==kind]
        if values:
            row=min(values,key=lambda r:r["deadline"])
            return row["deadline"],row
    patterns = [r"(?:입찰서.{0,12}마감일시|제안서.{0,12}제출기간|제안서.{0,12}제출기한|가격입찰서제출|제안서및가격입찰서제출)",
                r"(?:입찰등록.{0,8}마감|입찰참가신청.{0,8}마감)"]
    date_pattern = r"(20\d{2})[.년/-](\d{1,2})[.월/-](\d{1,2})[.일]?(?:\([월화수목금토일]\))?"
    for pattern in patterns:
        for page in pages:
            compact = re.sub(r"\s+", "", page["text"])
            for label in re.finditer(pattern, compact):
                rest = compact[label.end():label.end()+100]
                found = re.match(r"[:：]?(?:[~～])?" + date_pattern + r".{0,4}?(\d{1,2}):(\d{2})(?:[~～](\d{1,2}):(\d{2}))?", rest)
                if found:
                    year, month, day, hour, minute, end_hour, end_minute = found.groups()
                    try:
                        deadline = datetime(int(year), int(month), int(day), int(end_hour or hour), int(end_minute or minute))
                    except ValueError:
                        continue
                    return deadline.strftime("%Y-%m-%d %H:%M:%S"), {
                        "text": compact[label.start():label.end()+found.end()],
                        "file_name": page["file_name"], "page": page["page"], "source_url": page["source_url"]}
    return "", None

REGIONS = ("서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시",
           "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "강원도", "충청북도",
           "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도", "경상남도", "제주특별자치도")

REGION_ALIASES={"서울":"서울특별시","부산":"부산광역시","경남":"경상남도","경북":"경상북도",
                "경기":"경기도","충남":"충청남도","충북":"충청북도","제주":"제주특별자치도"}

def compact(text):
    return re.sub(r"\s+", "", text)

def evidence(page, quote):
    return {k: page.get(k, "") for k in ("bid_no", "bid_order", "file_name", "page", "source_url")} | {"quote": quote}

def region_requirement(pages):
    results = []
    for p in pages:
        text = compact(p["text"])
        next_page = next((q for q in pages if q["document_id"]==p["document_id"] and q["page"]==p["page"]+1), None)
        searchable = text + (compact(next_page["text"])[:300] if next_page else "")
        # 수요기관/납품 장소/연락처 주소는 지역 참가조건으로 쓰지 않는다.
        for match in re.finditer(r"(?:주된영업소(?:재지)?|본점(?:의)?소재지|본사(?:의)?소재지|지역제한)", text):
            left = max(0, match.start()-140)
            right = min(len(searchable), match.end()+220)
            quote = searchable[left:right]
            if re.search(r"지역제한[:：]?(?:없음|없습니다|해당없음|미적용)", quote):
                results.append({"status": "explicit_none", "regions": [], "source": evidence(p, quote)})
                continue
            tail = searchable[match.end():right]
            regions = [r for r in REGIONS if r in tail]
            bracket=re.match(r"[:：]?[([]([^])]{1,60})[)\]]",tail) if match.group()=="지역제한" else None
            if bracket:
                regions=list(dict.fromkeys(REGION_ALIASES.get(token,token) for token in re.split(r"[,·ㆍ/]|및|또는",bracket[1]) if token in REGION_ALIASES or token in REGIONS))
            if regions and re.search(r"소재|두고|이어야|있는|인업체|지역제한", quote):
                # 하나의 지역명만 발견해도 시·군 제한/여러 지역의 AND·OR는 검토한다.
                results.append({"status": "restricted", "regions": regions, "source": evidence(p, quote),
                                "sources": [evidence(next_page,compact(next_page["text"])[:300])] if next_page and right>len(text) else [],
                                "complex": bool(re.search(r"공동수급|구성원", tail) or any(re.search(re.escape(r)+r"[가-힣]{1,8}[시군구]",tail) for r in regions))})
    if not results:
        return {"status": "not_stated", "regions": [], "source": None,
                "description": "검사한 공고문에서 명시적 지역 참가조건을 찾지 못함. 제한 없음으로 판정하지 않음"}
    # 긍정·부정 문구가 충돌하면 한쪽을 임의로 선택하지 않는다.
    signatures = {(r["status"], tuple(r["regions"])) for r in results}
    if len(signatures) != 1:
        return {"status": "ambiguous", "regions": sorted({region for r in results for region in r['regions']}),
                "sources": [s for r in results for s in [r["source"]]+r.get("sources",[])]}
    return results[0]

# 3. PDF 페이지 추출과 청크 생성
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


def _document_base(row, bid, run_dir):
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
    return base, path


def _resolve_pdf(row, base, path, conversions, document):
    """원본과 변환 해시를 확인한다. 이 단계에서 다운로드나 변환은 하지 않는다."""
    if row.get("status") not in DOWNLOAD_SUCCESS or not path or not path.is_file():
        document["status"] = "download_required"
        return None
    digest = file_sha256(path)
    identity = "|".join((row["bid_no"], row["bid_order"], row.get("url", ""), digest))
    document.update(document_id=hashlib.sha256(identity.encode()).hexdigest()[:24], sha256=digest)
    if path.suffix.lower() in HWP_SUFFIXES:
        conversion = conversions.get(str(path.resolve()), {})
        if not conversion:
            document["status"] = "conversion_required"
            return None
        pdf = Path(conversion.get("pdf_path") or "__missing_pdf__")
        if (conversion.get("status") not in {"converted", "existing"}
                or conversion.get("original_sha256") != digest or not pdf.is_file()
                or file_sha256(pdf) != conversion.get("pdf_sha256")):
            document.update(status="conversion_failed", error=conversion.get("error") or "변환 기록 불일치")
            return None
        path = pdf
        base.update(file_name=pdf.name, local_path=str(pdf), original_sha256=digest,
                    requires_layout_review=True)
        digest = conversion["pdf_sha256"]
        document_id = hashlib.sha256((identity + digest).encode()).hexdigest()[:24]
        document.update(base, document_id=document_id, sha256=digest)
    if path.suffix.lower() != ".pdf":
        document["status"] = "unsupported_format"
        return None
    return path


def _read_pdf(path, reader_factory, document):
    try:
        with path.open("rb") as source:
            reader = reader_factory(source)
            if reader.is_encrypted and not reader.decrypt(""):
                document["status"] = "password_required"
                return None
            return [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        document.update(status="extraction_failed", error=type(exc).__name__)
        return None


def _page_records(base, document, texts, item, chunk_size, overlap):
    pages, chunks = [], []
    for page_no, text in enumerate(texts, 1):
        contacts = extract_contacts(text)
        text = mask_personal(text, official_names(item))
        metadata = {**base, "document_id": document["document_id"], "sha256": document["sha256"],
                    "page": page_no, "contacts": contacts,
                    "privacy_policy": "mask_names_preserve_contacts_v1",
                    "citation": f"{base['file_name']} p.{page_no}",
                    "document_status": document["status"]}
        pages.append({**metadata, "text": text})
        if not text.strip():
            continue
        for index, (start, end, part) in enumerate(split_text(text, chunk_size, overlap), 1):
            chunks.append({**metadata, "chunk_id": f"{document['document_id']}-p{page_no}-c{index}",
                           "char_start": start, "char_end": end, "text": part})
    return pages, chunks


def _prepare_attachment(row, bid, item, conversions, run_dir, reader_factory, chunk_size, overlap):
    base, path = _document_base(row, bid, run_dir)
    document = {**base, "document_id": "", "sha256": "", "status": "",
                "page_count": 0, "empty_pages": [], "chunk_count": 0, "error": ""}
    path = _resolve_pdf(row, base, path, conversions, document)
    if path is None:
        return document, [], []
    texts = _read_pdf(path, reader_factory, document)
    if texts is None:
        return document, [], []
    empty_pages = [i for i, text in enumerate(texts, 1) if not text.strip()]
    status = ("empty_text" if not any(text.strip() for text in texts)
              else "review_empty_pages" if empty_pages else "extracted")
    document.update(page_count=len(texts), empty_pages=empty_pages, status=status)
    pages, chunks = _page_records(base, document, texts, item, chunk_size, overlap)
    document["chunk_count"] = len(chunks)
    return document, pages, chunks


def prepare(run_dir, chunk_size=1000, overlap=200, reader_factory=None):
    """선택 첨부만 읽어 원본 검증 → PDF 읽기 → 마스킹 → 페이지/청크 저장."""
    list(split_text("test", chunk_size, overlap))
    run_dir = Path(run_dir).resolve()
    attachments = read_csv(run_dir / "attachments.csv")
    bids = {(r["bid_no"], r["bid_order"]): r for r in read_csv(run_dir / "bids.csv")}
    candidate_file = run_dir / "candidates.json"
    items = read_json(candidate_file).get("items", []) if candidate_file.exists() else []
    api_items = {(str(r["bidNtceNo"]), str(r.get("bidNtceOrd") or "000")): r for r in items}
    manifest = run_dir / "conversions.jsonl"
    conversions = {r["original_path"]: r for r in read_jsonl(manifest)} if manifest.is_file() else {}
    if reader_factory is None:
        # PDF 의존성은 실제 전처리 시에만 필요하다. CLI --help는 설치 전에도 제공한다.
        from pypdf import PdfReader
        reader_factory = PdfReader
    pages, chunks, documents = [], [], []
    for row in attachments:
        if row.get("selected", "").lower() != "true":
            continue
        key = (row["bid_no"], row["bid_order"])
        document, own_pages, own_chunks = _prepare_attachment(
            row, bids.get(key, {}), api_items.get(key, {}), conversions, run_dir,
            reader_factory, chunk_size, overlap)
        documents.append(document)
        pages.extend(own_pages)
        chunks.extend(own_chunks)
    return _save_prepared(run_dir, documents, pages, chunks, chunk_size, overlap)


def clean_chunks(pages, chunks):
    """같은 공고 안의 충분히 긴 동일 페이지만 병합. 모든 대체 출처는 보존."""
    groups = defaultdict(list)
    for page in pages:
        text = re.sub(r"\s+", "", page["text"])
        key = (page["bid_no"], page["bid_order"], text) if len(text) >= 150 else (page["document_id"], page["page"])
        groups[key].append(page)
    canonical, aliases, duplicates = set(), {}, []
    for group in groups.values():
        group.sort(key=lambda p: (p.get("requires_layout_review", False), p["file_name"], p["page"]))
        chosen = group[0]
        key = (chosen["document_id"], chosen["page"])
        canonical.add(key)
        sources = [{k: p.get(k, "") for k in ("file_name", "page", "source_url", "document_id")} for p in group]
        aliases[key] = sources
        if len(group)>1:
            duplicates.append({"kept": sources[0], "equivalent_sources": sources[1:], "bid_no": chosen["bid_no"]})
    result = []
    for chunk in chunks:
        key = (chunk["document_id"], chunk["page"])
        if key in canonical:
            result.append({**chunk, "equivalent_sources": aliases[key]})
    return result, duplicates



def _save_prepared(run_dir, documents, pages, chunks, chunk_size, overlap):
    raw_chunk_count = len(chunks)
    chunks, duplicate_pages = clean_chunks(pages, chunks)
    output = run_dir / "processed"
    output.mkdir(exist_ok=True)
    for name, records in (("pages", pages), ("chunks", chunks), ("documents", documents)):
        write_jsonl(output / f"{name}.jsonl", records)
    pending = [d for d in documents if d["status"] != "extracted" or d["requires_layout_review"]]
    write_jsonl(output / "needs_attention.jsonl", pending)
    counts = {}
    for document in documents:
        status = document["status"]
        counts[status] = counts.get(status, 0) + 1
    summary = {"prepared_at": datetime.now(timezone.utc).isoformat(), "run_dir": str(run_dir),
               "documents": len(documents), "pages": len(pages), "chunks": len(chunks),
               "raw_chunks": raw_chunk_count, "duplicate_page_groups": len(duplicate_pages),
               "statuses": counts, "chunk_size": chunk_size, "overlap": overlap,
               "layout_review_documents": sum(d["requires_layout_review"] for d in documents),
               "contacts_preserved": True, "personal_names_masked": True,
               "privacy_policy": "mask_names_preserve_contacts_v1",
               "page_numbering": "PDF physical page, 1-based"}
    write_json(output / "summary.json", summary)
    return summary


def main():
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
