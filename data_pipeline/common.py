"""공유 파일 계약과 작은 입출력 도우미. 처리 단계나 외부 호출은 포함하지 않는다."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
from pathlib import Path

from .collect_bids import ROOT, KST, BID_FIELDS, FILE_FIELDS, write_csv
from .prepare_documents import read_csv, write_jsonl

DOWNLOAD_SUCCESS = frozenset({"downloaded", "existing"})
TEXT_READY = frozenset({"extracted", "review_empty_pages"})
HWP_SUFFIXES = frozenset({".hwp", ".hwpx"})


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
