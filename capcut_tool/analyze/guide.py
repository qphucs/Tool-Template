"""Chuyển kết quả phân tích thành bản hướng dẫn dễ đọc, để bạn edit khung mẫu trong CapCut cho giống video mẫu."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np

from ..library.effects import choose

NAMES = {
    "blur": "mờ", "shake": "rung", "rgb_split": "tách màu RGB", "flash": "nháy sáng", "dark_flash": "tối/nháy đen",
    "pixelate": "vỡ điểm ảnh", "zoom_pulse": "zoom nảy", "color_shift": "đổi màu/ám màu",
}
TRANSITIONS = {"mix": "hòa tan (Mix)", "flash": "nháy sáng", "blur": "mờ", "zoom": "zoom", "slide": "trượt", "cut": "cắt thẳng"}
OVERLAYS = {"particles": "hạt lấp lánh", "light_leak": "vệt sáng (light leak)", "texture": "texture/nhiễu",
            "flicker": "lớp nhấp nháy"}


def _beat(b) -> str:
    return f"beat {b:g}" if b is not None else ""


def _motion(kf: dict) -> list[str]:
    out = []
    if "scale" in kf:
        v = [p["value"] for p in kf["scale"]]
        out.append(f"zoom {v[0]:.2f}→{v[-1]:.2f} (lớn nhất {max(v):.2f}, nhỏ nhất {min(v):.2f}), {len(v)} keyframe")
    if "rotation" in kf:
        v = [p["value"] for p in kf["rotation"]]
        out.append(f"xoay {min(v):+.1f}° … {max(v):+.1f}°")
    for axis, label in (("x", "trượt ngang"), ("y", "trượt dọc")):
        if axis in kf:
            v = [p["value"] for p in kf[axis]]
            out.append(f"{label} {min(v) * 100:+.1f}% … {max(v) * 100:+.1f}% khung")
    return out or ["ảnh gần như đứng yên"]


def _rhythm(events: list[dict]) -> str:
    beats = [e["start_beat"] for e in events if e.get("start_beat") is not None]
    if len(beats) < 3:
        return ""
    gap = float(np.median(np.diff(sorted(beats))))
    return f", đều mỗi {gap:.2g} beat" if gap > 0 else ""


def build_guide(analysis: dict, lib: dict | None = None) -> str:
    v, m = analysis["video"], analysis["music"]
    lines = [
        f"Video dài {v['duration_s']:.1f}s · {len(analysis['shots'])} cảnh nên cần {analysis['needs']['photos']} ảnh"
        + (f" · nhạc {m['tempo']:.0f} BPM" if m["tempo"] else " · không có nhạc"),
    ]
    if m["path"]:
        lines.append(f"Nhạc đã tách: {m['path']}  (kéo file này vào CapCut làm nhạc nền)")
    lines.append("")

    by_shot = defaultdict(list)
    for e in analysis["events"]:
        by_shot[e["shot"]].append(e)
    for s in analysis["shots"]:
        lines.append(f"CẢNH {s['index'] + 1}: {s['start_s']:.2f}s → {s['end_s']:.2f}s  ({_beat(s['start_beat'])} → {_beat(s['end_beat'])})")
        for item in _motion(s["keyframes"]):
            lines.append(f"   • Chuyển động: {item}")
        groups = defaultdict(list)
        for e in by_shot[s["index"]]:
            groups[e["type"]].append(e)
        for kind, evs in sorted(groups.items(), key=lambda kv: kv[1][0]["start_s"]):
            pick = choose(lib, "video_effects", kind) if lib else None
            suggest = f" → gợi ý hiệu ứng CapCut: {pick['name']}" if pick else ""
            when = (f"lúc {evs[0]['start_s']:.2f}s" if len(evs) == 1
                    else f"{len(evs)} lần từ {evs[0]['start_s']:.2f}s đến {evs[-1]['start_s']:.2f}s{_rhythm(evs)}")
            lines.append(f"   • {NAMES.get(kind, kind)}: {when}{suggest}")
        lines.append("")

    for t in analysis["transitions"]:
        pick = choose(lib, "transitions", t["type"]) if lib and t["type"] != "cut" else None
        lines.append(f"CHUYỂN CẢNH {t['after_shot'] + 1}→{t['after_shot'] + 2} lúc {t['cut_s']:.2f}s: "
                     f"{TRANSITIONS.get(t['type'], t['type'])}" + (f" → gợi ý: {pick['name']}" if pick else ""))
    if analysis["overlays"]:
        lines.append("")
        lines.append("LỚP PHỦ (cần bạn có file tương tự):")
        for o in analysis["overlays"]:
            lines.append(f"   • {OVERLAYS.get(o['kind'], o['kind'])} {o['start_s']:.1f}–{o['end_s']:.1f}s, "
                         f"hòa trộn {o['blend']}, ảnh minh hoạ: {Path(o['sample']).name}")
    if analysis["texts"]:
        lines.append("")
        lines.append("CHỮ:")
        for t in analysis["texts"]:
            lines.append(f"   • \"{t['text']}\" {t['start_s']:.1f}–{t['end_s']:.1f}s, màu RGB{tuple(t['color'])}")
    return "\n".join(lines)
