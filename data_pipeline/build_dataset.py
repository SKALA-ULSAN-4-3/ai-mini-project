"""평가용 20건을 3개월에 나눠 수집하고 변환·전처리·출처표를 재현한다."""
import argparse
import csv
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from . import collect_bids as collector
from .prepare_documents import prepare, read_csv, write_jsonl
from .privacy import extract_contacts
from .metadata import extract_deadline, extract_deadlines, region_requirement

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "corpus"
TERMS = ("소프트웨어", "시스템", "플랫폼", "챗봇", "웹", "인공지능", "정보화", "앱 ")


def collect_dataset(output, start, end, count=20, queries=None, candidate_limit=120, search_only=False, selection_file=None):
    if start > end or not 1 <= count <= 100 or candidate_limit < 1:
        raise ValueError("조회 기간 또는 수집 건수를 확인하세요.")
    output = Path(output).resolve()
    queries = list(dict.fromkeys(q.strip() for q in (queries or ["시스템", "개발", "소프트웨어"])))
    if not all(queries):
        raise ValueError("목록 탐색어는 비워 둘 수 없습니다.")
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "candidates.json"
    saved = json.loads(cache.read_text()) if cache.exists() else {}
    same_request = (saved.get("request", {}).get("start") == str(start)
                    and saved.get("request", {}).get("end") == str(end)
                    and saved.get("request", {}).get("queries", ["시스템", "개발", "소프트웨어"]) == queries
                    and saved.get("request", {}).get("candidate_limit", 120) == candidate_limit)
    if same_request:
        items = saved["items"]
    else:
        collector.load_env()
        key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
        if not key:
            raise RuntimeError("DATA_GO_KR_SERVICE_KEY 설정 필요")
        months, current = [], date(start.year, start.month, 1)
        while current <= end:
            following = date(current.year + current.month // 12, current.month % 12 + 1, 1)
            from datetime import timedelta
            months.append((max(start, current), min(end, following - timedelta(days=1))))
            current = following
        items = []
        for first, last in months:
            batch, _ = collector.search_candidates(key, first, last, queries, candidate_limit)
            items.extend(batch)
        items = list({(i["bidNtceNo"], i.get("bidNtceOrd", "000")): i for i in items}.values())
        cache.write_text(json.dumps({"request": {"start": str(start), "end": str(end), "queries": queries,
                                                  "candidate_limit": candidate_limit}, "items": items},
                                    ensure_ascii=False, indent=2))
    usable = []
    reports = []
    latest = {}
    for item in sorted(items, key=lambda i: str(i.get("bidNtceOrd") or "000").zfill(5)):
        latest[item["bidNtceNo"]] = item
    for item in items:
        title = item.get("bidNtceNm", "")
        words = queries
        reason = "검색 및 SW 개발 자료 선정 기준"
        if any(w in str(item.get("ntceKindNm", "")) for w in ("취소", "철회")):
            words, reason = [], "취소·철회 공고"
        report = collector.notice_row(item, words, saved.get("request", {}).get("collected_at", ""))
        report.update(selected=False, selection_reason=reason)
        reports.append(report)
        if latest[item["bidNtceNo"]] is not item:
            report["selection_reason"] = "정정 공고의 이전 차수"
            continue
        if not words:
            continue
        if (not any(t in title for t in TERMS) or not any(t in title for t in ("개발", "구축", "고도화", "기능개선", "기능 개선"))
                or any(t in title for t in ("취소", "철회", "구매", "물품", "유지보수", "유지관리", "감리", "장비"))
                or not any(Path(n).suffix.lower() in (".pdf", ".hwp", ".hwpx") for n, _ in collector.attachments(item))):
            report["selection_reason"] = "개발·구축 공고 또는 지원 첨부 형식 조건 불일치"
            continue
        usable.append(item)
    # 같은 공고번호의 정정 차수는 가장 최근 차수만 사용한다.
    unique = {}
    for item in sorted(usable, key=lambda i: str(i.get("bidNtceOrd") or "000")):
        unique[item["bidNtceNo"]] = item
    usable = list(unique.values())
    # 월별 round robin으로 선택. 특정 주/월에 20건이 편중되지 않는다.
    groups = {}
    for item in usable:
        groups.setdefault(item.get("bidNtceDt", "")[:7], []).append(item)
    ordered = []
    while any(groups.values()):
        for month in sorted(groups):
            if groups[month]:
                ordered.append(groups[month].pop(0))
    selected_path = output / "selection.json"
    by_id = {f"{i['bidNtceNo']}_{i.get('bidNtceOrd') or '000'}": i for i in usable}
    selected_ids = json.loads(selected_path.read_text()) if selected_path.exists() else []
    if selection_file:
        selected_ids = json.loads(Path(selection_file).read_text(encoding="utf-8"))["bid_ids"]
        if len(selected_ids) != count or len(set(selected_ids)) != count:
            raise ValueError("검수 목록의 고유 공고 수와 --count가 다릅니다.")
        absent = [k for k in selected_ids if k not in by_id]
        if absent:
            raise ValueError("검수 목록이 검색 조건 또는 최신 차수 조건을 통과하지 못했습니다: " + ", ".join(absent))
        selected = [by_id[k] for k in selected_ids]
        selected_path.write_text(json.dumps(selected_ids))
    elif same_request and len(selected_ids) == count and all(k in by_id for k in selected_ids):
        selected = [by_id[k] for k in selected_ids]
    else:
        selected = ordered[:count]
        selected_path.write_text(json.dumps([f"{i['bidNtceNo']}_{i.get('bidNtceOrd') or '000'}" for i in selected]))
    selected_keys = {(i["bidNtceNo"], str(i.get("bidNtceOrd") or "000")) for i in selected}
    for report in reports:
        report["selected"] = (report["bid_no"], report["bid_order"]) in selected_keys
        if not report["selected"] and report["selection_reason"] == "검색 및 SW 개발 자료 선정 기준":
            report["selection_reason"] = "조건 충족 후 최대 다운로드 공고 수 초과"
    collector.write_csv(output / "candidates.csv", collector.CANDIDATE_FIELDS, reports)
    selection_report = {"candidates": len(items), "usable": len(usable), "selected": len(selected),
                        "excluded": len(items)-len(selected), "target_count": count,
                        "queries": queries, "search_only": search_only,
                        "download_policy": "조건 일치 공고만 첨부 URL 요청; 부족해도 조건 완화하지 않음"}
    (output / "selection_report.json").write_text(json.dumps(selection_report, ensure_ascii=False, indent=2))
    print(f"목록 {len(items)}건 → 조건 충족 {len(usable)}건 → 첨부 대상 {len(selected)}건", flush=True)
    if search_only:
        # 목록 확인 때문에 이미 받은 파일의 상태/경로를 지우지 않는다.
        return output
    stamp = datetime.now().astimezone().isoformat()
    rows, files = [], []
    previous_bids = {(r["bid_no"], r["bid_order"]): r for r in read_csv(output / "bids.csv")} if (output / "bids.csv").exists() else {}
    previous = {r["url"]: r for r in read_csv(output / "attachments.csv")} if (output / "attachments.csv").exists() else {}
    for item in selected:
        row = collector.notice_row(item, queries, stamp)
        if same_request:
            row["collected_at"] = previous_bids.get((row["bid_no"], row["bid_order"]), {}).get("collected_at") or stamp
        rows.append(row)
        for i, (name, url) in enumerate(collector.attachments(item), 1):
            if Path(name).suffix.lower() not in (".pdf", ".hwp", ".hwpx") or any(
                    word in name for word in ("사칭", "사기 주의", "사기주의")):
                continue
            target = output / "raw" / f"{row['bid_no']}_{row['bid_order']}" / f"{i:02}_{collector.safe_name(name)}"
            record = dict(bid_no=row["bid_no"], bid_order=row["bid_order"], file_name=name, url=url,
                          selected=True, local_path=str(target), status="listed", error="")
            try:
                if search_only:
                    record["local_path"] = ""
                elif target.exists() and target.stat().st_size and previous.get(url, {}).get("status") in ("downloaded", "existing"):
                    record["status"] = "existing"
                else:
                    collector.download_file(url, target)
                    record["status"] = "downloaded"
                if not search_only:
                    print(f"첨부 확보: {row['bid_no']} / {name}", flush=True)
            except collector.CollectionError as exc:
                record.update(status="failed", error=str(exc))
            files.append(record)
            collector.write_csv(output / "attachments.csv", collector.FILE_FIELDS, files)
        related = [f for f in files if f["bid_no"] == row["bid_no"]]
        row["downloaded_files"] = sum(f["status"] in ("downloaded", "existing") for f in related)
        row["failed_files"] = sum(f["status"] == "failed" for f in related)
        collector.write_csv(output / "bids.csv", collector.BID_FIELDS, rows)
    if not selected:
        collector.write_csv(output / "bids.csv", collector.BID_FIELDS, [])
        collector.write_csv(output / "attachments.csv", collector.FILE_FIELDS, [])
    by_key = {(row["bid_no"], row["bid_order"]): row for row in rows}
    for report in reports:
        current = by_key.get((report["bid_no"], report["bid_order"]), {})
        report["downloaded_files"] = current.get("downloaded_files", 0)
        report["failed_files"] = current.get("failed_files", 0)
    collector.write_csv(output / "candidates.csv", collector.CANDIDATE_FIELDS, reports)
    return output


def convert_rhwp(output, executable):
    """기존 LibreOffice 작업과 별도로 실행 가능. 원본/변환 해시로 재개한다."""
    output = Path(output).resolve()
    previous = {}
    manifest = output / "conversions.jsonl"
    if manifest.exists():
        previous = {r["original_path"]: r for r in map(json.loads, manifest.read_text().splitlines())}
    records = []
    for row in read_csv(output / "attachments.csv"):
        source = Path(row["local_path"])
        if source.suffix.lower() not in (".hwp", ".hwpx") or row["status"] not in ("downloaded", "existing"):
            continue
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        target = output / "converted" / hashlib.sha256(str(source).encode()).hexdigest()[:16] / (source.stem + ".pdf")
        old = previous.get(str(source), {})
        record = dict(bid_no=row["bid_no"], bid_order=row["bid_order"], original_path=str(source),
                      original_sha256=digest, pdf_path=str(target), pdf_sha256="", status="failed",
                      engine="rhwp", requires_layout_review=True, error="")
        try:
            if not (target.exists() and old.get("original_sha256") == digest and
                    old.get("pdf_sha256") == hashlib.sha256(target.read_bytes()).hexdigest()):
                target.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run([str(executable), "export-pdf", str(source), "-o", str(target),
                                         "--fallback-sans", "Apple SD Gothic Neo", "--fallback-serif", "AppleMyungjo"],
                                        capture_output=True, text=True, timeout=120)
                if result.returncode or not target.exists():
                    raise RuntimeError("HWP 변환 실패")
            from pypdf import PdfReader
            reader = PdfReader(target)
            if not reader.pages or not any((p.extract_text() or "").strip() for p in reader.pages):
                raise RuntimeError("변환 PDF 텍스트 없음")
            record.update(status="converted", pdf_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
            print(f"변환 완료: {source.name}", flush=True)
        except Exception as exc:
            record["error"] = str(exc)[:200]
        records.append(record)
        write_jsonl(manifest, records)
    return records


def enrich(output):
    output = Path(output).resolve()
    rows = read_csv(output / "bids.csv")
    items = {(str(i["bidNtceNo"]), str(i.get("bidNtceOrd") or "000")): i
             for i in json.loads((output / "candidates.json").read_text())["items"]}
    pages = [json.loads(line) for line in (output / "processed/pages.jsonl").read_text().splitlines()]
    fields = list(collector.BID_FIELDS) + ["industry_restriction", "region_restriction", "joint_supply",
                                          "file_names", "contacts", "metadata_evidence", "metadata_needs_review", "region_status", "deadline_schedule"]
    rows = [{key: value for key, value in row.items() if key in fields} for row in rows]
    for row in rows:
        own = [p for p in pages if (p["bid_no"], p["bid_order"]) == (row["bid_no"], row["bid_order"])]
        item = items[(row["bid_no"], row["bid_order"])]
        text = "\n".join(p["text"] for p in own)
        import re
        evidence = {}
        for key, pattern in {
            "industry_restriction": r"[^\n]*(?:소프트웨어사업자|업종코드|업종제한|입찰참가자격)[^\n]*(?:\n[^\n]+){0,3}",
            "region_restriction": r"[^\n]*(?:지역제한|본점\s*소재지|주된\s*영업소|지역\s*제한)[^\n]*(?:\n[^\n]+){0,2}",
            "joint_supply": r"[^\n]*(?:공동수급|공동계약|공동이행|분담이행)[^\n]*(?:\n[^\n]+){0,2}",
            "deadline": r"[^\n]*(?:입찰.*마감|제안서.*제출.*기한|제안서.*마감)[^\n]*(?:\n[^\n]+){0,2}",
        }.items():
            for page in own:
                match = re.search(pattern, page["text"])
                if match:
                    evidence[key] = {"text": match.group()[:700], "file_name": page["file_name"],
                                     "page": page["page"], "source_url": page["source_url"]}
                    break
            if key != "deadline":
                row[key] = evidence.get(key, {}).get("text") or "원문 확인 필요"
        if item.get("cmmnSpldmdMethdNm"):
            row["joint_supply"] = item["cmmnSpldmdMethdNm"]
            evidence["joint_supply_api"] = {"field": "cmmnSpldmdMethdNm", "value": row["joint_supply"]}
        if not row.get("deadline") or row["deadline"] == "원문 확인 필요":
            deadline, source = extract_deadline(own)
            row["deadline"] = deadline or "원문 확인 필요"
            if source:
                evidence["deadline"] = source
        elif item.get("bidClseDt"):
            evidence["deadline"] = {"text": row["deadline"], "source_url": row["detail_url"],
                                    "field": "OpenAPI.bidClseDt"}
        row["file_names"] = "|".join(dict.fromkeys(p["file_name"] for p in own))
        contacts = extract_contacts(text, item)
        # API에서 받은 연락처도 공고 URL을 함께 보관한다.
        for contact in contacts:
            found = next((p for p in own if contact["value"] in p["text"]), None)
            contact["source"] = ({k: found[k] for k in ("file_name", "page", "source_url")} if found
                                 else {"source_url": row["detail_url"], "field": "OpenAPI担当部署連絡先"})
        row["contacts"] = json.dumps(contacts, ensure_ascii=False)
        row["metadata_evidence"] = json.dumps(evidence, ensure_ascii=False)
        row["metadata_needs_review"] = any(row[k] == "원문 확인 필요" for k in
                                   ("industry_restriction", "region_restriction", "joint_supply", "deadline"))
        notices = [p for p in own if "공고" in p["file_name"] and "사유" not in p["file_name"]]
        region = region_requirement(notices)
        row["region_status"] = region["status"]
        row["region_restriction"] = (" / ".join(region["regions"]) if region["status"]=="restricted"
                                     else "제한 없음(원문 명시)" if region["status"]=="explicit_none"
                                     else "공고문에 지역 조건 명시를 찾지 못함" if region["status"]=="not_stated"
                                     else "지역 조건 문구 상충: 원문 확인 필요")
        evidence["region_restriction"] = region
        row["deadline_schedule"] = json.dumps(extract_deadlines(notices),ensure_ascii=False)
        row["metadata_needs_review"] = row["metadata_needs_review"] or region["status"] in ("not_stated","ambiguous")
        row["metadata_evidence"] = json.dumps(evidence,ensure_ascii=False)
    collector.write_csv(output / "bids.csv", fields, rows)
    lines = ["# 입찰공고 데이터 출처표", "", "원본은 보존합니다. 적재 텍스트의 이름·식별번호는 마스킹하고 공개 전화번호·이메일은 보존합니다.",
             "", "| 공고번호·차수 | 공고명 | 공고일 | 원문 URL | 수집일 | PDF 파일 |", "|---|---|---|---|---|---|"]
    for row in rows:
        cells = [row["bid_no"]+"_"+row["bid_order"], row["title"], row["published_at"],
                 row["detail_url"], row["collected_at"], row["file_names"]]
        lines.append("| " + " | ".join(str(c).replace("|", ", ").replace("\n", " ") for c in cells) + " |")
    (output / "README.md").write_text("\n".join(lines)+"\n")
    return rows


def export_pdf20(output):
    """공고별 대표 공고문 한 개를 별도 폴더에 복사하고 출처를 기록한다."""
    output = Path(output).resolve()
    documents = [json.loads(line) for line in (output / "processed/documents.jsonl").read_text().splitlines()]
    rows = read_csv(output / "bids.csv")
    target = output / "pdf20"
    target.mkdir(exist_ok=True)
    previous = [json.loads(line) for line in (target/"manifest.jsonl").read_text().splitlines()] if (target/"manifest.jsonl").exists() else []
    manifest = []
    for row in rows:
        options = [d for d in documents if d["bid_no"] == row["bid_no"] and d["status"] == "extracted"]
        if not options:
            raise RuntimeError(f"검색 가능한 대표 PDF 없음: {row['bid_no']}")
        options.sort(key=lambda d: ("공고" not in d["file_name"], "사유" in d["file_name"],
                                    d["requires_layout_review"], d["file_name"]))
        chosen = options[0]
        destination = target / f"{row['bid_no']}_{row['bid_order']}.pdf"
        shutil.copy2(chosen["local_path"], destination)
        manifest.append({**chosen, "export_path": str(destination)})
    write_jsonl(target / "manifest.jsonl", manifest)
    keep = {Path(r["export_path"]).resolve() for r in manifest}
    for old in previous:
        path=Path(old.get("export_path", "")).resolve()
        if path.parent==target and path not in keep and path.suffix.lower()==".pdf":
            path.unlink(missing_ok=True)
    # 이전 버전이 남긴 대표 PDF도 관리되는 공고번호 파일명만 정리한다.
    import re
    for path in target.glob("*.pdf"):
        if re.fullmatch(r"R\d{2}BK\d+_\d{3}\.pdf",path.name) and path.resolve() not in keep:
            path.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2026, 8, 1))
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2026, 10, 23))
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--query", action="append", help="공고 목록 탐색어; 기업 선별 조건과 분리")
    parser.add_argument("--candidate-limit", type=int, default=120, help="월별 목록 후보 조회 수")
    parser.add_argument("--search-only", action="store_true", help="선별 목록·링크만 기록. 첨부 요청·후처리 안 함")
    parser.add_argument("--selection-file", type=Path, help="검수한 고정 공고 목록 JSON. 조건 불일치는 오류로 중단")
    parser.add_argument("--rhwp", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--ingest", action="store_true", help="PDF와 공식 웹 주제 5개를 FAISS에 적재")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    args = parser.parse_args()
    if not args.prepare_only:
        collect_dataset(args.output, args.start, args.end, args.count,
                        queries=args.query,
                        candidate_limit=args.candidate_limit, search_only=args.search_only, selection_file=args.selection_file)
    if args.search_only:
        return 0
    needs_conversion = any(r.get("selected", "").lower() == "true" and r.get("status") in ("downloaded", "existing")
                           and Path(r.get("local_path", "")).suffix.lower() in (".hwp", ".hwpx")
                           for r in read_csv(args.output / "attachments.csv"))
    if args.rhwp and needs_conversion:
        convert_rhwp(args.output, args.rhwp)
    elif not args.prepare_only and needs_conversion:
        from .convert_documents import convert_run
        convert_run(args.output)
    result = prepare(args.output)
    enrich(args.output)
    export_pdf20(args.output)
    from .audit_dataset import audit
    reviewed=audit(args.output)
    if reviewed["hard_failures"]:
        print("자동 검수 실패: validation.json을 확인하고 보완한 후 적재하세요.")
        return 2
    if args.ingest:
        from .knowledge import KnowledgeStore, ingest_processed
        from .web_topics import ingest_topics
        collector.load_env()
        ingest_processed(args.output, KnowledgeStore("pdf", model=args.embedding_model))
        ingest_topics(KnowledgeStore("web", model=args.embedding_model))
    result=json.loads((args.output/"processed/summary.json").read_text())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not any(s not in ("extracted", "review_empty_pages") for s in result["statuses"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
