"""Thay ảnh/clip ở các ô thay và thay nhạc nền trong draft_content."""
from __future__ import annotations

import random
import uuid
from pathlib import Path

from ..capcut.drafts import US
from ..media import IMAGE_EXT, VIDEO_EXT, MediaInfo, probe
from .retime import NewTimeline

PHOTO_DURATION = 10_800_000_000  # CapCut gán cho ảnh tĩnh độ dài 3 giờ


def list_materials(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    files = [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXT | VIDEO_EXT]
    if not files:
        raise ValueError(f"Thư mục nguyên liệu {folder} không có ảnh hoặc clip nào")
    return sorted(files)


def _segments_by_id(content: dict) -> dict[str, dict]:
    return {s["id"]: s for t in content["tracks"] for s in t["segments"]}


def _material(content: dict, category: str, mid: str) -> dict:
    return next(m for m in content["materials"][category] if m["id"] == mid)


def fill_slots(content: dict, slot_ids: list[str], files: list[Path], rng: random.Random) -> list[Path]:
    """Gán ngẫu nhiên nguyên liệu vào từng ô thay. Clip phải đủ dài cho ô, nếu không thì dùng ảnh."""
    segments = _segments_by_id(content)
    infos = [probe(f) for f in files]
    used: list[Path] = []
    for sid in slot_ids:
        seg = segments[sid]
        need_s = seg["target_timerange"]["duration"] * (seg.get("speed") or 1.0) / US
        fits = [i for i in infos if i.kind == "photo" or i.duration_s >= need_s]
        if not fits:
            raise ValueError(f"Không có ảnh hoặc clip nào đủ dài {need_s:.2f}s cho ô thay")
        unused = [i for i in fits if i.path not in used] or fits
        info = rng.choice(unused)
        _apply_media(_material(content, "videos", seg["material_id"]), seg, info)
        used.append(info.path)
    return used


def fill_slots_ordered(content: dict, slot_ids: list[str], files: list[Path]) -> list[Path]:
    """Ảnh/clip thứ i vào ô thay thứ i (theo thời gian). Số file phải bằng số ô."""
    if len(files) != len(slot_ids):
        raise ValueError(f"Mẫu có {len(slot_ids)} ô thay nên cần đúng {len(slot_ids)} ảnh/clip, bạn chọn {len(files)}")
    segments = _segments_by_id(content)
    ordered = sorted(slot_ids, key=lambda sid: segments[sid]["target_timerange"]["start"])
    for sid, path in zip(ordered, files):
        seg = segments[sid]
        info = probe(path)
        need_s = seg["target_timerange"]["duration"] * (seg.get("speed") or 1.0) / US
        if info.kind == "video" and info.duration_s < need_s:
            raise ValueError(f"Clip {path.name} dài {info.duration_s:.1f}s, ô thay cần {need_s:.1f}s")
        _apply_media(_material(content, "videos", seg["material_id"]), seg, info)
    return list(files)


def _apply_media(material: dict, seg: dict, info: MediaInfo) -> None:
    material.update({
        "type": info.kind,
        "path": info.path.as_posix(),
        "material_name": info.path.name,
        "width": info.width,
        "height": info.height,
        "duration": PHOTO_DURATION if info.kind == "photo" else round(info.duration_s * US),
        "has_audio": info.has_audio,
        "unique_id": "",
    })
    src = seg.get("source_timerange")
    if src is not None:
        src["start"] = 0


def replace_music(content: dict, music_segment_id: str, music: MediaInfo, nt: NewTimeline) -> None:
    seg = _segments_by_id(content)[music_segment_id]
    material = _material(content, "audios", seg["material_id"])
    material.update({
        "path": music.path.as_posix(),
        "name": music.path.name,
        "duration": round(music.duration_s * US),
        "music_id": str(uuid.uuid4()),
    })
    start = round(nt.music_start_s * US)
    seg["target_timerange"] = {"start": 0, "duration": nt.duration}
    seg["source_timerange"] = {"start": start, "duration": nt.duration}
    seg["speed"] = 1.0
    # bỏ điểm beat cũ của CapCut, để CapCut tự dò lại cho nhạc mới
    for ref in seg.get("extra_material_refs", []):
        for b in content["materials"].get("beats", []):
            if b["id"] == ref:
                b["user_beats"] = []
                b.get("ai_beats", {}).update({"beats_path": "", "beats_url": "", "melody_path": "", "melody_url": ""})
