"""Chạy toàn bộ phân tích video mẫu và lưu kết quả.

    python -m capcut_tool.analyze.run <video> [--no-text]

Kết quả nằm trong data/analysis/<tên video>/:
    analysis.json   mọi thứ bóc tách được, thời gian tính bằng giây và vị trí beat
    music.m4a       nhạc tách từ video
    summary.jpg     ảnh tóm tắt: khung đại diện từng cảnh và dải thời gian hiệu ứng
    overlays/       ảnh minh hoạ lớp phủ cần bạn đưa file
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..audio.beats import BeatGrid, detect_beats
from . import effects, motion, overlay, shots, signals, text
from .frames import extract_audio, load_video

ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "data" / "analysis"
ANALYSIS_VERSION = 1

COLORS = {  # màu từng kiểu hiệu ứng trên dải thời gian (BGR)
    "flash": (255, 255, 255), "dark_flash": (90, 90, 90), "blur": (230, 160, 60), "shake": (60, 160, 240),
    "zoom_pulse": (80, 220, 120), "rgb_split": (220, 80, 220), "pixelate": (60, 220, 220), "color_shift": (40, 90, 230),
    "particles": (200, 200, 120), "light_leak": (90, 180, 255), "texture": (150, 150, 150), "flicker": (180, 120, 200),
    "text": (255, 220, 120),
}


def _folder_for(video: Path) -> Path:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", video.stem)[:60]
    return ANALYSIS_DIR / safe


def analyze_video(path: str | Path, read_text: bool = True,
                  progress: Callable[[str], None] = print) -> tuple[dict, Path]:
    video = Path(path)
    out = _folder_for(video)
    out.mkdir(parents=True, exist_ok=True)

    progress("Đọc khung hình…")
    v = load_video(video)
    progress("Tách nhạc và dò beat…")
    music = extract_audio(video, out / "music.m4a")
    grid: BeatGrid | None = detect_beats(music) if music else None
    beat = (lambda f: round(grid.to_beat(f / v.fps), 3)) if grid else (lambda f: None)

    progress("Đo tín hiệu từng khung…")
    sig = signals.compute(v.frames)
    progress("Dò điểm cắt…")
    shot_list = shots.detect_shots(sig, v.fps)
    progress(f"Đo chuyển động {len(shot_list)} cảnh…")
    motions = [motion.analyze_shot(v.frames, s, sig) for s in shot_list]

    progress("Nhận diện hiệu ứng và transition…")
    events = effects.flash_events(shots.detect_flashes(sig), shot_list)
    for s, m in zip(shot_list, motions):
        events += effects.detect_events(sig, s, m)
    events.sort(key=lambda e: e.start)
    transitions = effects.detect_transitions(v.frames, shot_list, events, motions, v.fps)

    progress("Tìm lớp phủ…")
    static = overlay.screen_static_mask(v.frames)
    read_full = text.frame_reader(video)
    overlays = []
    for s, m in zip(shot_list, motions):
        overlays += overlay.detect_overlays(v.frames, s, m, events, out / "overlays", static)
        particles = overlay.detect_particles(read_full, s, m, events, out / "overlays")
        if particles:
            overlays.append(particles)

    texts = []
    if read_text:
        progress("Đọc chữ (OCR, có thể mất vài phút)…")
        texts = text.read_texts(v.frames, v.fps, read_full, list(zip(shot_list, motions)))

    sec = lambda f: round(f / v.fps, 3)
    result = {
        "version": ANALYSIS_VERSION,
        "created": datetime.now().isoformat(timespec="seconds"),
        "video": {"path": str(video), "fps": v.fps, "width": v.width, "height": v.height,
                  "duration_s": round(v.duration_s, 3), "frames": len(v.frames)},
        "music": {"path": str(music) if music else None,
                  "tempo": round(grid.tempo, 2) if grid else None,
                  "beat_grid": grid.to_dict() if grid else None},
        "shots": [{
            "index": s.index, "start_s": sec(s.start), "end_s": sec(s.end),
            "start_beat": beat(s.start), "end_beat": beat(s.end),
            "reference_s": sec(m.reference),
            "tracked_ratio": round(float(m.tracked.mean()), 3),
            "keyframes": {p: [{"t_s": sec(s.start + k), "beat": beat(s.start + k), "value": round(val, 4)}
                              for k, val in kf] for p, kf in m.keyframes.items()},
        } for s, m in zip(shot_list, motions)],
        "events": [{"type": e.type, "shot": e.shot, "start_s": sec(e.start), "end_s": sec(e.end),
                    "start_beat": beat(e.start), "end_beat": beat(e.end), "strength": round(e.strength, 3)}
                   for e in events],
        "transitions": [{"after_shot": i, "type": t.type, "cut_s": sec(t.cut), "cut_beat": beat(t.cut),
                         "start_s": sec(t.start), "end_s": sec(t.end)} for i, t in enumerate(transitions)],
        "overlays": [{**asdict(o), "start_s": sec(o.start), "end_s": sec(o.end)} for o in overlays],
        "texts": [{"text": t.text, "start_s": sec(t.start), "end_s": sec(t.end), "start_beat": beat(t.start),
                   "box": [round(b, 4) for b in t.box], "color": t.color,
                   "height_ratio": round(t.height_ratio, 4), "confidence": round(t.confidence, 3)} for t in texts],
        "needs": {
            "photos": len(shot_list),
            "overlays": [{"kind": o.kind, "blend": o.blend, "start_s": sec(o.start), "end_s": sec(o.end),
                          "sample": o.sample} for o in overlays],
        },
    }
    (out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    progress("Vẽ ảnh tóm tắt…")
    _summary_image(v, shot_list, motions, events, overlays, texts, grid, out / "summary.jpg")
    progress("Xong.")
    return result, out


def _summary_image(v, shot_list, motions, events, overlays, texts, grid, path: Path) -> None:
    """Hàng trên: khung đầu, khung tham chiếu, khung cuối của từng cảnh. Hàng dưới: dải thời gian."""
    thumb_w = 120
    thumbs = []
    for s, m in zip(shot_list, motions):
        for i in (s.start, m.reference, s.end - 1):
            f = v.frames[i]
            t = cv2.resize(f, (thumb_w, round(f.shape[0] * thumb_w / f.shape[1])))
            cv2.putText(t, f"{i / v.fps:.1f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            thumbs.append(t)
        thumbs.append(np.full((thumbs[-1].shape[0], 8, 3), 30, np.uint8))
    top = np.hstack(thumbs)
    width = max(top.shape[1], 900)
    rows = sorted({e.type for e in events} | {o.kind for o in overlays} | ({"text"} if texts else set()))
    row_h, label_w = 22, 110
    timeline = np.full((row_h * (len(rows) + 2), width, 3), 24, np.uint8)
    x_of = lambda f: label_w + int((width - label_w - 10) * f / len(v.frames))
    if grid is not None:
        for t in grid.times:
            if t <= v.duration_s:
                cv2.line(timeline, (x_of(t * v.fps), 0), (x_of(t * v.fps), row_h - 6), (110, 110, 110), 1)
    cv2.putText(timeline, "beat", (6, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)
    for s in shot_list[1:]:
        cv2.line(timeline, (x_of(s.start), 0), (x_of(s.start), timeline.shape[0]), (0, 0, 255), 2)
    spans = [(e.type, e.start, e.end) for e in events] + [(o.kind, o.start, o.end) for o in overlays] + \
            [("text", t.start, t.end) for t in texts]
    for r, kind in enumerate(rows, start=1):
        y = r * row_h
        cv2.putText(timeline, kind, (6, y + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1, cv2.LINE_AA)
        for k, a, b in spans:
            if k == kind:
                cv2.rectangle(timeline, (x_of(a), y + 4), (max(x_of(b), x_of(a) + 2), y + row_h - 4), COLORS.get(k, (200, 200, 200)), -1)
    if top.shape[1] < width:
        top = np.hstack([top, np.full((top.shape[0], width - top.shape[1], 3), 24, np.uint8)])
    cv2.imwrite(str(path), np.vstack([top, timeline]))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    if not Path(args[0]).is_file():
        print(f"Không tìm thấy video: {args[0]}\n"
              "Hãy thay bằng đường dẫn thật, ví dụ: chuột phải vào file video > Copy as path, rồi dán vào lệnh.")
        sys.exit(1)
    result, folder = analyze_video(args[0], read_text="--no-text" not in sys.argv)
    print(f"\n{len(result['shots'])} cảnh (cần {result['needs']['photos']} ảnh), {len(result['events'])} hiệu ứng, "
          f"{len(result['transitions'])} transition, {len(result['overlays'])} lớp phủ, {len(result['texts'])} chữ, "
          f"nhạc {result['music']['tempo']} BPM\nKết quả: {folder}")
