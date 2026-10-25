"""공식 평가 목록만 다운로드·해시 검증하고 추천 테스트용 원문 근거를 재생성한다."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET
import zipfile

from .collect_bids import ROOT, CollectionError, allowed_download, download_file, safe_name
from .privacy import mask_personal

DATASET = ROOT / "rag-code-template_ext/evaluation/real"
ASSETS = ROOT / "data/evaluation-source-20261023"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def official_sources(dataset):
    with (dataset / "bids.csv").open(encoding="utf-8-sig") as stream:
        bids = list(csv.DictReader(stream))
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    sources = json.loads((dataset / "source-manifest.json").read_text(encoding="utf-8"))
    keys = {(b["bid_no"], b["revision"]) for b in bids}
    if len(bids) != manifest["targets"]["bids"] or len(keys) != len(bids):
        raise ValueError("평가 공고 수/중복이 manifest와 다릅니다.")
    seen, paths = set(), set()
    for row in sources:
        key = (row["bid_no"], row["bid_order"])
        query = parse_qs(urlparse(row["url"]).query)
        if (key not in keys or not re.fullmatch(r"[A-Za-z0-9]+", key[0])
                or not re.fullmatch(r"\d{3}", key[1])):
            raise ValueError("평가 목록 외 공고 또는 다른 차수입니다.")
        if (not allowed_download(row["url"]) or query.get("bidPbancNo") != [key[0]]
                or query.get("bidPbancOrd") != [key[1]]):
            raise ValueError("원문 URL의 공고번호/차수가 다릅니다.")
        if not re.fullmatch(r"[a-f0-9]{64}", row.get("sha256", "")):
            raise ValueError("원문 SHA-256 누락/형식 오류: 3번과 기준 해시를 확인하세요.")
        identity = (*key, row["file_name"])
        relative = (f"{key[0]}_{key[1]}", safe_name(row["file_name"]))
        if identity in seen or relative in paths:
            raise ValueError("원문 파일명 중복/저장 경로 충돌입니다.")
        seen.add(identity); paths.add(relative)
    if {s[:2] for s in seen} != keys:
        raise ValueError("원문이 없는 평가 공고가 있습니다.")
    for bid in bids:
        if not any((a["bid_no"], a["bid_order"], a["file_name"], a["url"]) ==
                   (bid["bid_no"], bid["revision"], bid["filename"], bid["url"]) for a in sources):
            raise ValueError("bids.csv의 대표 원문과 source-manifest가 다릅니다.")
    return sources


def build_evidence(attachments):
    from pypdf import PdfReader
    blocks = []
    for row in attachments:
        path = Path(row["local_path"])
        source = dict(bid_no=row["bid_no"], revision=row["bid_order"],
                      filename=row["file_name"], url=row["url"], sha256=row["sha256"])
        if path.suffix.lower() == ".pdf":
            for number, page in enumerate(PdfReader(path).pages, 1):
                blocks.append({"source": {**source, "page": number},
                               "text": mask_personal(page.extract_text() or "")})
        elif path.suffix.lower() == ".hwpx" and "제안요청서" in row["file_name"]:
            with zipfile.ZipFile(path) as archive:
                for section in sorted(archive.namelist()):
                    if not section.startswith("Contents/section") or not section.endswith(".xml"):
                        continue
                    for index, node in enumerate(ET.fromstring(archive.read(section)).iter()):
                        if not node.tag.endswith("}tbl"):
                            continue
                        text = " ".join(n.text or "" for n in node.iter() if n.tag.endswith("}t"))
                        if len(text) > 18000 or not ("평가항목" in text and "배점" in text or
                                                    "신용평가등급" in text and "CCC" in text):
                            continue
                        lines = [" | ".join(" ".join(t.text or "" for t in cell.iter()
                                                      if t.tag.endswith("}t"))
                                            for cell in tr if cell.tag.endswith("}tc"))
                                 for tr in node if tr.tag.endswith("}tr")]
                        blocks.append({"source": {**source, "page": None,
                                                  "locator": f"{section}#element-{index}"},
                                       "text": mask_personal("\n".join(lines))})
    for number, block in enumerate(blocks, 1):
        block["id"] = number
    return blocks


def collect(dataset=DATASET, assets=ASSETS, *, verify_only=False, reuse_manifest=None):
    sources = official_sources(dataset)
    reusable = {}
    if reuse_manifest:
        with reuse_manifest.open(encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                reusable[(row["bid_no"], row["bid_order"], row["file_name"], row["url"])] = Path(row["local_path"])
    attachments, failures = [], []
    for row in sources:
        target = assets / "raw" / f"{row['bid_no']}_{row['bid_order']}" / safe_name(row["file_name"])
        result = {**row, "local_path": str(target.resolve())}
        try:
            if target.is_file() and digest(target) == row["sha256"]:
                result["status"] = "existing"
            elif verify_only:
                raise ValueError("missing" if not target.exists() else "sha256_mismatch")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
                    staged = Path(temporary) / target.name
                    cached = reusable.get((row["bid_no"], row["bid_order"], row["file_name"], row["url"]))
                    if cached and cached.is_file() and digest(cached) == row["sha256"]:
                        shutil.copyfile(cached, staged)
                        result["status"] = "reused"
                    else:
                        download_file(row["url"], staged)
                        result["status"] = "downloaded"
                    if digest(staged) != row["sha256"]:
                        raise ValueError("sha256_mismatch")
                    staged.replace(target)
            attachments.append(result)
        except (CollectionError, ValueError, OSError, RuntimeError) as exc:
            failures.append({**row, "error": str(exc)})
    report = {"bids": len({(a['bid_no'], a['bid_order']) for a in sources}),
              "expected_files": len(sources), "verified_files": len(attachments),
              "failures": failures, "mode": "verify" if verify_only else "collect",
              "dataset_sha256": {n: digest(dataset/n) for n in
                                 ("bids.csv", "manifest.json", "source-manifest.json")}}
    if not failures and not verify_only:
        evidence = build_evidence(attachments)
        covered = {b['source']['bid_no'] for b in evidence if b['source'].get('page') and b['text'].strip()}
        if covered != {a['bid_no'] for a in sources}:
            raise ValueError("PDF 텍스트를 확보하지 못한 평가 공고가 있습니다.")
        write_json(assets / "attachments.json", attachments)
        write_json(assets / "evidence.json", evidence)
        report["evidence_blocks"] = len(evidence)
    write_json(assets / "download-failures.json", failures)
    write_json(assets / "verification.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("failures", "dataset_sha256")}, ensure_ascii=False))
    print(f"실패 {len(failures)}개: {assets / 'download-failures.json'}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--assets", type=Path, default=ASSETS)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--reuse-manifest", type=Path)
    args = parser.parse_args()
    report = collect(args.dataset, args.assets, verify_only=args.verify_only, reuse_manifest=args.reuse_manifest)
    return bool(report["failures"])


if __name__ == "__main__":
    raise SystemExit(main())
