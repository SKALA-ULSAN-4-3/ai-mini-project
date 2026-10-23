"""HWP/HWPX를 LibreOffice + H2Orestart로 PDF 변환한다. 원본은 보존한다."""
import argparse
from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "data_pipeline"

from .common import read_csv, read_json, read_jsonl, write_jsonl, file_sha256, DOWNLOAD_SUCCESS, HWP_SUFFIXES

ROOT = Path(__file__).resolve().parents[1]
sha256 = file_sha256
TOOLS = ROOT / "data" / "tools"
PROFILE = TOOLS / "hwp-profile"
EXTENSION_VERSION = "0.8.0"
EXTENSION_SHA256 = "f36c19fa6b7dff1cf34114d926bdc088e6bcfa7fdc93d67eaafd3f572be1d62c"
EXTENSION_URL = "https://github.com/ebandal/H2Orestart/releases/download/v0.8.0/H2Orestart.oxt"


def find_soffice(explicit=None):
    if explicit and not Path(explicit).is_file():
        raise RuntimeError("--soffice에 지정한 실행파일이 없습니다.")
    candidates = [explicit, TOOLS / "LibreOffice.app/Contents/MacOS/soffice",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice", shutil.which("soffice")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("LibreOffice가 없습니다. --soffice로 실행파일 경로를 지정하세요.")


def execute(args, timeout=45):
    args = list(args)
    java_home = os.environ.get("JAVA_HOME")
    if not java_home and sys.platform == "darwin":
        detected = subprocess.run(["/usr/libexec/java_home"], capture_output=True, text=True, timeout=5)
        if not detected.returncode:
            java_home = detected.stdout.strip()
    if java_home:
        args.insert(1, "-env:UNO_JAVA_JFW_JREHOME=" + Path(java_home).resolve().as_uri())
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"변환 도구 실행 실패 (종료 코드 {result.returncode})")
    return result.stdout


