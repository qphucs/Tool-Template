"""Nhận diện hiệu ứng theo thời gian và kiểu transition ở mỗi điểm cắt.

Mỗi tín hiệu được so với mức nền của chính cảnh đó, để ảnh vốn mờ hay vốn ám màu không bị nhận nhầm.
Kết quả là *kiểu* hiệu ứng (flash, mờ, rung, glitch…); bước dựng project sẽ chọn hiệu ứng CapCut cùng kiểu.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .motion import ShotMotion
from .shots import Flash, Shot
from .signals import FrameSignals

MIN_EVENT_FRAMES = 1


@dataclass
class Event:
    type: str       # flash, dark_flash, blur, shake, zoom_pulse, rgb_split, pixelate, color_shift
    start: int      # khung
    end: int        # khung (không tính)
    strength: float  # 0..1 tương đối
    shot: int


@dataclass
class Transition:
    cut: int        # khung đầu của cảnh sau
    type: str       # cut, mix, flash, blur, zoom, slide
    start: int
    end: int


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j < n and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _events(kind: str, score: np.ndarray, threshold: float, shot: Shot, scale: float) -> list[Event]:
    out = []
    for a, b in _runs(score > threshold):
        if b - a >= MIN_EVENT_FRAMES:
            out.append(Event(kind, shot.start + a, shot.start + b,
                             float(min(score[a:b].max() / scale, 1.0)), shot.index))
    return out


def detect_events(sig: FrameSignals, shot: Shot, motion: ShotMotion) -> list[Event]:
    idx = np.array(list(shot.frames()))
    events: list[Event] = []

    sharp = sig.sharpness[idx]
    blur_score = 1 - sharp / (np.median(sharp) + 1e-6)
    events += _events("blur", blur_score, 0.55, shot, 1.0)

    luma = sig.luma[idx]
    dip = np.median(luma) - luma
    events += _events("dark_flash", dip, 25, shot, 100)

    events += _events("shake", motion.jitter, 0.008, shot, 0.05)
    pulse = motion.raw["scale"] - motion.smooth["scale"]
    events += _events("zoom_pulse", np.abs(pulse), 0.03, shot, 0.2)
    spin = np.abs(motion.raw["rotation"] - motion.smooth["rotation"])
    events += _events("shake", spin, 1.5, shot, 10)

    split = sig.rgb_split[idx]
    events += _events("rgb_split", split / (np.median(split) + 1e-6) - 1, 0.5, shot, 3)

    block = sig.blockiness[idx]
    events += _events("pixelate", block - np.median(block), 0.12, shot, 0.3)

    hue = sig.hue_shift[idx]
    events += _events("color_shift", np.abs(hue - np.median(hue)), 3.0, shot, 15)
    return _merge(events)


def flash_events(flashes: list[Flash], shots: list[Shot]) -> list[Event]:
    out = []
    for f in flashes:
        shot = next((s.index for s in shots if s.start <= f.start < s.end), 0)
        out.append(Event("flash", f.start, f.end, min(f.strength / 100, 1.0), shot))
    return out


def _merge(events: list[Event], gap: int = 1) -> list[Event]:
    """Gộp các sự kiện cùng kiểu nằm sát nhau."""
    merged: list[Event] = []
    for e in sorted(events, key=lambda e: (e.type, e.start)):
        last = merged[-1] if merged else None
        if last and last.type == e.type and e.start <= last.end + gap:
            last.end = max(last.end, e.end)
            last.strength = max(last.strength, e.strength)
        else:
            merged.append(e)
    return sorted(merged, key=lambda e: e.start)


def _blend_score(frame: np.ndarray, a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Khung có phải là A và B chồng mờ lên nhau không: trả về (alpha, sai số tương đối)."""
    f, a, b = (x.astype(np.float32) for x in (frame, a, b))
    d = (a - b).ravel()
    denom = float(d @ d) or 1.0
    alpha = float(np.clip(((f - b).ravel() @ d) / denom, 0, 1))
    residual = np.abs(f - (alpha * a + (1 - alpha) * b)).mean()
    return alpha, float(residual / (np.abs(a - b).mean() + 1e-6))


def detect_transitions(frames: list[np.ndarray], shots: list[Shot], events: list[Event],
                       motions: list[ShotMotion], fps: float) -> list[Transition]:
    out = []
    span = max(int(0.2 * fps), 3)
    for prev, nxt, m_prev, m_next in zip(shots, shots[1:], motions, motions[1:]):
        cut = nxt.start
        a = frames[max(prev.end - span - 1, prev.start)]
        b = frames[min(nxt.start + span, nxt.end - 1)]
        small = (lambda x: cv2.resize(x, (90, round(90 * x.shape[0] / x.shape[1]))))
        mixed = [i for i in range(cut - span, cut + span)
                 if 0 <= i < len(frames)
                 and (lambda r: 0.15 < r[0] < 0.85 and r[1] < 0.35)(_blend_score(small(frames[i]), small(a), small(b)))]
        near = [e for e in events if e.start <= cut + span and e.end >= cut - span]
        kinds = {e.type for e in near}
        edge_motion = abs(m_next.raw["scale"][0] - m_next.smooth["scale"][min(span, len(m_next.smooth["scale"]) - 1)])
        edge_shift = abs(m_next.raw["x"][0]) + abs(m_prev.raw["x"][-1])
        if len(mixed) >= 2:
            kind, start, end = "mix", min(mixed), max(mixed) + 1
        elif "flash" in kinds:
            kind, start, end = "flash", cut - span, cut + span
        elif "blur" in kinds:
            kind, start, end = "blur", cut - span, cut + span
        elif edge_motion > 0.08:
            kind, start, end = "zoom", cut - span, cut + span
        elif edge_shift > 0.08:
            kind, start, end = "slide", cut - span, cut + span
        else:
            kind, start, end = "cut", cut, cut
        out.append(Transition(cut, kind, max(start, 0), min(end, len(frames))))
    return out
