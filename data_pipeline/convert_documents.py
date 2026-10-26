"""HWP/HWPX를 LibreOffice + H2Orestart로 PDF 변환한다. 원본은 보존한다."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile, is_zipfile
from urllib.request import urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "data" / "tools"
PROFILE = TOOLS / "hwp-profile"
EXTENSION_VERSION = "0.8.0"
EXTENSION_SHA256 = "f36c19fa6b7dff1cf34114d926bdc088e6bcfa7fdc93d67eaafd3f572be1d62c"
EXTENSION_URL = "https://github.com/ebandal/H2Orestart/releases/download/v0.8.0/H2Orestart.oxt"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def find_soffice(explicit=None):
    if explicit and not Path(explicit).is_file():
        raise RuntimeError("--soffice에 지정한 실행파일이 없습니다.")
    candidates = [explicit, TOOLS / "LibreOffice.app/Contents/MacOS/soffice",
                  "/Applications/LibreOffice.app/Contents/MacOS/soffice", shutil.which("soffice")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise RuntimeError("LibreOffice가 없습니다. --soffice로 실행파일 경로를 지정하세요.")


ACTIVE_PROCESS = None


def cancel_active_conversion():
    if ACTIVE_PROCESS is not None:
        try:
            os.killpg(ACTIVE_PROCESS.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class ConversionTimeout(RuntimeError):
    pass


def conversion_policy():
    def setting(name, default, low, high):
        try:
            value = int(os.environ.get(name, default))
        except ValueError:
            raise RuntimeError(f"{name}은 정수여야 합니다.") from None
        if not low <= value <= high:
            raise RuntimeError(f"{name}은 {low}~{high} 범위여야 합니다.")
        return value
    return (setting("BID_CONVERSION_TIMEOUT_SECONDS", 120, 30, 600),
            setting("BID_CONVERSION_MAX_ATTEMPTS", 3, 1, 4),
            setting("BID_PREPARE_TIMEOUT_SECONDS", 3600, 120, 14400))


def attempt_timeout(base_seconds, attempt):
    """각 재시도마다 직전보다 오래 기다린다."""
    return base_seconds * attempt


def _save_conversion_records(path, records):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    temporary.replace(path)


def execute(args, timeout=None):
    if timeout is None:
        timeout = conversion_policy()[0]
    args = list(args)
    java_home = os.environ.get("JAVA_HOME")
    if not java_home and sys.platform == "darwin":
        detected = subprocess.run(["/usr/libexec/java_home"], capture_output=True, text=True, timeout=5)
        if not detected.returncode:
            java_home = detected.stdout.strip()
    if java_home:
        args.insert(1, "-env:UNO_JAVA_JFW_JREHOME=" + Path(java_home).resolve().as_uri())
    global ACTIVE_PROCESS
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    ACTIVE_PROCESS = process
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            cancel_active_conversion()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # 상속된 파이프가 닫히지 않아도 작업을 무기한 기다리지 않는다.
                process.stdout.close()
                process.stderr.close()
            raise ConversionTimeout(f"변환 도구가 {timeout}초 내에 응답하지 않아 자식 프로세스까지 종료했습니다.") from None
        if process.returncode:
            detail = (stderr or stdout).strip()[-1500:]
            raise RuntimeError(f"변환 도구 실행 실패 (종료 코드 {process.returncode}): {detail}")
        return stdout
    finally:
        ACTIVE_PROCESS = None



def _install_macos_extension(soffice, extension):
    """서명을 유지한다. macOS의 UNO 자식 실행 제약에 맞게 Office 내부에서 등록한다."""
    if (PROFILE / ".lock").exists():
        raise RuntimeError("변환 프로필이 사용 중입니다. 변환 작업을 종료한 뒤 설치를 다시 실행하세요.")
    basic = PROFILE / "user" / "basic"
    index = basic / "script.xlc"
    if not index.exists():
        execute([soffice, "-env:UserInstallation=" + PROFILE.resolve().as_uri(),
                 "--headless", "--norestore", "--terminate_after_init"])
    original_index = index.read_bytes()
    library = Path(tempfile.mkdtemp(prefix="PipelineSetup", dir=basic))
    result_file = library / "result.txt"
    namespace = "http://openoffice.org/2000/library"
    script_namespace = "http://openoffice.org/2000/script"
    try:
        tree = ET.fromstring(original_index)
        ET.SubElement(tree, f"{{{namespace}}}library", {
            f"{{{namespace}}}name": library.name, f"{{{namespace}}}link": "false"})
        index.write_bytes(ET.tostring(tree, encoding="utf-8", xml_declaration=True))
        definition = ET.Element(f"{{{namespace}}}library", {
            f"{{{namespace}}}name": library.name, f"{{{namespace}}}readonly": "false",
            f"{{{namespace}}}passwordprotected": "false"})
        ET.SubElement(definition, f"{{{namespace}}}element", {f"{{{namespace}}}name": "Setup"})
        (library / "script.xlb").write_bytes(ET.tostring(definition, encoding="utf-8", xml_declaration=True))
        # URI로 경로의 따옴표·개행을 인코딩한다. 입력 문서의 매크로는 실행하지 않는다.
        module = ET.Element(f"{{{script_namespace}}}module", {
            f"{{{script_namespace}}}name": "Setup", f"{{{script_namespace}}}language": "StarBasic"})
        module.text = f'''Sub Install
 On Error GoTo Failed
 Dim manager As Object, environment As Object
 Dim properties(0) As New com.sun.star.beans.NamedValue
 properties(0).Name = "SUPPRESS_LICENSE"
 properties(0).Value = "1"
 environment = CreateUnoListener("Environment_", "com.sun.star.ucb.XCommandEnvironment")
 manager = GetDefaultContext().getValueByName("/singletons/com.sun.star.deployment.ExtensionManager")
 manager.addExtension("{extension.resolve().as_uri()}", properties(), "user", Nothing, environment)
 WriteResult "OK"
 StarDesktop.terminate()
 Exit Sub
Failed:
 WriteResult "ERROR " & Err & ": " & Error$
 StarDesktop.terminate()
End Sub
Sub WriteResult(message As String)
 Dim stream As Object
 stream = CreateUnoService("com.sun.star.ucb.SimpleFileAccess").openFileWrite("{result_file.as_uri()}")
 Dim writer As Object
 writer = CreateUnoService("com.sun.star.io.TextOutputStream")
 writer.setOutputStream(stream)
 writer.setEncoding("UTF-8")
 writer.writeString(message)
 writer.closeOutput()
End Sub
Function Environment_getInteractionHandler() As Object
 Environment_getInteractionHandler = CreateUnoListener("Interaction_", "com.sun.star.task.XInteractionHandler")
End Function
Function Environment_getProgressHandler() As Object
 Environment_getProgressHandler = Nothing
End Function
Sub Interaction_handle(request As Object)
 Dim continuation As Object, approve As Boolean, requestType As String
 requestType = CreateUnoService("com.sun.star.reflection.CoreReflection").getType(request.getRequest()).getName()
 approve = requestType = "com.sun.star.deployment.InstallException" Or _
           requestType = "com.sun.star.deployment.VersionException"
 For Each continuation In request.getContinuations()
  If (approve And HasUnoInterfaces(continuation, "com.sun.star.task.XInteractionApprove")) Or _
     (Not approve And HasUnoInterfaces(continuation, "com.sun.star.task.XInteractionAbort")) Then
   continuation.select()
   Exit Sub
  End If
 Next
End Sub
'''
        (library / "Setup.xba").write_bytes(ET.tostring(module, encoding="utf-8", xml_declaration=True))
        execute([soffice, "-env:UserInstallation=" + PROFILE.resolve().as_uri(),
                 "--headless", "--norestore", "--nodefault",
                 f"macro:///{library.name}.Setup.Install()"], timeout=90)
        result = result_file.read_text(encoding="utf-8") if result_file.exists() else "등록 결과 없음"
        if result.strip() != "OK":
            raise RuntimeError(f"H2Orestart 내부 등록 실패: {result[:1500]}")
    finally:
        index.write_bytes(original_index)
        shutil.rmtree(library)


def setup(soffice):
    """사용자 기본 설정을 바꾸지 않고 프로젝트 전용 프로필에 확장 설치."""
    TOOLS.mkdir(parents=True, exist_ok=True)
    extension = TOOLS / "H2Orestart.oxt"
    if not extension.is_file() or sha256(extension) != EXTENSION_SHA256:
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
    registered = ("ebandal.libreoffice.H2Orestart" in installed
                  and re.findall(r"is registered: (\w+)", installed)
                  and all(state == "yes" for state in re.findall(r"is registered: (\w+)", installed)))
    if sys.platform == "darwin" and not registered:
        _install_macos_extension(soffice, extension)
    elif "ebandal.libreoffice.H2Orestart" not in installed:
        execute([str(unopkg), profile_arg, "add", "--suppress-license", str(extension)])
    installed = execute([str(unopkg), profile_arg, "list"])
    if "ebandal.libreoffice.H2Orestart" in installed and "is registered: no" in installed:
        execute([str(unopkg), profile_arg, "validate", "ebandal.libreoffice.H2Orestart"])
        installed = execute([str(unopkg), profile_arg, "list"])
    if ("ebandal.libreoffice.H2Orestart" not in installed
            or not re.findall(r"is registered: (\w+)", installed)
            or any(state != "yes" for state in re.findall(r"is registered: (\w+)", installed))):
        raise RuntimeError("H2Orestart 등록 실패: Java를 지원하는 정식 LibreOffice와 JDK가 필요합니다.")
    config = {"soffice": soffice, "engine_version": execute([soffice, "--version"]).strip(),
              "extension_version": EXTENSION_VERSION}
    (TOOLS / "converter.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def convert_one(source, target, soffice, profile=PROFILE, _archive_depth=0, timeout=None):
    """격리된 임시 출력에서 완성된 PDF만 목적 경로에 반영한다."""
    from pypdf import PdfReader
    if profile == PROFILE and os.environ.get("BID_CONVERTER_PROFILE"):
        profile = Path(os.environ["BID_CONVERTER_PROFILE"])
    target.parent.mkdir(parents=True, exist_ok=True)
    # 일부 공고는 파일명이 .hwp지만 실제 내용은 한글 원문 여러 개를 담은 ZIP이다.
    # 정상 HWPX ZIP과 구분하고, 이름이 일치하는 원문 하나만 임시 경로에서 변환한다.
    if is_zipfile(source):
        with ZipFile(source) as archive:
            names = archive.namelist()
            if "Contents/section0.xml" not in names:
                matches = [entry for entry in archive.infolist()
                           if not entry.is_dir() and source.name.endswith(Path(entry.filename).name)
                           and Path(entry.filename).suffix.lower() in (".hwp", ".hwpx")]
                if _archive_depth or len(matches) != 1:
                    raise RuntimeError("첨부는 ZIP 형식이며 내부에서 이름이 일치하는 한글 원문 하나를 확인하지 못했습니다. 원본 첨부를 확인하세요.")
                entry = matches[0]
                if entry.file_size > 50 * 1024 * 1024 or entry.flag_bits & 1:
                    raise RuntimeError("ZIP 내부 한글 원문이 크기 제한을 넘거나 암호화되어 있습니다.")
                with tempfile.TemporaryDirectory(prefix="hwp-source-", dir=target.parent) as temp:
                    # archive.extract를 쓰지 않아 경로 이동·링크를 통한 파일 쓰기를 막는다.
                    extracted = Path(temp) / Path(entry.filename).name
                    extracted.write_bytes(archive.read(entry))
                    return convert_one(extracted, target, soffice, profile, _archive_depth + 1, timeout)
    with tempfile.TemporaryDirectory(prefix="hwp-", dir=target.parent) as temp:
        execute([soffice, "-env:UserInstallation=" + Path(profile).resolve().as_uri(),
                 "--headless", "--infilter=Hwp2002_File", "--convert-to", "pdf:writer_pdf_Export",
                 "--outdir", temp, str(source)], timeout=timeout)
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
        config = json.loads(config_path.read_text(encoding="utf-8"))
    manifest = run_dir / "conversions.jsonl"
    old = {}
    if manifest.is_file():
        old = {r["original_path"]: r for r in map(json.loads, manifest.read_text(encoding="utf-8").splitlines())}
    with (run_dir / "attachments.csv").open(encoding="utf-8-sig", newline="") as stream:
        attachments = list(csv.DictReader(stream))
    records = []
    for row in attachments:
        if row.get("selected", "").lower() != "true":
            continue
        path = Path(row["local_path"]) if row.get("local_path") else None
        if not path or path.suffix.lower() not in (".hwp", ".hwpx"):
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
            if row.get("status") not in ("downloaded", "existing") or not path.is_file():
                raise RuntimeError("원본 다운로드가 완료되지 않았습니다.")
            digest = sha256(path)
            record["original_sha256"] = digest
            # 파일명이 같아도 원본 경로/확장자가 다르면 충돌하지 않는다.
            source_id = hashlib.sha256((str(path) + digest).encode()).hexdigest()[:16]
            target = run_dir / "converted" / source_id / (path.stem + ".pdf")
            cached = old.get(str(path), {})
            if (cached.get("original_sha256") == digest and cached.get("status") in ("converted", "existing")
                    and all(cached.get(k) == config.get(k) for k in config)
                    and target.is_file() and cached.get("pdf_sha256") == sha256(target)):
                record.update(pdf_path=str(target), pdf_sha256=cached["pdf_sha256"], status="existing",
                              elapsed_seconds=0.0)
            else:
                # 서로 다른 첨부 URL이 같은 원문을 제공해도 변환은 한 번만 수행한다.
                equivalent = next((r for r in [*old.values(), *records[:-1]]
                                   if r.get("original_sha256") == digest
                                   and r.get("status") in ("converted", "existing")
                                   and all(r.get(k) == config.get(k) for k in config)
                                   and r.get("pdf_path") and Path(r["pdf_path"]).is_file()
                                   and r.get("pdf_sha256") == sha256(Path(r["pdf_path"]))), None)
                if equivalent:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(equivalent["pdf_path"], target)
                    record.update(pdf_path=str(target), pdf_sha256=equivalent["pdf_sha256"], status="existing",
                                  elapsed_seconds=0.0)
                else:
                    timeout_seconds, max_attempts, _ = conversion_policy()
                    record.setdefault("attempt_history", [])
                    for attempt in range(1, max_attempts + 1):
                        attempt_started = time.perf_counter()
                        attempt_timeout_seconds = attempt_timeout(timeout_seconds, attempt)
                        record.update(status="converting" if attempt == 1 else "retrying",
                                      attempt=attempt, max_attempts=max_attempts,
                                      timeout_seconds=attempt_timeout_seconds)
                        _save_conversion_records(manifest, records)
                        print(f"PDF 변환: {path.name} ({attempt}/{max_attempts}, {attempt_timeout_seconds}초)", flush=True)
                        try:
                            if converter is not convert_one:
                                converter(path, target, config["soffice"])
                            elif attempt == 1:
                                converter(path, target, config["soffice"], timeout=attempt_timeout_seconds)
                            else:
                                # 시간 초과 후에는 잠금·복구 상태가 남지 않은 별도 프로필로 재시도한다.
                                with tempfile.TemporaryDirectory(prefix="office-retry-") as temp:
                                    retry_profile = Path(temp) / "profile"
                                    shutil.copytree(PROFILE, retry_profile,
                                                    ignore=shutil.ignore_patterns(".lock", "*.lock", "lock"))
                                    converter(path, target, config["soffice"], profile=retry_profile,
                                              timeout=attempt_timeout_seconds)
                            record["attempt_history"].append({"attempt": attempt,
                                "timeout_seconds": attempt_timeout_seconds, "status": "converted", "error": ""})
                            elapsed = round(time.perf_counter() - attempt_started, 3)
                            record["attempt_history"][-1]["elapsed_seconds"] = elapsed
                            record.update(pdf_path=str(target), pdf_sha256=sha256(target), status="converted",
                                          error="", elapsed_seconds=sum(
                                              entry.get('elapsed_seconds', 0) for entry in record['attempt_history']))
                            break
                        except ConversionTimeout as exc:
                            record["attempt_history"].append({"attempt": attempt,
                                "timeout_seconds": attempt_timeout_seconds,
                                "status": "timeout",
                                "error": str(exc),
                                "elapsed_seconds": round(time.perf_counter() - attempt_started, 3)})
                            record.update(status="timeout", error=str(exc))
                            record['elapsed_seconds'] = round(sum(
                                entry.get('elapsed_seconds', 0) for entry in record['attempt_history']), 3)
                            _save_conversion_records(manifest, records)
                            if attempt == max_attempts:
                                raise

        except Exception as exc:
            if record.get("attempt") and record.get("status") not in ("converted", "existing"):
                history = record.setdefault("attempt_history", [])
                if not history or history[-1].get("attempt") != record["attempt"]:
                    history.append({"attempt": record["attempt"],
                                    "timeout_seconds": record.get("timeout_seconds"),
                                    "status": "failed", "error": str(exc)})
            record.update(status="failed", error=(str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))
            if record.get("attempt"):
                record["elapsed_seconds"] = round(sum(
                    entry.get('elapsed_seconds', 0) for entry in record.get('attempt_history', [])), 3)
        # 중간에 멈춰도 완료된 파일은 다음 실행에서 재사용한다.
        _save_conversion_records(manifest, records)
    if not records:
        _save_conversion_records(manifest, [])
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
