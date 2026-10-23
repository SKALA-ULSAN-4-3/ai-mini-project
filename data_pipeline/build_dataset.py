"""공고문 기반 후보 준비와 사용자 선택 후 전체 첨부 수신을 분리한다."""
import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import shutil
import re

from project_env import load_env

from . import g2b_client as collector
from .convert_documents import convert_rhwp
from .bid_workflow import prepare_discovery, select_bid, latest_notices, is_active_notice
from .common import DEFAULT_DATASET, KST, read_csv, read_json, read_jsonl, write_json, write_jsonl, DOWNLOAD_SUCCESS, TEXT_READY, HWP_SUFFIXES
from .ingest import ingest_sources
from .prepare_documents import prepare, extract_contacts, extract_deadline, extract_deadlines, region_requirement


def collect_dataset(output, start, end, count=20, queries=None, candidate_limit=120,
                    search_only=False, profile=None, rhwp=None):
    """API 조회 결과에서 공고문만 준비한다. 전체 첨부는 사용자 선택 후 수신한다."""
    if start > end or not 1 <= count <= 100 or candidate_limit < 1:
        raise ValueError("조회 기간 또는 수집 건수를 확인하세요.")
    output = Path(output).resolve()
    queries = list(dict.fromkeys(q.strip() for q in (queries or ["시스템", "개발", "소프트웨어"])))
    if not all(queries):
        raise ValueError("목록 탐색어는 비워 둘 수 없습니다.")
    output.mkdir(parents=True, exist_ok=True)
    cache = output / "candidates.json"
    saved = read_json(cache) if cache.exists() else {}
    request = saved.get("request", {})
    same = (request.get("start") == str(start) and request.get("end") == str(end)
            and request.get("queries", ["시스템", "개발", "소프트웨어"]) == queries
            and request.get("candidate_limit", 120) == candidate_limit)
    if same:
        items = saved["items"]
    else:
        load_env()
        key = os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
        if not key:
            raise ValueError("DATA_GO_KR_SERVICE_KEY 설정 필요")
        items, truncated = collector.search_candidates(key, start, end, queries, candidate_limit)
        request = dict(start=str(start), end=str(end), queries=queries, candidate_limit=candidate_limit,
                       collected_at=datetime.now(KST).isoformat(), page_limit_reached=truncated)
        write_json(cache, {"request": request, "items": items})
    latest = latest_notices(items)
    active = [item for item in items if is_active_notice(item, latest)][:count]
    # 원본 후보 캐시는 보존하고 이번 탐색 대상만 별도 디렉터리에 둔다.
    discovery = output / "discovery"
    discovery.mkdir(exist_ok=True)
    write_json(discovery / "candidates.json", {"request": request, "items": active})
    if profile is None and (discovery / "company_profile.json").exists():
        profile = read_json(discovery / "company_profile.json")
    result = prepare_discovery(discovery, profile, search_only, rhwp)
    print(f"탐색 폴더: {discovery}")
    print(f"공고 {len(result['items'])}건 / 본문 일치 {len(result['recommended_bid_ids'])}건 / 전체 첨부 선택 대기")
    return discovery


def _enrich_row(row, item, own):
    """한 공고의 원문 근거·연락처·일정을 CSV 필드로 옮긴다."""
    text = "\n".join(p["text"] for p in own)
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


def enrich(output):
    output = Path(output).resolve()
    rows = read_csv(output / "bids.csv")
    items = {(str(i["bidNtceNo"]), str(i.get("bidNtceOrd") or "000")): i
             for i in read_json(output / "candidates.json")["items"]}
    pages = read_jsonl(output / "processed/pages.jsonl")
    fields = list(collector.BID_FIELDS) + ["industry_restriction", "region_restriction", "joint_supply",
                                          "file_names", "contacts", "metadata_evidence", "metadata_needs_review", "region_status", "deadline_schedule"]
    rows = [{key: value for key, value in row.items() if key in fields} for row in rows]
    for row in rows:
        key = (row["bid_no"], row["bid_order"])
        own = [page for page in pages if (page["bid_no"], page["bid_order"]) == key]
        _enrich_row(row, items[key], own)
    collector.write_csv(output / "bids.csv", fields, rows)
    _write_source_table(output, rows)
    return rows


