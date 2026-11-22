"""Link động theo beat: dựng project mới từ công thức trên nhạc có độ dài bất kỳ.

Công thức được chia thành các phần, tính bằng beat của nhạc gốc:

    [đầu ........ | chuyển cảnh | bùng ...... | lặp ............ | kết]
    start_beat    transition    loop_start    ...      loop_end   end_beat

Trên nhạc mới, người dùng chọn beat bắt đầu và beat chuyển cảnh (đánh số theo beat
dò được của nhạc mới). Tool ghép lại:

- Phần đầu: chuyển cảnh sớm hơn công thức thì cắt bớt đuôi phần đầu; muộn hơn thì
  lặp lại đoạn nhịp ngay trước chuyển cảnh (``intro_unit`` beat), không lặp lại
  hiệu ứng mở đầu.
- Đoạn bùng sau chuyển cảnh phát một lần như công thức.
- Đoạn lặp (``loop_start`` -> ``loop_end``) lặp vòng cho tới hết nhạc.
- Phần kết (fade out…) đặt vào cuối nhạc.

Mọi mốc được đổi beat -> giây theo beat thật của nhạc mới, nên hiệu ứng rơi đúng nhịp
kể cả khi nhạc nhanh/chậm khác công thức hoặc tempo không đều.
"""
from __future__ import annotations

import copy
import math
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..audio.beats import BeatGrid, detect_beats
from ..capcut.drafts import US
from .retime import _fix_overlaps, match_tempo

EPS = 1e-6
DEFAULT_PERIOD = 4.0        # chu kỳ lặp mặc định: 4 beat (một ô nhịp)
DENSITIES = (0.5, 1.0, 2.0)  # ½: gộp đôi beat, 1: giữ nguyên, 2: chia đôi beat


# ---------------------------------------------------------------- cấu trúc công thức
@dataclass
class Structure:
    """Các mốc chia phần của công thức, tính bằng beat của nhạc gốc."""
    transition: float
    loop_start: float
    loop_end: float
    intro_unit: float = DEFAULT_PERIOD

    def to_dict(self) -> dict:
        return {k: round(float(v), 4) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, data: dict) -> "Structure":
        return cls(**{k: float(data[k]) for k in ("transition", "loop_start", "loop_end", "intro_unit") if k in data})


def _slot_segments(formula: dict) -> list[dict]:
    slots = set(formula.get("slots") or [])
    return sorted((s for s in formula["segments"] if s["id"] in slots), key=lambda s: s["start_beat"])


def default_structure(formula: dict) -> Structure:
    """Đoán cấu trúc: chuyển cảnh = chỗ đổi sang ô thay thứ hai; đoạn bùng kéo tới khi các
    hiệu ứng dài bắt đầu ngay tại chuyển cảnh kết thúc; đoạn lặp là bội số của 4 beat."""
    start, end = float(formula["start_beat"]), float(formula["end_beat"])
    if "structure" in formula:
        try:
            return clamp_structure(Structure.from_dict(formula["structure"]), formula)
        except (KeyError, TypeError, ValueError):
            pass

    slots = _slot_segments(formula)
    if len(slots) >= 2:
        transition = float(slots[1]["start_beat"])
    else:
        transition = start + round((end - start) / 3)
    transition = min(max(transition, start + 1), end - 1)

    period = DEFAULT_PERIOD
    burst_end = transition
    for s in formula["segments"]:
        if s["track_type"] == "audio":
            continue
        length = s["end_beat"] - s["start_beat"]
        if abs(s["start_beat"] - transition) <= 0.5 and 2 <= length < (end - transition) * 0.8:
            burst_end = max(burst_end, s["end_beat"])
    loop_start = transition + max(1, math.ceil((burst_end - transition - 0.25) / period)) * period
    if loop_start >= end - period:
        loop_start = transition
    loops = max(1, math.floor((end - loop_start - 0.5) / period))
    loop_end = min(loop_start + loops * period, end)
    return clamp_structure(Structure(transition, loop_start, loop_end, period), formula)


