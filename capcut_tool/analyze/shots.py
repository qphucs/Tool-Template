"""Dò điểm cắt (chuyển sang ảnh/clip khác) và khung nháy sáng.

Hiệu ứng như glitch hay flash làm khung hình đổi mạnh trong vài khung rồi trở lại; điểm cắt thì
nội dung trước và sau khác hẳn nhau một cách bền vững. Ta chỉ nhận điểm cắt khi thay đổi bền vững.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .signals import FrameSignals, hist_distance

MIN_SHOT_S = 0.25
WINDOW = 5          # số khung lấy trung bình trước/sau điểm cắt
PERSIST_GAP = 8     # kiểm tra lại sau từng này khung để loại thay đổi thoáng qua
CUT_DISTANCE = 0.2


@dataclass
class Shot:
    index: int
    start: int  # khung đầu (tính cả)
    end: int    # khung cuối (không tính)

    def frames(self) -> range:
        return range(self.start, self.end)


@dataclass
class Flash:
    start: int
    end: int
    strength: float  # độ sáng vượt nền, 0..255


def _mean_hist(s: FrameSignals, a: int, b: int) -> np.ndarray:
    a, b = max(a, 0), min(b, len(s.hist))
    return s.hist[a:b].mean(axis=0)


def detect_flashes(s: FrameSignals, threshold: float = 18.0) -> list[Flash]:
    n = len(s.luma)
    excess = np.array([s.luma[i] - np.median(s.luma[max(i - 6, 0):i + 7]) for i in range(n)])
    flashes, i = [], 0
    while i < n:
        if excess[i] > threshold:
            j = i
            while j + 1 < n and excess[j + 1] > threshold / 2:
                j += 1
            flashes.append(Flash(i, j + 1, float(excess[i:j + 1].max())))
            i = j + 1
        else:
            i += 1
    return flashes


def detect_shots(s: FrameSignals, fps: float) -> list[Shot]:
    n = len(s.hist)
    jump = np.zeros(n)
    for i in range(1, n):
        jump[i] = hist_distance(s.hist[i - 1], s.hist[i])
    threshold = max(0.2, float(np.median(jump) + 8 * np.median(np.abs(jump - np.median(jump)))))
    min_len = max(int(MIN_SHOT_S * fps), 2)

    cuts: list[int] = []
    for i in np.argsort(-jump):
        i = int(i)
        if jump[i] < threshold:
            break
        if i < min_len or n - i < min_len or any(abs(i - c) < min_len for c in cuts):
            continue
        before = _mean_hist(s, i - WINDOW, i)
        after = _mean_hist(s, i, i + WINDOW)
        later = _mean_hist(s, i + PERSIST_GAP, i + PERSIST_GAP + WINDOW)
        earlier = _mean_hist(s, i - PERSIST_GAP - WINDOW, i - PERSIST_GAP)
        if (hist_distance(before, after) > CUT_DISTANCE and hist_distance(before, later) > CUT_DISTANCE
                and hist_distance(earlier, after) > CUT_DISTANCE):
            cuts.append(i)
    bounds = [0] + sorted(cuts) + [n]
    return [Shot(k, a, b) for k, (a, b) in enumerate(zip(bounds, bounds[1:]))]
