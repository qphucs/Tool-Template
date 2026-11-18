"""Học công thức: gắn mọi mốc thời gian của project mẫu vào vị trí beat của nhạc nền.

Công thức lưu vị trí beat thay vì giây, nên khi đổi nhạc chỉ cần đổi beat -> giây theo nhạc mới
là các điểm cắt, hiệu ứng, keyframe tự co giãn cho khớp.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ..audio.beats import BeatGrid, detect_beats
from ..capcut.drafts import US, DraftInfo
from ..capcut.timeline import Segment, Timeline, load_timeline

FORMULA_VERSION = 1
FORMULAS_DIR = Path(__file__).resolve().parents[2] / "data" / "formulas"

SNAP_STEP = 0.25        # làm tròn về 1/4 beat
SNAP_TOLERANCE = 0.05   # giây; lệch ít hơn thì coi là đúng nhịp


class BeatMapper:
    """Đổi thời gian trên timeline (micro giây) sang vị trí beat của nhạc nền."""

    def __init__(self, grid: BeatGrid, music: Segment):
        self.grid = grid
        self.music_start = music.start
        self.source_start = music.source_start or 0
        self.speed = music.speed or 1.0
        self.errors: list[float] = []

    def music_time(self, t: int) -> float:
        return (self.source_start + (t - self.music_start) * self.speed) / US

    def exact(self, t: int) -> float:
        """Vị trí beat chính xác, không làm tròn; dùng cho keyframe và animation dày."""
        return round(self.grid.to_beat(self.music_time(t)), 4)

    def beat(self, t: int) -> float:
        """Vị trí beat của mốc t; nếu gần một mốc 1/4 beat thì làm tròn và ghi lại sai số."""
        mt = self.music_time(t)
        raw = self.grid.to_beat(mt)
        snapped = round(raw / SNAP_STEP) * SNAP_STEP
        error = abs(self.grid.to_time(snapped) - mt)
        self.errors.append(error)
        return snapped if error <= SNAP_TOLERANCE else round(raw, 4)


def _segment_formula(s: Segment, bm: BeatMapper) -> dict:
    item = {
        "id": s.id,
        "track": s.track_index,
        "track_type": s.track_type,
        "material_type": s.material_type,
        "name": s.material_name,
        "start_beat": bm.beat(s.start),
        "end_beat": bm.beat(s.end),
        "is_slot": s.is_slot,
    }
    if s.keyframes:
        item["keyframes"] = [
            {"property": k.property, "beats": [bm.exact(s.start + o) for o in k.offsets]}
            for k in s.keyframes
        ]
    animations = []
    for ref in s.refs_of("material_animations"):
        for a in ref.raw.get("animations", []):
            start = s.start + a.get("start", 0)
            animations.append({"ref_id": ref.id, "anim_id": a.get("id"), "name": a.get("name", ""),
                               "start_beat": bm.exact(start), "end_beat": bm.exact(start + a.get("duration", 0))})
    if animations:
        item["animations"] = animations
    for ref in s.refs_of("transitions"):
        # transition nằm ở cuối đoạn, độ dài tính bằng beat quanh điểm cắt
        item["transition"] = {"ref_id": ref.id, "name": ref.name,
                              "beats": round(ref.duration / US / bm.grid.period, 4)}
    return item


def learn(draft: DraftInfo, timeline: Timeline | None = None, grid: BeatGrid | None = None) -> dict:
    timeline = timeline or load_timeline(draft.folder)
    music = timeline.music
    if music is None:
        raise ValueError(f"Project {draft.name!r} không có nhạc nền để dò beat")
    grid = grid or detect_beats(music.material_path)
    bm = BeatMapper(grid, music)

    segments = [_segment_formula(s, bm) for s in timeline.segments() if s is not music]
    errors = bm.errors
    on_beat = sum(e <= SNAP_TOLERANCE for e in errors)
    return {
        "version": FORMULA_VERSION,
        "name": draft.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source": {"draft_id": draft.id, "draft_name": draft.name, "folder": str(draft.folder)},
        "canvas": {"width": timeline.width, "height": timeline.height, "fps": timeline.fps},
        "music": {
            "segment_id": music.id,
            "path": music.material_path,
            "source_start_s": round((music.source_start or 0) / US, 4),
            "speed": music.speed,
            "tempo": round(grid.tempo, 3),
        },
        "start_beat": bm.beat(0),
        "end_beat": bm.beat(timeline.duration),
        "slots": [s.id for s in timeline.slots],
        "segments": segments,
        "alignment": {
            "events": len(errors),
            "on_beat_ratio": round(on_beat / len(errors), 3) if errors else 0.0,
            "max_error_ms": round(max(errors) * 1000, 1) if errors else 0.0,
        },
        "beat_grid": grid.to_dict(),
    }


def formula_path(name: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "formula"
    return FORMULAS_DIR / f"{safe}.json"


def save(formula: dict) -> Path:
    path = formula_path(formula["name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(formula, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def list_formulas() -> list[dict]:
    if not FORMULAS_DIR.exists():
        return []
    return sorted((load(p) for p in FORMULAS_DIR.glob("*.json")), key=lambda f: f["created"], reverse=True)


def media_segments(formula: dict) -> list[dict]:
    """Các đoạn ảnh/clip trong công thức, là những đoạn có thể đặt làm ô thay."""
    return sorted((s for s in formula["segments"]
                   if s["track_type"] == "video" and s["material_type"] in ("photo", "video")),
                  key=lambda s: (s["start_beat"], s["track"]))


def set_slots(formula: dict, slot_ids: list[str]) -> Path:
    """Đổi danh sách ô thay theo lựa chọn của bạn rồi lưu lại công thức."""
    chosen = set(slot_ids)
    for s in formula["segments"]:
        s["is_slot"] = s["id"] in chosen
    formula["slots"] = [s["id"] for s in media_segments(formula) if s["id"] in chosen]
    return save(formula)