def clamp_structure(st: Structure, formula: dict) -> Structure:
    start, end = float(formula["start_beat"]), float(formula["end_beat"])
    t = min(max(st.transition, start + 0.25), end - 0.25)
    ls = min(max(st.loop_start, t), end)
    le = min(max(st.loop_end, ls + 0.25), end)
    if le - ls < 0.25:
        ls, le = t, end
    unit = min(max(st.intro_unit, 0.25), t - start)
    return Structure(t, ls, le, unit)


# ---------------------------------------------------------------- nhạc mới
_GRID_CACHE: dict[tuple[str, float], BeatGrid] = {}


def music_grid(path: str | Path) -> BeatGrid:
    """Dò beat (có cache theo đường dẫn + thời gian sửa file)."""
    p = Path(path)
    key = (str(p.resolve()), p.stat().st_mtime)
    if key not in _GRID_CACHE:
        _GRID_CACHE[key] = detect_beats(p)
    return _GRID_CACHE[key]


def grid_from_dict(data: dict) -> BeatGrid:
    return BeatGrid(float(data["tempo"]), np.asarray(data["times"], dtype=float),
                    np.asarray(data.get("strengths") or [1.0] * len(data["times"]), dtype=float))


def apply_density(grid: BeatGrid, density: float) -> BeatGrid:
    if density >= 1.5:
        return grid.scaled(2)
    if density <= 0.75:
        return grid.scaled(0.5)
    return grid


def auto_density(grid: BeatGrid, formula_tempo: float) -> float:
    """Mật độ beat giúp tempo nhạc mới gần tempo công thức nhất."""
    best = match_tempo(grid, formula_tempo)
    return min(DENSITIES, key=lambda d: abs(apply_density(grid, d).tempo - best.tempo))


@dataclass
class BeatPlan:
    """Lựa chọn của người dùng trên nhạc mới. Chỉ số beat theo lưới đã áp mật độ."""
    density: float = 1.0
    offset_ms: float = 0.0          # dời toàn bộ beat sớm/muộn để khớp tai nghe
    start_index: int = 0            # beat của nhạc mới ứng với beat đầu công thức
    transition_index: int = 13      # beat của nhạc mới đặt chuyển cảnh
    end_index: float | None = None  # None: tới hết nhạc
    remove_effects: list[str] = field(default_factory=list)
    intro_unit: float | None = None  # ghi đè độ dài đoạn nhịp lặp trước chuyển cảnh
    loop_period: float | None = None  # ghi đè độ dài đoạn lặp (beat), None = theo công thức
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BeatPlan":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


def default_plan(formula: dict, grid: BeatGrid, same_music: bool,
                 density: float | None = None, structure: Structure | None = None) -> BeatPlan:
    """Kế hoạch mặc định: chuyển cảnh sau đúng số beat như công thức."""
    st = structure or default_structure(formula)
    start = float(formula["start_beat"])
    if same_music:
        dens = 1.0 if density is None else density
        factor = dens
        return BeatPlan(density=dens, start_index=round(round(start) * factor),
                        transition_index=round(st.transition * factor),
                        end_index=float(formula["end_beat"]) * factor if dens == 1.0 else None)
    dens = auto_density(grid, formula["music"]["tempo"]) if density is None else density
    g = apply_density(grid, dens)
    pick = start - round(start)               # vd -0.25: video bắt đầu trước beat một chút
    first = 0
    while g.to_time(first + pick) < -0.06 and first < len(g.times) - 1:
        first += 1
    intro_beats = round(st.transition - round(start))
    return BeatPlan(density=dens, start_index=first, transition_index=first + intro_beats)


# ---------------------------------------------------------------- ghép các phần
@dataclass
class Piece:
    """Phát đoạn công thức [src_a, src_a + len) tại [out_a, out_b) trên nhạc mới (beat)."""
    out_a: float
    out_b: float
    src_a: float
    part: str

    @property
    def src_b(self) -> float:
        return self.src_a + (self.out_b - self.out_a)


