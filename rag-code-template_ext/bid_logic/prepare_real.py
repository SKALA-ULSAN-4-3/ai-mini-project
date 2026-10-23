"""실수집 자료에서 평가 입력과 검산용 원문 근거를 준비한다. 정답/검토 승인은 만들지 않는다."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data_pipeline.privacy import mask_personal, official_names
from .shortlist import _budget, _deadline
from .validation import CSV_FIELDS

SCORE_BIDS = ["R26BK01667722", "R26BK01706837", "R26BK01751013", "R26BK01706954", "R26BK01760198"]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(source, pdf_pages, output, assets):
    source, output, assets = map(Path, (source, output, assets))
    output.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    originals = list(csv.DictReader((source / "bids.csv").open(encoding="utf-8-sig")))
    attachments = list(csv.DictReader((source / "attachments.csv").open(encoding="utf-8-sig")))
    if len(originals) != 20 or len({(r["bid_no"], r["bid_order"]) for r in originals}) != 20:
        raise ValueError("고유 공고 20건이 필요합니다.")
    # 이미 사람이 작성한 입력이 있으면 덮어쓰지 않는다.
    profiles_file = output / "profiles.json"
    if profiles_file.exists() and json.loads(profiles_file.read_text()):
        raise ValueError("프로필 입력이 이미 있습니다. 새 출력 폴더를 지정하세요.")
    candidates = json.loads((source / "candidates.json").read_text())["items"]
    names = [name for item in candidates for name in official_names(item)]
    by_key = {(r["bid_no"], r["bid_order"]): r for r in originals}
    for attachment in attachments:
        original = Path(attachment["local_path"])
        target = assets / "raw" / f"{attachment['bid_no']}_{attachment['bid_order']}" / original.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(original, target)
        attachment["local_path"] = str(target)
        attachment["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    write_json(assets / "attachments.json", attachments)
    write_json(output / "source-manifest.json", [
        {k: a[k] for k in ("bid_no", "bid_order", "file_name", "url", "sha256")}
        for a in attachments])
    normalized = []
    for row in originals:
        related = [a for a in attachments if (a["bid_no"], a["bid_order"]) == (row["bid_no"], row["bid_order"])]
        notice = next((a for a in related if a["file_name"].lower().endswith(".pdf") and
                       any(w in a["file_name"] for w in ("공고문", "공고서"))), related[0])
        deadline = _deadline(row)
        item = {field: "" for field in CSV_FIELDS}
        item.update(bid_no=row["bid_no"], revision=row["bid_order"], title=row["title"], agency=row["agency"],
                    published_at=row["published_at"][:10], budget=str(_budget(row)),
                    deadline=deadline.isoformat() if deadline else "", filename=notice["file_name"], url=notice["url"])
        for field in ("regions", "industries", "licenses", "company_sizes", "certs"):
            item[field] = "null"  # 원문 자격을 단순 배열로 임의 확정하지 않는다.
        if row["bid_no"]=="R26BK01760198":
            item["regions"]='["제주"]'  # 공고문 PDF p.2~3의 지역제한·소재지 조건을 직접 확인.
        normalized.append(item)
    with (output / "bids.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(normalized)
    profiles = []
    for identifier, region, keywords, credit, amount, owned in (
        ("seoul_web", "서울", ["홈페이지", "웹 서비스", "콘텐츠관리", "포털"], "AA0", 100000000,
         ["사업자등록증 사본", "소프트웨어사업자 신고확인서", "신용평가등급 확인서"]),
        ("ulsan_data", "울산", ["정보시스템", "데이터 연계", "기능 개발", "업무 시스템"], "BB0", 40000000,
         ["사업자등록증 사본", "직접생산확인증명서"]),
        ("jeju_campus", "제주", ["대학", "학사", "학습관리", "학생", "Axis 프레임워크"], "B0", 20000000, [])):
        profiles.append({"id": identifier, "fictional": True, "industry": "SW", "licenses": ["SW"],
                         "region": region, "company_size": "중소기업", "certs": [], "budget_min": 30000000,
                         "budget_max": 500000000, "keywords": keywords, "credit_rating": credit,
                         "credit_rating_issued_at": "2026-07-01", "credit_rating_valid_until": "2027-07-01",
                         "owned_docs": owned, "track_records": [{"completed_at": "2025-06-01", "category": "Axis 대학 정보화",
                         "summary": "Axis 프레임워크 기반 대학 학사정보시스템 구축", "amount": amount, "amount_unit": "KRW"}]})
    write_json(profiles_file, profiles)
    write_json(output / "manifest.json", {"schema_version": 1, "dataset_kind": "real", "from": "2026-08-01",
        "to": "2026-10-07", "now": "2026-10-07T16:00:00+09:00", "ranking_input_kind": "unmeasured",
        "embedding_model": None, "index_version": None, "targets": {"bids": 20, "profiles": 3, "score_bids": 5},
        "evaluation_mode": "historical_replay", "notes": "과거 공고 고정 시각 재생. 현재 유효 입찰 추천 아님. 자격 제한 미확인은 null.",
        "score_bid_nos": SCORE_BIDS})
    blocks = []
    pdf_rows = [json.loads(line) for line in Path(pdf_pages).read_text().splitlines()]
    for row in pdf_rows:
        attachment = next(a for a in attachments if (a["bid_no"], a["file_name"]) == (row["bid_no"], row["filename"]))
        block = {"source": {k: row[k] for k in ("bid_no", "revision", "filename", "page", "url")},
                 "text": mask_personal(row["text"], names)}
        block["source"].update(sha256=attachment["sha256"], collected_at=by_key[(row["bid_no"],row["revision"])]["collected_at"])
        blocks.append(block)
    for a in attachments:
        if not a["file_name"].endswith(".hwpx") or "제안요청서" not in a["file_name"]:
            continue
        with zipfile.ZipFile(a["local_path"]) as archive:
            for section in sorted(archive.namelist()):
                if not section.startswith("Contents/section") or not section.endswith(".xml"):
                    continue
                tree = ET.fromstring(archive.read(section))
                for i, node in enumerate(tree.iter()):
                    if not node.tag.endswith("}tbl"):
                        continue
                    text = " ".join(n.text or "" for n in node.iter() if n.tag.endswith("}t"))
                    if len(text) > 18000 or not ("평가항목" in text and "배점" in text or "신용평가등급" in text and "CCC" in text):
                        continue
                    rows = [" | ".join(" ".join(t.text or "" for t in cell.iter() if t.tag.endswith("}t"))
                                        for cell in row if cell.tag.endswith("}tc")) for row in node if row.tag.endswith("}tr")]
                    blocks.append({"source": {"bid_no": a["bid_no"], "revision": a["bid_order"], "filename": a["file_name"],
                        "page": None, "locator": f"{section}#element-{i}", "url": a["url"], "sha256": a["sha256"]},
                        "text": mask_personal("\n".join(rows), names)})
    for i, block in enumerate(blocks, 1):
        block["id"] = i
    write_json(assets / "evidence.json", blocks)
    print(f"Prepared {len(normalized)} bids, {len(profiles)} fictional profiles, {len(blocks)} source blocks")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--pdf-pages", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evaluation/real"))
    parser.add_argument("--assets", type=Path, default=ROOT / "data/evaluation-source-20261023")
    args = parser.parse_args()
    prepare(args.source, args.pdf_pages, args.output, args.assets)
