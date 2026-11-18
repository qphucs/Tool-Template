"""Ghi project mới vào thư mục CapCut một cách an toàn.

- Không bao giờ sửa project gốc: luôn sao chép sang thư mục mới.
- Sao lưu root_meta_info.json trước khi ghi.
- Chỉ đăng ký vào danh sách project khi CapCut đã tắt, vì CapCut đang mở sẽ ghi đè file này.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from ..capcut.drafts import drafts_root

BACKUP_DIR = Path(__file__).resolve().parents[2] / "data" / "backups"
CONTENT_COPIES = ("draft_content.json", "draft_content.json.bak", "template-2.tmp")


class CapCutRunningError(RuntimeError):
    pass


def capcut_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "CapCut.exe" in out


def _capcut_id() -> str:
    return str(uuid.uuid4()).upper()


def _unique_folder(root: Path, name: str) -> Path:
    folder = root / name
    n = 1
    while folder.exists():
        folder = root / f"{name} ({n})"
        n += 1
    return folder


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp-write")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def write_draft(source_folder: Path, name: str, content: dict, root: Path | None = None) -> Path:
    """Sao chép project mẫu sang thư mục mới, ghi content mới và đăng ký với CapCut."""
    if capcut_running():
        raise CapCutRunningError("CapCut đang mở. Hãy tắt CapCut rồi chạy lại để tool đăng ký project mới.")
    root = root or drafts_root()
    folder = _unique_folder(root, name)
    shutil.copytree(source_folder, folder)
    try:
        _write_contents(folder, content)
        meta = _write_meta(folder, content)
        _register(root, folder, meta, source_folder)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


def _write_contents(folder: Path, content: dict) -> None:
    """CapCut 9 giữ bản draft_content ở thư mục gốc và trong Timelines/<id>; ghi đè tất cả các bản."""
    targets = [folder] + [p for p in (folder / "Timelines").glob("*") if p.is_dir()]
    for target in targets:
        for name in CONTENT_COPIES:
            if (target / name).exists() or name == "draft_content.json":
                _write_json(target / name, content)
        # bản nháp đồng bộ đám mây của project gốc, bỏ đi để CapCut không dùng nhầm nội dung cũ
        mini = target / "attachment" / "patch" / "mini_draft.json"
        if mini.exists():
            mini.unlink()


def _write_meta(folder: Path, content: dict) -> dict:
    path = folder / "draft_meta_info.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    now = int(time.time() * 1_000_000)
    meta.update({
        "draft_id": _capcut_id(),
        "draft_name": folder.name,
        "draft_fold_path": folder.as_posix(),
        "draft_root_path": folder.parent.as_posix(),
        "tm_draft_create": now,
        "tm_draft_modified": now,
        "tm_duration": content["duration"],
        "draft_cloud_template_id": "",
    })
    _write_json(path, meta)
    return meta


def _register(root: Path, folder: Path, meta: dict, source_folder: Path) -> None:
    root_meta_path = root / "root_meta_info.json"
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root_meta_path, BACKUP_DIR / f"root_meta_info-{datetime.now():%Y%m%d-%H%M%S}.json")

    root_meta = json.loads(root_meta_path.read_text(encoding="utf-8"))
    store = root_meta["all_draft_store"]
    # dùng mục của project mẫu làm khuôn, chỉ đổi các trường riêng của project mới
    template = next((e for e in store if Path(e["draft_fold_path"]) == Path(source_folder)), store[0])
    entry = dict(template)
    folder_str = folder.as_posix()
    entry.update({
        "draft_id": meta["draft_id"],
        "draft_name": folder.name,
        "draft_fold_path": folder_str,
        "draft_cover": f"{folder_str}\\draft_cover.jpg",
        "draft_json_file": f"{folder_str}\\draft_content.json",
        "draft_root_path": root.as_posix(),
        "tm_draft_create": meta["tm_draft_create"],
        "tm_draft_modified": meta["tm_draft_modified"],
        "tm_duration": meta["tm_duration"],
        "tm_draft_removed": 0,
        "draft_is_invisible": False,
        "draft_cloud_template_id": "",
        "cloud_draft_sync": False,
        "tm_draft_cloud_entry_id": -1,
        "tm_draft_cloud_parent_entry_id": -1,
        "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1,
        "tm_draft_cloud_modified": 0,
    })
    store.insert(0, entry)
    root_meta["draft_ids"] = root_meta.get("draft_ids", len(store) - 1) + 1
    _write_json(root_meta_path, root_meta)