def _cycle(out_a: float, out_b: float, src_a: float, src_b: float, part: str,
           align_end: bool = False) -> list[Piece]:
    """Lặp vòng đoạn nguồn [src_a, src_b) để lấp [out_a, out_b)."""
    length = src_b - src_a
    total = out_b - out_a
    if total <= EPS or length <= EPS:
        return []
    pieces: list[Piece] = []
    pos = out_a
    if align_end:
        # phần lẻ ở đầu, các vòng đủ kết thúc đúng tại out_b
        rem = total - math.floor(total / length + EPS) * length
        if rem > EPS:
            pieces.append(Piece(pos, pos + rem, src_b - rem, part))
            pos += rem
    while out_b - pos > EPS:
        step = min(length, out_b - pos)
        pieces.append(Piece(pos, pos + step, src_a, part))
        pos += step
    return pieces


def plan_pieces(formula: dict, st: Structure, plan: BeatPlan, end_beat_out: float) -> list[Piece]:
    s0, end = float(formula["start_beat"]), float(formula["end_beat"])
    pick = s0 - round(s0)
    m0 = plan.start_index + pick
    mt = float(plan.transition_index)
    me = float(end_beat_out)
    if mt <= m0 + 0.25:
        raise ValueError("Beat chuyển cảnh phải nằm sau beat bắt đầu")
    if me <= mt + 0.25:
        raise ValueError("Nhạc kết thúc trước hoặc ngay tại beat chuyển cảnh, hãy chọn chuyển cảnh sớm hơn")

    unit = plan.intro_unit or st.intro_unit
    unit = min(max(unit, 0.25), st.transition - s0)
    pieces: list[Piece] = []
    intro_src = st.transition - s0
    intro_out = mt - m0
    if intro_out <= intro_src + EPS:
        pieces.append(Piece(m0, mt, s0, "đầu"))                       # chuyển sớm: cắt đuôi
    else:
        pieces.append(Piece(m0, m0 + intro_src, s0, "đầu"))
        pieces += _cycle(m0 + intro_src, mt, st.transition - unit, st.transition,
                         "lặp trước chuyển cảnh", align_end=True)     # chuyển muộn: lặp nhịp

    burst = st.loop_start - st.transition
    outro = end - st.loop_end
    available = me - mt
    if available < burst + outro:
        # nhạc ngắn: ưu tiên giữ phần kết, rút ngắn đoạn bùng
        outro_len = min(outro, available)
        burst_len = max(available - outro_len, 0.0)
        if burst_len > EPS:
            pieces.append(Piece(mt, mt + burst_len, st.transition, "bùng"))
        if outro_len > EPS:
            pieces.append(Piece(me - outro_len, me, end - outro_len if burst_len > EPS else st.loop_end, "kết"))
        return pieces

    if burst > EPS:
        pieces.append(Piece(mt, mt + burst, st.transition, "bùng"))
    loop_src_end = st.loop_end
    if plan.loop_period:
        loop_src_end = min(st.loop_start + plan.loop_period, end)
    pieces += _cycle(mt + burst, me - outro, st.loop_start, loop_src_end, "lặp")
    if outro > EPS:
        pieces.append(Piece(me - outro, me, st.loop_end, "kết"))
    return pieces


# ---------------------------------------------------------------- dựng content
@dataclass
class ComposeResult:
    duration: int               # micro giây
    music_start_s: float
    tempo: float
    pieces: list[Piece]
    kept_slots: list[str]
    removed: list[str]
    beats_us: list[int]         # beat của nhạc mới (micro giây trong file nhạc), để ghi vào CapCut


