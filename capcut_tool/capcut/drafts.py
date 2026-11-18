"""Liệt kê project (draft) của CapCut PC. Chỉ đọc, không ghi gì vào thư mục CapCut."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

US = 1_000_000  # CapCut lưu thời gian theo micro giây


def drafts_root() -> Path:
    """Thư mục chứa project của CapCut PC."""
    override = os.environ.get("CAPCUT_DRAFTS_ROOT")
    if override:
        return Path(override)
    return Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft"


@dataclass
class DraftInfo:
    id: str
    name: str
    folder: Path
    cover: Path | None
    duration_s: float
    modified: datetime

    @property
    def content_path(self) -> Path:
        return self.folder / "draft_content.json"


def _from_timestamp(value: int) -> datetime:
    # root_meta_info lưu micro giây; một số bản cũ lưu giây
    return datetime.fromtimestamp(value / US if value > 10**12 else value)


def list_drafts(root: Path | None = None) -> list[DraftInfo]:
    """Đọc root_meta_info.json, trả về danh sách project mới sửa trước."""
    root = root or drafts_root()
    meta = json.loads((root / "root_meta_info.json").read_text(encoding="utf-8"))
    drafts = []
    for entry in meta.get("all_draft_store", []):
        if entry.get("tm_draft_removed") or entry.get("draft_is_invisible"):
            continue
        folder = Path(entry["draft_fold_path"])
        if not (folder / "draft_content.json").is_file():
            continue
        cover = Path(entry["draft_cover"]) if entry.get("draft_cover") else None
        drafts.append(DraftInfo(
            id=entry["draft_id"],
            name=entry["draft_name"],
            folder=folder,
            cover=cover if cover and cover.is_file() else None,
            duration_s=entry.get("tm_duration", 0) / US,
            modified=_from_timestamp(entry.get("tm_draft_modified", 0)),
        ))
    drafts.sort(key=lambda d: d.modified, reverse=True)
    return drafts
