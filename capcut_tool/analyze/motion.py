"""Đo chuyển động của ảnh trong từng cảnh (zoom, trượt, xoay) và rút gọn thành keyframe.

Mỗi khung được căn với khung tham chiếu (khung nét nhất của cảnh) bằng phép biến đổi đồng dạng.
Phần chuyển động mượt thành keyframe; phần dao động nhanh quanh nó được coi là hiệu ứng rung.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .shots import Shot
from .signals import FrameSignals

PROPERTIES = ("scale", "rotation", "x", "y")
# sai số cho phép khi rút gọn keyframe, theo từng thuộc tính
TOLERANCE = {"scale": 0.012, "rotation": 0.6, "x": 0.006, "y": 0.006}


@dataclass
class ShotMotion:
    reference: int                       # khung tham chiếu
    raw: dict[str, np.ndarray]           # giá trị từng khung (scale tương đối, độ xoay, dịch x/y theo bề rộng/cao)
    smooth: dict[str, np.ndarray]
    keyframes: dict[str, list[tuple[int, float]]] = field(default_factory=dict)  # (khung trong cảnh, giá trị)
    jitter: np.ndarray | None = None     # độ rung từng khung (tỉ lệ theo khung hình)
    tracked: np.ndarray | None = None    # khung nào căn được


_orb = cv2.ORB_create(1500)


def _estimate(ref_kp, ref_des, frame: np.ndarray) -> np.ndarray | None:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    kp, des = _orb.detectAndCompute(gray, None)
    if des is None or ref_des is None or len(kp) < 12:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(ref_des, des)
    if len(matches) < 12:
        return None
    src = np.float32([ref_kp[m.queryIdx].pt for m in matches])
    dst = np.float32([kp[m.trainIdx].pt for m in matches])
    m, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
    if m is None or inliers is None or inliers.sum() < 10:
        return None
    return m


def _decompose(m: np.ndarray, w: int, h: int) -> tuple[float, float, float, float]:
    a, b = m[0, 0], m[1, 0]
    scale = float(np.hypot(a, b))
    rotation = float(np.degrees(np.arctan2(b, a)))
    cx, cy = w / 2, h / 2
    nx = m[0, 0] * cx + m[0, 1] * cy + m[0, 2]
    ny = m[1, 0] * cx + m[1, 1] * cy + m[1, 2]
    return scale, rotation, float((nx - cx) / w), float((ny - cy) / h)


def _smooth(values: np.ndarray, k: int = 5) -> np.ndarray:
    if len(values) < k:
        return values.copy()
    pad = np.pad(values, k // 2, mode="edge")
    med = np.array([np.median(pad[i:i + k]) for i in range(len(values))])
    kernel = np.ones(k) / k
    return np.convolve(np.pad(med, k // 2, mode="edge"), kernel, mode="valid")


def _rdp(points: list[tuple[int, float]], tol: float) -> list[tuple[int, float]]:
    """Ramer-Douglas-Peucker: giữ ít điểm nhất mà đường nối vẫn lệch không quá tol."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    worst, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        x, y = points[i]
        expected = y0 + (y1 - y0) * (x - x0) / ((x1 - x0) or 1)
        if abs(y - expected) > worst:
            worst, idx = abs(y - expected), i
    if worst <= tol:
        return [points[0], points[-1]]
    return _rdp(points[:idx + 1], tol)[:-1] + _rdp(points[idx:], tol)


def analyze_shot(frames: list[np.ndarray], shot: Shot, sig: FrameSignals) -> ShotMotion:
    idx = list(shot.frames())
    h, w = frames[0].shape[:2]
    # khung tham chiếu: nét nhất trong nửa giữa cảnh, tránh khung đang có hiệu ứng ở hai đầu
    core = idx[len(idx) // 4: max(len(idx) * 3 // 4, len(idx) // 4 + 1)]
    reference = max(core, key=lambda i: sig.sharpness[i])
    ref_kp, ref_des = _orb.detectAndCompute(cv2.cvtColor(frames[reference], cv2.COLOR_BGR2GRAY), None)

    values = {p: np.full(len(idx), np.nan) for p in PROPERTIES}
    for k, i in enumerate(idx):
        m = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float64) if i == reference else _estimate(ref_kp, ref_des, frames[i])
        if m is not None:
            for p, v in zip(PROPERTIES, _decompose(m, w, h)):
                values[p][k] = v
    tracked = ~np.isnan(values["scale"])
    # khung không căn được (đang mờ, vỡ ảnh…) thì nội suy từ khung lân cận
    for p in PROPERTIES:
        v = values[p]
        if tracked.any():
            v[~tracked] = np.interp(np.flatnonzero(~tracked), np.flatnonzero(tracked), v[tracked])
        else:
            v[:] = 1.0 if p == "scale" else 0.0

    smooth = {p: _smooth(values[p]) for p in PROPERTIES}
    jitter = np.hypot(values["x"] - smooth["x"], values["y"] - smooth["y"])
    keyframes = {p: _rdp([(k, float(v)) for k, v in enumerate(smooth[p])], TOLERANCE[p]) for p in PROPERTIES}
    # bỏ thuộc tính gần như đứng yên
    keyframes = {p: kf for p, kf in keyframes.items()
                 if max(v for _, v in kf) - min(v for _, v in kf) > TOLERANCE[p]}
    return ShotMotion(reference, values, smooth, keyframes, jitter, tracked)