class _Clock:
    """beat (lưới nhạc mới) -> micro giây trên timeline mới, làm tròn khung hình."""

    def __init__(self, grid: BeatGrid, start_beat: float, offset_s: float, fps: float, end_beat: float,
                 music_duration_s: float):
        self.grid = grid
        self.offset_s = offset_s
        self.fps = fps or 30.0
        self.music_start_s = max(grid.to_time(start_beat) + offset_s, 0.0)
        end_s = min(grid.to_time(end_beat) + offset_s, music_duration_s)
        self.duration = self.frame(end_s - self.music_start_s)
        if self.duration <= 0:
            raise ValueError("Đoạn nhạc được chọn quá ngắn")

    def frame(self, seconds: float) -> int:
        return round(round(seconds * self.fps) * US / self.fps)

    @property
    def frame_us(self) -> int:
        return round(US / self.fps)

    def at(self, beat: float) -> int:
        t = self.frame(self.grid.to_time(beat) + self.offset_s - self.music_start_s)
        return min(max(t, 0), self.duration)

    def period_us(self, beat: float) -> float:
        return (self.grid.to_time(beat + 1) - self.grid.to_time(beat)) * US


def _index(content: dict) -> dict[str, tuple[str, dict]]:
    out = {}
    for category, items in content["materials"].items():
        if isinstance(items, list):
            for m in items:
                if isinstance(m, dict) and "id" in m:
                    out[m["id"]] = (category, m)
    return out


def _new_id() -> str:
    return str(uuid.uuid4()).upper()


def _clone_segment(seg: dict, index: dict, content: dict) -> tuple[dict, dict[str, str]]:
    """Nhân bản đoạn và mọi material nó dùng (mỗi đoạn CapCut có material riêng)."""
    new = copy.deepcopy(seg)
    new["id"] = _new_id()
    mapping: dict[str, str] = {}
    for old in [seg["material_id"], *seg.get("extra_material_refs", [])]:
        if old not in index:
            continue
        category, mat = index[old]
        clone = copy.deepcopy(mat)
        clone["id"] = _new_id()
        content["materials"][category].append(clone)
        index[clone["id"]] = (category, clone)
        mapping[old] = clone["id"]
    new["material_id"] = mapping.get(seg["material_id"], seg["material_id"])
    new["extra_material_refs"] = [mapping.get(r, r) for r in seg.get("extra_material_refs", [])]
    for kf in new.get("common_keyframes", []):
        kf["id"] = str(uuid.uuid4())
        for item in kf.get("keyframe_list", []):
            item["id"] = _new_id()
    return new, mapping


@dataclass
class _Sub:
    out_a: float
    out_b: float
    src_a: float
    src_b: float


def _subs(f: dict, pieces: list[Piece]) -> list[list[_Sub]]:
    """Các lần xuất hiện của đoạn công thức f trên timeline mới, đã gộp phần liền nhau."""
    a0, b0 = f["start_beat"], f["end_beat"]
    point = b0 - a0 < EPS
    found: list[_Sub] = []
    for p in pieces:
        if point:
            if p.src_a - EPS <= a0 < p.src_b - EPS:
                o = p.out_a + (a0 - p.src_a)
                found.append(_Sub(o, o, a0, a0))
            continue
        a, b = max(a0, p.src_a), min(b0, p.src_b)
        if b - a > EPS:
            found.append(_Sub(p.out_a + (a - p.src_a), p.out_a + (b - p.src_a), a, b))
    is_video = f.get("material_type") == "video"
    groups: list[list[_Sub]] = []
    for s in found:
        if groups and not point:
            last = groups[-1][-1]
            joined = abs(last.out_b - s.out_a) < EPS
            if joined and (not is_video or abs(last.src_b - s.src_a) < EPS):
                groups[-1].append(s)
                continue
        groups.append([s])
    return groups


def _interp(items: list[tuple[float, dict]], beat: float) -> list[float]:
    """Giá trị keyframe tại beat (nội suy tuyến tính, ngoài vùng thì giữ giá trị biên)."""
    if beat <= items[0][0]:
        return list(items[0][1].get("values", []))
    if beat >= items[-1][0]:
        return list(items[-1][1].get("values", []))
    for (b1, k1), (b2, k2) in zip(items, items[1:]):
        if b1 <= beat <= b2:
            v1, v2 = k1.get("values", []), k2.get("values", [])
            if len(v1) != len(v2) or b2 - b1 < EPS:
                return list(v1)
            r = (beat - b1) / (b2 - b1)
            return [x + (y - x) * r for x, y in zip(v1, v2)]
    return list(items[-1][1].get("values", []))


