"""Phân tích draft_content.json thành timeline dễ dùng. Chỉ đọc."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .drafts import US

# Các loại material phụ không mang thông tin công thức
_IGNORED_EXTRAS = {
    "speeds", "canvases", "sound_channel_mappings", "material_colors",
    "vocal_separations", "placeholder_infos", "loudnesses",
}


@dataclass
class Ref:
    """Một material phụ gắn vào đoạn: transition, animation, hiệu ứng, blend…"""
    category: str          # tên nhóm trong materials, ví dụ "transitions"
    id: str
    type: str
    name: str
    resource_id: str = ""
    duration: int = 0      # micro giây, dùng cho transition
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class KeyframeTrack:
    property: str          # ví dụ KFTypePositionX
    offsets: list[int]     # micro giây, tính từ đầu đoạn


@dataclass
class Segment:
    id: str
    track_index: int
    track_type: str
    start: int
    duration: int
    source_start: int | None
    speed: float
    material_category: str
    material_type: str
    material_name: str
    material_path: str
    refs: list[Ref]
    keyframes: list[KeyframeTrack]
    raw: dict = field(default_factory=dict, repr=False)
    is_slot: bool = False  # đoán là ô cho người dùng thay

    @property
    def end(self) -> int:
        return self.start + self.duration

    def refs_of(self, category: str) -> list[Ref]:
        return [r for r in self.refs if r.category == category]


@dataclass
class Track:
    index: int
    type: str
    attribute: int
    segments: list[Segment]


@dataclass
class Timeline:
    folder: Path
    duration: int
    fps: float
    width: int
    height: int
    tracks: list[Track]
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def duration_s(self) -> float:
        return self.duration / US

    def segments(self, track_type: str | None = None) -> list[Segment]:
        return [s for t in self.tracks if track_type in (None, t.type) for s in t.segments]

    @property
    def music(self) -> Segment | None:
        """Đoạn nhạc dài nhất, coi là nhạc nền dùng để dò beat."""
        audios = self.segments("audio")
        return max(audios, key=lambda s: s.duration) if audios else None

    @property
    def slots(self) -> list[Segment]:
        return sorted((s for s in self.segments("video") if s.is_slot), key=lambda s: s.start)


def _material_name(m: dict) -> str:
    return m.get("name") or m.get("material_name") or m.get("type") or ""


def load_timeline(folder: Path) -> Timeline:
    data = json.loads((Path(folder) / "draft_content.json").read_text(encoding="utf-8"))
    index: dict[str, tuple[str, dict]] = {}
    for category, items in data["materials"].items():
        if isinstance(items, list):
            for m in items:
                if isinstance(m, dict) and "id" in m:
                    index[m["id"]] = (category, m)

    tracks = []
    for ti, t in enumerate(data["tracks"]):
        segments = []
        for s in t["segments"]:
            category, m = index.get(s["material_id"], ("", {}))
            refs = []
            for rid in s.get("extra_material_refs", []):
                rc, rm = index.get(rid, ("", {}))
                if not rc or rc in _IGNORED_EXTRAS:
                    continue
                refs.append(Ref(rc, rid, rm.get("type", ""), _material_name(rm),
                                rm.get("resource_id") or rm.get("effect_id") or "",
                                rm.get("duration", 0) or 0, rm))
            keyframes = [
                KeyframeTrack(c.get("property_type", ""), [k["time_offset"] for k in c.get("keyframe_list", [])])
                for c in s.get("common_keyframes", [])
            ]
            src = s.get("source_timerange") or {}
            segments.append(Segment(
                id=s["id"], track_index=ti, track_type=t["type"],
                start=s["target_timerange"]["start"], duration=s["target_timerange"]["duration"],
                source_start=src.get("start"), speed=s.get("speed", 1.0),
                material_category=category, material_type=m.get("type", ""),
                material_name=_material_name(m), material_path=m.get("path", ""),
                refs=refs, keyframes=keyframes, raw=s,
            ))
        tracks.append(Track(ti, t["type"], t.get("attribute", 0), segments))

    canvas = data.get("canvas_config") or {}
    timeline = Timeline(Path(folder), data["duration"], data.get("fps", 30.0),
                        canvas.get("width", 0), canvas.get("height", 0), tracks, data)
    _mark_slots(timeline)
    return timeline


def _mark_slots(timeline: Timeline) -> None:
    """Đoán ô thay: ảnh/clip người dùng tự đưa vào, không phải lớp phủ hay tài nguyên của CapCut.

    Lớp phủ (overlay) thường dùng chế độ hòa trộn hoặc lặp lại cùng một file nhiều lần.
    """
    videos = [s for s in timeline.segments("video") if s.material_type in ("photo", "video")]
    usage = Counter(s.material_path for s in videos)
    for s in videos:
        blended = any(r.category == "effects" for r in s.refs)
        from_capcut = "/CapCut/User Data/" in s.material_path.replace("\\", "/")
        s.is_slot = not blended and not from_capcut and usage[s.material_path] == 1