def _write_source_table(output, rows):
    lines = ["# 입찰공고 데이터 출처표", "", "원본은 보존합니다. 적재 텍스트의 이름·식별번호는 마스킹하고 공개 전화번호·이메일은 보존합니다.",
             "", "| 공고번호·차수 | 공고명 | 공고일 | 원문 URL | 수집일 | PDF 파일 |", "|---|---|---|---|---|---|"]
    for row in rows:
        cells = [row["bid_no"]+"_"+row["bid_order"], row["title"], row["published_at"],
                 row["detail_url"], row["collected_at"], row["file_names"]]
        lines.append("| " + " | ".join(str(c).replace("|", ", ").replace("\n", " ") for c in cells) + " |")
    (output / "README.md").write_text("\n".join(lines)+"\n")


def export_pdf20(output):
    """공고별 대표 공고문 한 개를 별도 폴더에 복사하고 출처를 기록한다."""
    output = Path(output).resolve()
    documents = read_jsonl(output / "processed/documents.jsonl")
    rows = read_csv(output / "bids.csv")
    target = output / "pdf20"
    target.mkdir(exist_ok=True)
    previous = read_jsonl(target / "manifest.jsonl") if (target/"manifest.jsonl").exists() else []
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
    parser.add_argument("--candidate-limit", type=int, default=120, help="API 목록 후보 조회 수")
    parser.add_argument("--search-only", action="store_true", help="선별 목록·링크만 기록. 첨부 요청·후처리 안 함")
    parser.add_argument("--rhwp", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--ingest", action="store_true", help="PDF와 공식 웹 주제 5개를 FAISS에 적재")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--profile", type=Path, help="공고문 본문 사전 분류에 사용하는 기업 프로필 JSON")
    parser.add_argument("--select-bid", action="append", help="사용자가 선택한 공고번호_차수; 지정한 공고만 전체 첨부 수신")
    args = parser.parse_args()
    if not args.prepare_only:
        if args.select_bid:
            if args.search_only:
                parser.error("--search-only와 --select-bid는 함께 사용할 수 없습니다.")
            discovery = args.output if (args.output / "bid_list.json").exists() else args.output / "discovery"
            failed = 0
            for bid_id in args.select_bid:
                result = select_bid(discovery, bid_id)
                failed += sum(r["status"] == "failed" for r in result["attachments"])
                print(f"선택 공고 {bid_id}: 전체 첨부 {len(result['attachments'])}개")
            return 2 if failed else 0
        if args.ingest:
            parser.error("초기 탐색에서는 자동 적재하지 않습니다. 평가·선택 단계와 분리해 적재 명령을 사용하세요.")
        profile = read_json(args.profile) if args.profile else None
        discovery = collect_dataset(args.output, args.start, args.end, args.count, queries=args.query,
                        candidate_limit=args.candidate_limit, search_only=args.search_only,
                        profile=profile, rhwp=args.rhwp)
        listing = read_json(discovery / "bid_list.json")
        return 2 if not args.search_only and any(r["notice_status"] not in TEXT_READY
                                                for r in listing["items"]) else 0
    if args.select_bid or args.search_only or args.profile:
        parser.error("--prepare-only는 기존 오프라인 자료 후처리 전용입니다.")
    needs_conversion = any(r.get("selected", "").lower() == "true" and r.get("status") in DOWNLOAD_SUCCESS
                           and Path(r.get("local_path", "")).suffix.lower() in HWP_SUFFIXES
                           for r in read_csv(args.output / "attachments.csv"))
    if args.rhwp and needs_conversion:
        convert_rhwp(args.output, args.rhwp)
    result = prepare(args.output)
    enrich(args.output)
    export_pdf20(args.output)
    if args.ingest:
        load_env()
        ingest_sources(args.output, args.embedding_model)
    result = read_json(args.output / "processed/summary.json")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not any(s not in TEXT_READY for s in result["statuses"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