def _keyframes(seg: dict, f: dict, group: list[_Sub], clock: _Clock, start_us: int, dur: int) -> None:
    for kf, fk in zip(seg.get("common_keyframes", []), f.get("keyframes", [])):
        raw = kf.get("keyframe_list", [])
        items = sorted(zip(fk["beats"], raw), key=lambda x: x[0])
        if not items:
            continue
        out: dict[int, dict] = {}

        def put(beat_src: float, beat_out: float, template: dict, values: list[float] | None = None):
            item = copy.deepcopy(template)
            item["id"] = _new_id()
            if values is not None:
                item["values"] = values
            t = min(max(clock.at(beat_out) - start_us, 0), dur)
            item["time_offset"] = t
            out[t] = item

        for sub in group:
            shift = sub.out_a - sub.src_a
            put(sub.src_a, sub.out_a, items[0][1], _interp(items, sub.src_a))
            for beat, item in items:
                if sub.src_a < beat < sub.src_b:
                    put(beat, beat + shift, item)
            put(sub.src_b, sub.out_b, items[-1][1], _interp(items, sub.src_b))
        kf["keyframe_list"] = [out[t] for t in sorted(out)]


def _animations(seg: dict, f: dict, index: dict, clock: _Clock, out_start: float, dur: int) -> None:
    beats = {a["anim_id"]: a["end_beat"] - a["start_beat"] for a in f.get("animations", [])}
    period = clock.period_us(out_start)
    for ref in seg.get("extra_material_refs", []):
        category, mat = index.get(ref, ("", {}))
        if category != "material_animations":
            continue
        for a in mat.get("animations", []):
            kind = a.get("type")
            length = beats.get(a.get("id"))
            adur = round(length * period) if length is not None else a.get("duration", 0)
            adur = min(max(adur, 0), dur)
            if kind == "in":
                a["start"], a["duration"] = 0, adur
            elif kind == "out":
                a["start"], a["duration"] = dur - adur, adur
            else:                                   # group / loop: phủ hết đoạn
                a["start"], a["duration"] = 0, dur


def _source(seg: dict, mat: dict, f: dict, group: list[_Sub], formula_time, dur: int) -> None:
    src = seg.get("source_timerange")
    if not src:
        return
    speed = seg.get("speed") or 1.0
    need = round(dur * speed)
    if mat.get("type") == "video":
        offset = (formula_time(group[0].src_a) - formula_time(f["start_beat"])) * speed
        start = src.get("start", 0) + round(offset)
        available = mat.get("duration") or need
        src["start"] = max(0, min(start, available - need))
    elif mat.get("type") == "photo":
        src["start"] = 0
    src["duration"] = need


def _formula_clock(formula: dict, content: dict):
    """beat công thức -> micro giây trên timeline gốc (để tính điểm bắt đầu trong clip)."""
    grid = grid_from_dict(formula["beat_grid"])
    music = next((s for t in content["tracks"] for s in t["segments"]
                  if s["id"] == formula["music"]["segment_id"]), None)
    music_start = music["target_timerange"]["start"] if music else 0
    src0 = formula["music"].get("source_start_s", 0.0)
    speed = formula["music"].get("speed") or 1.0
    return lambda b: music_start + (grid.to_time(b) - src0) / speed * US


def _matches(name: str, removed: list[str]) -> bool:
    low = (name or "").lower()
    return any(r and r.lower() in low for r in removed)