def setup(soffice):
    """사용자 기본 설정을 바꾸지 않고 프로젝트 전용 프로필에 확장 설치."""
    TOOLS.mkdir(parents=True, exist_ok=True)
    extension = TOOLS / "H2Orestart.oxt"
    if not extension.is_file() or file_sha256(extension) != EXTENSION_SHA256:
        with urlopen(EXTENSION_URL, timeout=30) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != EXTENSION_SHA256:
            raise RuntimeError("H2Orestart 배포 파일의 SHA-256이 일치하지 않습니다.")
        extension.write_bytes(data)
    unopkg = Path(soffice).with_name("unopkg" + (".exe" if os.name == "nt" else ""))
    if not unopkg.is_file():
        found = shutil.which("unopkg")
        if not found:
            raise RuntimeError("LibreOffice의 unopkg 실행파일이 필요합니다.")
        unopkg = Path(found)
    profile_arg = "-env:UserInstallation=" + PROFILE.resolve().as_uri()
    installed = execute([str(unopkg), profile_arg, "list"])
    if "ebandal.libreoffice.H2Orestart" not in installed:
        execute([str(unopkg), profile_arg, "add", "--suppress-license", str(extension)])
    installed = execute([str(unopkg), profile_arg, "list"])
    if "ebandal.libreoffice.H2Orestart" in installed and "is registered: no" in installed:
        execute([str(unopkg), profile_arg, "validate", "ebandal.libreoffice.H2Orestart"])
        installed = execute([str(unopkg), profile_arg, "list"])
    if "ebandal.libreoffice.H2Orestart" not in installed or "is registered: no" in installed:
        raise RuntimeError("H2Orestart 등록 실패: Java를 지원하는 정식 LibreOffice와 JDK가 필요합니다.")
    config = {"soffice": soffice, "engine_version": execute([soffice, "--version"]).strip(),
              "extension_version": EXTENSION_VERSION}
    (TOOLS / "converter.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def convert_one(source, target, soffice, profile=PROFILE):
    """격리된 임시 출력에서 완성된 PDF만 목적 경로에 반영한다."""
    from pypdf import PdfReader
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hwp-", dir=target.parent) as temp:
        execute([soffice, "-env:UserInstallation=" + Path(profile).resolve().as_uri(),
                 "--headless", "--infilter=Hwp2002_File", "--convert-to", "pdf:writer_pdf_Export",
                 "--outdir", temp, str(source)])
        pdf = Path(temp) / (source.stem + ".pdf")
        if not pdf.is_file() or pdf.read_bytes()[:5] != b"%PDF-":
            raise RuntimeError("PDF가 생성되지 않았습니다. 변환 로그와 확장 설치를 확인하세요.")
        with pdf.open("rb") as stream:
            reader = PdfReader(stream)
            if reader.is_encrypted or not len(reader.pages):
                raise RuntimeError("변환 PDF가 암호화되었거나 페이지가 없습니다.")
            # 페이지를 읽을 수 있는지 확인. 표/레이아웃 정확성은 별도 검토한다.
            texts = [page.extract_text() or "" for page in reader.pages]
            if not any(text.strip() for text in texts):
                raise RuntimeError("변환 PDF에서 검색 가능한 텍스트를 찾지 못했습니다.")
            validate_text_quality(texts)
        pdf.replace(target)


def validate_text_quality(texts):
    # 실제 변환에서 발견된 '한글 전체가 같은 글자로 바뀌는' 글꼴 오류 차단.
    # 의미·표 구조의 정확성을 검증하는 기능은 아니다.
    for text in texts:
        hangul = re.findall("[가-힣]", text)
        if len(hangul) >= 80 and Counter(hangul).most_common(1)[0][1] / len(hangul) >= 0.45:
            raise RuntimeError("한글이 같은 글자로 반복됩니다. LibreOffice 버전·한국어 글꼴을 확인하세요.")


def convert_run(run_dir, config=None, converter=convert_one):
    run_dir = Path(run_dir).resolve()
    if config is None:
        config_path = TOOLS / "converter.json"
        if not config_path.is_file():
            raise RuntimeError("먼저 convert_documents.py --setup을 실행하세요.")
        config = read_json(config_path)
    manifest = run_dir / "conversions.jsonl"
    old = {}
    if manifest.is_file():
        old = {r["original_path"]: r for r in read_jsonl(manifest)}
    attachments = read_csv(run_dir / "attachments.csv")
    records = []
    for row in attachments:
        if row.get("selected", "").lower() != "true":
            continue
        path = Path(row["local_path"]) if row.get("local_path") else None
        if not path or path.suffix.lower() not in HWP_SUFFIXES:
            continue
        if not path.is_absolute():
            path = run_dir / path
        path = path.resolve()
        record = {"bid_no": row["bid_no"], "bid_order": row["bid_order"],
                  "original_path": str(path), "original_sha256": "", "pdf_path": "",
                  "pdf_sha256": "", "status": "", "error": "", **config,
                  "requires_layout_review": True}
        records.append(record)
        try:
            if row.get("status") not in DOWNLOAD_SUCCESS or not path.is_file():
                raise RuntimeError("원본 다운로드가 완료되지 않았습니다.")
            digest = file_sha256(path)
            record["original_sha256"] = digest
            # 파일명이 같아도 원본 경로/확장자가 다르면 충돌하지 않는다.
            source_id = hashlib.sha256((str(path) + digest).encode()).hexdigest()[:16]
            target = run_dir / "converted" / source_id / (path.stem + ".pdf")
            cached = old.get(str(path), {})
            if (cached.get("original_sha256") == digest and cached.get("status") in ("converted", "existing")
                    and all(cached.get(k) == config.get(k) for k in config)
                    and target.is_file() and cached.get("pdf_sha256") == file_sha256(target)):
                record.update(pdf_path=str(target), pdf_sha256=cached["pdf_sha256"], status="existing")
            else:
                print(f"PDF 변환: {path.name}", flush=True)
                converter(path, target, config["soffice"])
                record.update(pdf_path=str(target), pdf_sha256=file_sha256(target), status="converted")
        except Exception as exc:
            record.update(status="failed", error=(str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))
        # 중간에 멈춰도 완료된 파일은 다음 실행에서 재사용한다.
        write_jsonl(manifest, records)
    if not records:
        write_jsonl(manifest, [])
    return records


def convert_rhwp(output, executable):
    """기존 LibreOffice 작업과 별도로 실행 가능. 원본/변환 해시로 재개한다."""
    output = Path(output).resolve()
    previous = {}
    manifest = output / "conversions.jsonl"
    if manifest.exists():
        previous = {r["original_path"]: r for r in read_jsonl(manifest)}
    records = []
    for row in read_csv(output / "attachments.csv"):
        source = Path(row["local_path"])
        if source.suffix.lower() not in HWP_SUFFIXES or row["status"] not in DOWNLOAD_SUCCESS:
            continue
        digest = file_sha256(source)
        target = output / "converted" / hashlib.sha256(str(source).encode()).hexdigest()[:16] / (source.stem + ".pdf")
        old = previous.get(str(source), {})
        record = dict(bid_no=row["bid_no"], bid_order=row["bid_order"], original_path=str(source),
                      original_sha256=digest, pdf_path=str(target), pdf_sha256="", status="failed",
                      engine="rhwp", requires_layout_review=True, error="")
        try:
            if not (target.exists() and old.get("original_sha256") == digest and
                    old.get("pdf_sha256") == file_sha256(target)):
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
            record.update(status="converted", pdf_sha256=file_sha256(target))
            print(f"변환 완료: {source.name}", flush=True)
        except Exception as exc:
            record["error"] = str(exc)[:200]
        records.append(record)
        write_jsonl(manifest, records)
    return records

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true", help="프로젝트 전용 변환 환경 설정")
    parser.add_argument("--soffice", help="Java 지원 LibreOffice 실행파일 경로 (--setup과 함께)")
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if not args.setup and not args.run_dir:
        parser.error("--setup 또는 --run-dir를 지정하세요.")
    try:
        if args.setup:
            print(json.dumps(setup(find_soffice(args.soffice)), ensure_ascii=False, indent=2))
        if args.run_dir:
            records = convert_run(args.run_dir)
            counts = {s: sum(r["status"] == s for r in records) for s in ("converted", "existing", "failed")}
            print(json.dumps(counts, ensure_ascii=False))
            return 2 if counts["failed"] else 0
    except Exception as exc:
        print(f"변환 준비 실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
