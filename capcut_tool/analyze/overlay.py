"""Phát hiện lớp phủ (light leak, hạt, texture, lớp nháy) bằng phần dư sau khi bù chuyển động của ảnh.

Ảnh trong một cảnh là ảnh tĩnh; sau khi căn mọi khung về khung tham chiếu, phần nào vẫn thay đổi mà
không phải do hiệu ứng toàn khung (mờ, tối, ám màu) thì là lớp phủ. Không tách được file lớp phủ gốc,
nên ta lưu ảnh minh hoạ để bạn tìm hoặc đưa file tương tự.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .effects import Event
from .motion import ShotMotion
from .shots import Shot

GLOBAL_EVENTS = {"blur", "dark_flash", "flash", "color_shift", "pixelate", "rgb_split", "shake", "zoom_pulse"}
EDGE_ONLY = 0.6  # phần dư nằm trên cạnh quá tỉ lệ này thì không phải lớp phủ


@dataclass
class Overlay:
    kind: str        # light_leak, particles, texture, flicker
    start: int
    end: int
    coverage: float  # phần diện tích khung bị phủ, 0..1
    blend: str       # screen (sáng lên), multiply (tối đi), normal
    sample: str = "" # đường dẫn ảnh minh hoạ


def to_reference(motion: ShotMotion, k: int, w: int, h: int) -> np.ndarray:
    """Ma trận đưa khung thứ k của cảnh về khung tham chiếu, cho ảnh kích thước w x h."""
    s, r = motion.raw["scale"][k], np.radians(motion.raw["rotation"][k])
    dx, dy = motion.raw["x"][k] * w, motion.raw["y"][k] * h
    a, b = s * np.cos(r), s * np.sin(r)
    cx, cy = w / 2, h / 2
    return cv2.invertAffineTransform(np.array([[a, -b, cx + dx - (a * cx - b * cy)], [b, a, cy + dy - (b * cx + a * cy)]]))


def _aligned(frames, shot: Shot, motion: ShotMotion, screen_static: np.ndarray):
    """Căn mọi khung về khung tham chiếu. Trả về ảnh đã căn và mặt nạ vùng dùng được của từng khung:
    vùng nằm trong khung hình thật và không phải điểm đứng yên trên màn hình (logo, watermark)."""
    h, w = frames[0].shape[:2]
    usable_screen = (~screen_static).astype(np.uint8) * 255
    images, masks = [], []
    for k, i in enumerate(shot.frames()):
        m = to_reference(motion, k, w, h)
        images.append(cv2.warpAffine(frames[i], m, (w, h), borderMode=cv2.BORDER_REPLICATE))
        valid = cv2.warpAffine(usable_screen, m, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        masks.append(cv2.erode(valid, np.ones((7, 7), np.uint8)) > 0)
    return images, masks


def screen_static_mask(frames, threshold: float = 4.0) -> np.ndarray:
    """Điểm gần như không đổi trên màn hình suốt video (logo, watermark) trong khi nội dung chuyển động."""
    gray = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames[:: max(len(frames) // 60, 1)]]).astype(np.float32)
    static = gray.std(axis=0) < threshold
    return cv2.dilate(static.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0


def detect_overlays(frames, shot: Shot, motion: ShotMotion, events: list[Event], out_dir: Path,
                    screen_static: np.ndarray) -> list[Overlay]:
    aligned, masks = _aligned(frames, shot, motion, screen_static)
    if len(aligned) < 6:
        return []
    stack = np.stack(aligned).astype(np.float32)
    base = np.median(stack, axis=0)
    skip = {e_i for e in events if e.type in GLOBAL_EVENTS and e.shot == shot.index
            for e_i in range(e.start - shot.start, e.end - shot.start)}

    edges = cv2.dilate(cv2.Canny(base.astype(np.uint8), 60, 160), np.ones((5, 5), np.uint8)) > 0
    per_frame = []
    for k, f in enumerate(stack):
        usable = masks[k]
        if k in skip or usable.mean() < 0.3:
            per_frame.append(None)
            continue
        signed = (f - base).mean(axis=2)
        diff = np.abs(signed)
        mask = (diff > 18) & usable
        if mask.any() and (mask & edges).sum() / mask.sum() > EDGE_ONLY:
            per_frame.append(None)  # chỉ lệch ở cạnh: viền tách màu hoặc căn khung chưa khớp
            continue
        coverage = float(mask.sum() / usable.sum())
        per_frame.append((coverage, float(signed[mask].mean()) if mask.any() else 0.0,
                          float(cv2.Laplacian(diff * usable, cv2.CV_32F).var()), mask))

    covered = np.array([p is not None and p[0] > 0.04 for p in per_frame])
    overlays = []
    for a, b in _runs(covered):
        if b - a < 3:
            continue
        stats = [per_frame[k] for k in range(a, b)]
        coverage = float(np.mean([s[0] for s in stats]))
        brightness = float(np.mean([s[1] for s in stats]))
        texture = float(np.mean([s[2] for s in stats]))
        blobs = np.mean([cv2.connectedComponents(s[3].astype(np.uint8))[0] for s in stats])
        if blobs > 40:
            kind = "particles"
        elif texture > 400 and coverage > 0.3:
            kind = "texture"
        elif brightness > 0 and coverage > 0.1:
            kind = "light_leak"
        else:
            kind = "flicker"
        blend = "screen" if brightness > 4 else "multiply" if brightness < -4 else "normal"
        mid = (a + b) // 2
        out_dir.mkdir(parents=True, exist_ok=True)
        sample = out_dir / f"overlay_shot{shot.index}_{shot.start + a}.jpg"
        vis = np.clip(np.abs(stack[mid] - base) * 2, 0, 255).astype(np.uint8)
        cv2.imwrite(str(sample), np.hstack([aligned[mid], vis]))
        overlays.append(Overlay(kind, shot.start + a, shot.start + b, coverage, blend, str(sample)))
    return overlays


PARTICLE_MIN = 12   # số chấm sáng nhấp nháy trung bình mỗi khung để coi là có lớp hạt
PARTICLE_SAMPLES = 16


def _flat_background(gray: np.ndarray) -> np.ndarray:
    """Vùng nền phẳng: sau khi xoá chấm nhỏ (median 5x5), độ lệch chuẩn cục bộ rất thấp."""
    bg = cv2.medianBlur(gray, 5).astype(np.float32)
    mean = cv2.blur(bg, (11, 11))
    std = np.sqrt(np.maximum(cv2.blur(bg * bg, (11, 11)) - mean * mean, 0))
    return std < 3.5


def detect_particles(read_frame, shot: Shot, motion: ShotMotion, events: list[Event], out_dir: Path) -> Overlay | None:
    """Lớp hạt lấp lánh (bụi, sao) rất nhỏ, chỉ thấy ở độ phân giải gốc.

    Lấy mẫu vài khung gốc không có hiệu ứng, căn về khung tham chiếu, tách chấm sáng nhỏ bằng phép
    top-hat rồi đếm chấm không có ở khung trung vị: hạt nhấp nháy và trôi, chi tiết của ảnh thì đứng yên.
    """
    busy = {i for e in events if e.shot == shot.index for i in range(e.start - 1, e.end + 1)}
    idx = [i for i in shot.frames() if i not in busy]
    picks = idx[:: max(len(idx) // PARTICLE_SAMPLES, 1)]
    spots, flats = [], []
    for i in picks:
        frame = read_frame(i)
        if frame is None:
            continue
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        aligned = cv2.warpAffine(gray, to_reference(motion, i - shot.start, w, h), (w, h), borderMode=cv2.BORDER_REPLICATE)
        spots.append(cv2.morphologyEx(aligned, cv2.MORPH_TOPHAT, np.ones((7, 7), np.uint8)))
        flats.append(_flat_background(aligned))
    if len(spots) < 4:
        return None
    stack = np.stack(spots).astype(np.float32)
    steady = np.median(stack, axis=0)
    counts = []
    for s, flat in zip(stack, flats):
        # hạt là chấm sáng nhỏ nằm trên nền phẳng; vân đường, lá cây không phẳng nên không bị đếm nhầm
        twinkle = (((s - steady) > 18) & flat).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(twinkle)
        counts.append(int(((stats[1:, cv2.CC_STAT_AREA] >= 1) & (stats[1:, cv2.CC_STAT_AREA] <= 40)).sum()))
    if np.median(counts) < PARTICLE_MIN:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = out_dir / f"particles_shot{shot.index}.jpg"
    best = int(np.argmax(counts))
    vis = np.clip((stack[best] - steady) * 4, 0, 255).astype(np.uint8)
    cv2.imwrite(str(sample), cv2.resize(vis, (vis.shape[1] // 2, vis.shape[0] // 2)))
    return Overlay("particles", shot.start, shot.end, float(np.median(counts)) / 1000, "screen", str(sample))


def _runs(mask):
    runs, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    return runs
