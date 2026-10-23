"""공유 파일 계약과 작은 입출력 도우미. 처리 단계나 외부 호출은 포함하지 않는다."""
from contextlib import contextmanager
import csv
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "corpus"
KST = ZoneInfo("Asia/Seoul")
DOWNLOAD_SUCCESS = frozenset({"downloaded", "existing"})
TEXT_READY = frozenset({"extracted", "review_empty_pages"})
HWP_SUFFIXES = frozenset({".hwp", ".hwpx"})

BID_FIELDS = ["bid_no", "bid_order", "title", "agency", "published_at", "deadline",
              "estimated_price", "allocated_budget", "detail_url", "search_keywords",
              "collected_at", "downloaded_files", "failed_files"]
CANDIDATE_FIELDS = BID_FIELDS + ["selected", "selection_reason"]
FILE_FIELDS = ["bid_no", "bid_order", "file_name", "url", "selected", "status", "local_path", "error"]


def stamp():
    return datetime.now(KST).isoformat()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path, skip_blank=False):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if not skip_blank or line.strip()]


def write_jsonl(path, records):
    with Path(path).open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path, fields, rows):
    with Path(path).open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


@contextmanager
def directory_lock(directory, filename):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / filename).open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
