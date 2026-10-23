"""명시 선택한 공고의 원본 첨부를 제공한다. 변환 PDF는 배포하지 않는다."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile
from .common import read_json, write_json, DOWNLOAD_SUCCESS

from .bid_workflow import locked, select_bids
from .g2b_client import safe_name


class DeliveryIncomplete(ValueError):
    pass


def attachment_id(record):
    return hashlib.sha256(record["url"].encode()).hexdigest()[:24]


def original_path(root, bid_id, record):
    path = Path(record.get("local_path") or "__missing__").resolve()
    allowed = (Path(root) / "raw" / safe_name(bid_id)).resolve()
    if (record.get("status") not in DOWNLOAD_SUCCESS or not path.is_file()
            or not path.is_relative_to(allowed) or not path.stat().st_size):
        raise DeliveryIncomplete("원본 첨부 다운로드가 완료되지 않았습니다.")
    return path


def delivery_items(run_dir, bid_ids):
    root = Path(run_dir)
    listing = read_json(root / "bid_list.json")
    selected_path = root / "user_selections.json"
    selections = read_json(selected_path) if selected_path.exists() else {}
    items = []
    for bid_id in bid_ids:
        bid = next((b for b in listing["items"] if b["bid_id"] == bid_id), None)
        if not bid or bid_id not in selections:
            raise ValueError("사용자가 선택한 공고만 전달할 수 있습니다.")
        attachments = []
        for record in bid["attachments"]:
            entry = {"file_id": attachment_id(record), "file_name": record["file_name"],
                     "source_url": record["url"], "status": record["status"], "available": False}
            try:
                path = original_path(root, bid_id, record)
                entry.update(available=True, bytes=path.stat().st_size)
            except DeliveryIncomplete:
                pass
            attachments.append(entry)
        items.append({"bid_id": bid_id, "title": bid["title"], "attachments": attachments,
                      "complete": bool(attachments) and all(a["available"] for a in attachments)})
    return items


def select_for_delivery(run_dir, bid_ids):
    select_bids(run_dir, bid_ids)
    with locked(run_dir) as root:
        items = delivery_items(root, bid_ids)
        result = {"selected_bid_ids": bid_ids, "items": items,
                  "complete": all(i["complete"] for i in items),
                  "scope": "OpenAPI attachment URLs 1-10 and standard notice URL",
                  "format": "original_attachments", "converted_files_included": False}
        write_json(root / "delivery.json", result)
        return result


def build_archive(run_dir):
    """실패 파일이 있으면 완전한 묶음으로 가장하지 않고 409 처리를 요청한다."""
    with locked(run_dir) as root:
        delivery = root / "delivery.json"
        if not delivery.exists():
            raise ValueError("먼저 공고 1~2개를 선택하세요.")
        ids = read_json(delivery)["selected_bid_ids"]
        items = delivery_items(root, ids)
        if not all(i["complete"] for i in items):
            raise DeliveryIncomplete("실패·누락 첨부가 있습니다. 선택 요청을 다시 보내 재시도하세요.")
        listing = read_json(root / "bid_list.json")
        records = {b["bid_id"]: b["attachments"] for b in listing["items"]}
        target = root / "delivery.zip"
        # API가 전달 중인 이전 ZIP도 손상되지 않도록 원자적으로 교체한다.
        with tempfile.NamedTemporaryFile(dir=root, suffix=".zip", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for bid_id in ids:
                    for position, record in enumerate(records[bid_id], 1):
                        path = original_path(root, bid_id, record)
                        name = safe_name(record["file_name"])
                        if name == "standard_notice":
                            name += path.suffix
                        archive.write(path, f"{safe_name(bid_id)}/{position:02}_{name}")
                archive.writestr("manifest.json", json.dumps({"items": items, "format": "original_attachments"}, ensure_ascii=False, indent=2))
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def find_attachment(run_dir, bid_id, file_id):
    with locked(run_dir) as root:
        items = delivery_items(root, [bid_id])
        if not any(a["file_id"] == file_id for a in items[0]["attachments"]):
            raise ValueError("선택 공고에 없는 첨부입니다.")
        listing = read_json(root / "bid_list.json")
        bid = next(b for b in listing["items"] if b["bid_id"] == bid_id)
        record = next(r for r in bid["attachments"] if attachment_id(r) == file_id)
        return original_path(root, bid_id, record), safe_name(record["file_name"])