def compose(content: dict, formula: dict, grid: BeatGrid, music_duration_s: float,
            plan: BeatPlan, structure: Structure | None = None) -> ComposeResult:
    """Sửa trực tiếp content (draft_content.json của project mẫu) theo nhạc mới."""
    st = clamp_structure(structure or default_structure(formula), formula)
    g = apply_density(grid, plan.density)
    end_beat_out = plan.end_index if plan.end_index is not None else g.to_beat(music_duration_s - plan.offset_ms / 1000)
    pieces = plan_pieces(formula, st, plan, end_beat_out)
    s0 = float(formula["start_beat"])
    clock = _Clock(g, plan.start_index + (s0 - round(s0)), plan.offset_ms / 1000,
                   formula["canvas"].get("fps") or 30.0, end_beat_out, music_duration_s)

    index = _index(content)
    formula_time = _formula_clock(formula, content)
    by_id = {s["id"]: (ti, s) for ti, t in enumerate(content["tracks"]) for s in t["segments"]}
    missing = [f["id"] for f in formula["segments"] if f["id"] not in by_id]
    if missing:
        raise ValueError(f"Project mẫu đã bị sửa sau khi học, thiếu {len(missing)} đoạn. Hãy học lại công thức.")

    drop: set[str] = set()
    removed: list[str] = []
    new_segments: list[tuple[int, dict]] = []
    for f in formula["segments"]:
        ti, seg = by_id[f["id"]]
        if f["track_type"] == "effect" and _matches(f.get("name", ""), plan.remove_effects):
            drop.add(f["id"])
            removed.append(f.get("name", ""))
            continue
        groups = _subs(f, pieces)
        if not groups:
            drop.add(f["id"])
            continue
        template = copy.deepcopy(seg)  # bản gốc chưa sửa, để nhân bản
        # hiệu ứng chớp 1-2 khung hình: giữ đúng độ dài gốc, không co giãn theo beat
        point = (f["end_beat"] - f["start_beat"] < EPS
                 or seg["target_timerange"]["duration"] <= 2.5 * US / (formula["canvas"].get("fps") or 30.0))
        for gi, group in enumerate(groups):
            start_us = clock.at(group[0].out_a)
            if start_us >= clock.duration:
                if gi == 0:
                    drop.add(seg["id"])
                continue
            if gi == 0:
                target = seg
            else:
                target, _ = _clone_segment(template, index, content)
                new_segments.append((ti, target))
            if point:
                dur = max(template["target_timerange"]["duration"], clock.frame_us)
            else:
                dur = max(clock.at(group[-1].out_b) - start_us, clock.frame_us)
            dur = max(min(dur, clock.duration - start_us), 1)
            target["target_timerange"] = {"start": start_us, "duration": dur}
            mat = index.get(target["material_id"], ("", {}))[1]
            _source(target, mat, f, group, formula_time, dur)
            _keyframes(target, f, group, clock, start_us, dur)
            _animations(target, f, index, clock, group[0].out_a, dur)
            if "transition" in f:
                tr_id = next((r for r in target.get("extra_material_refs", [])
                              if index.get(r, ("", {}))[0] == "transitions"), None)
                if tr_id:
                    tr = index[tr_id][1]
                    tr["duration"] = min(round(f["transition"]["beats"] * clock.period_us(group[-1].out_b)), dur)

    for ti, seg in new_segments:
        content["tracks"][ti]["segments"].append(seg)
    for track in content["tracks"]:
        track["segments"] = [s for s in track["segments"] if s["id"] not in drop]
    _fix_overlaps(content, clock.frame_us)
    content["duration"] = clock.duration

    kept = [sid for sid in formula.get("slots", []) if sid not in drop]
    lo, hi = clock.music_start_s, clock.music_start_s + clock.duration / US
    beats_us = [round((t + plan.offset_ms / 1000) * US) for t in g.times if lo - 0.01 <= t + plan.offset_ms / 1000 <= hi + 0.01]
    return ComposeResult(clock.duration, clock.music_start_s, g.tempo, pieces, kept, sorted(set(removed)), beats_us)


def write_beat_marks(content: dict, music_segment_id: str, beats_us: list[int]) -> None:
    """Ghi beat đã dò vào điểm beat của đoạn nhạc để thấy vạch beat trong CapCut."""
    seg = next((s for t in content["tracks"] for s in t["segments"] if s["id"] == music_segment_id), None)
    if seg is None:
        return
    for ref in seg.get("extra_material_refs", []):
        for b in content["materials"].get("beats", []):
            if b["id"] == ref:
                b["user_beats"] = list(beats_us)
