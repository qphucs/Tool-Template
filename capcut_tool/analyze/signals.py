"""Tín hiệu đo trên từng khung hình, dùng để dò điểm cắt và nhận diện hiệu ứng."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class FrameSignals:
    luma: np.ndarray        # độ sáng trung bình 0..255
    saturation: np.ndarray  # độ bão hòa trung bình 0..255
    hue_shift: np.ndarray   # độ lệch màu (a, b trong Lab) so với trung tính
    sharpness: np.ndarray   # phương sai Laplacian, thấp = mờ
    rgb_split: np.ndarray   # viền màu quanh cạnh (tỉ lệ), cao = glitch tách màu
    blockiness: np.ndarray  # 0..1, cao = vỡ điểm ảnh (pixelate)
    hist: np.ndarray        # histogram HSV đã chuẩn hóa, dùng so sánh nội dung
    diff: np.ndarray        # khác biệt với khung trước (0..255)


def _rgb_split(frame: np.ndarray) -> float:
    """Độ lệch kênh màu quanh các cạnh: khi tách màu, cạnh của kênh đỏ và xanh dương không trùng nhau
    nên hiện viền xanh/tím. Tỉ lệ năng lượng cạnh khác nhau giữa R và B so với cạnh của kênh G."""
    b, g, r = (cv2.Laplacian(c, cv2.CV_32F) for c in cv2.split(frame.astype(np.float32)))
    return float(np.abs(r - b).mean() / (np.abs(g).mean() + 1e-6))


def _blockiness(gray: np.ndarray) -> float:
    """Ảnh bị pixelate gần như không đổi trong từng ô; so với chính nó sau khi gộp ô."""
    best = 0.0
    for block in (8, 12, 16, 24):
        h, w = gray.shape[0] // block * block, gray.shape[1] // block * block
        g = gray[:h, :w].astype(np.float32)
        small = cv2.resize(g, (w // block, h // block), interpolation=cv2.INTER_AREA)
        back = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        texture = g.std() + 1e-3
        best = max(best, 1.0 - float(np.abs(g - back).mean()) / texture)
    return best


def compute(frames: list[np.ndarray]) -> FrameSignals:
    n = len(frames)
    luma, sat, hue, sharp, split, block, diff = (np.zeros(n) for _ in range(7))
    hists = []
    prev = None
    for i, f in enumerate(frames):
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(f, cv2.COLOR_BGR2LAB).astype(np.float32)
        luma[i] = gray.mean()
        sat[i] = hsv[:, :, 1].mean()
        hue[i] = float(np.hypot(lab[:, :, 1].mean() - 128, lab[:, :, 2].mean() - 128))
        sharp[i] = cv2.Laplacian(gray, cv2.CV_32F).var()
        split[i] = _rgb_split(f)
        block[i] = _blockiness(gray)
        h = cv2.calcHist([hsv], [0, 1], None, [24, 16], [0, 180, 0, 256]).flatten()
        hists.append(h / (h.sum() or 1))
        diff[i] = 0 if prev is None else float(cv2.absdiff(gray, prev).mean())
        prev = gray
    return FrameSignals(luma, sat, hue, sharp, split, block, np.array(hists), diff)


def hist_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Khoảng cách Bhattacharyya giữa hai histogram, 0 = giống hệt, 1 = khác hẳn."""
    return float(cv2.compareHist(a.astype(np.float32), b.astype(np.float32), cv2.HISTCMP_BHATTACHARYYA))
