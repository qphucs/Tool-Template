"""Đọc khung hình và tách nhạc từ video mẫu."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..media import find_tool

WORK_WIDTH = 360  # thu nhỏ để phân tích nhanh; đủ chi tiết cho chuyển động và hiệu ứng


@dataclass
class VideoData:
    path: Path
    fps: float
    width: int           # kích thước gốc
    height: int
    frames: list[np.ndarray]  # BGR, đã thu nhỏ về WORK_WIDTH

    @property
    def duration_s(self) -> float:
        return len(self.frames) / self.fps

    def time(self, index: int) -> float:
        return index / self.fps


def load_video(path: str | Path, width: int = WORK_WIDTH) -> VideoData:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Không mở được video {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    size = (width, round(h * width / w))
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(cv2.resize(frame, size, interpolation=cv2.INTER_AREA))
    cap.release()
    if len(frames) < 2:
        raise ValueError(f"Video {path} không có đủ khung hình")
    return VideoData(Path(path), fps, w, h, frames)


def extract_audio(video: str | Path, out: Path) -> Path | None:
    """Tách nhạc ra file m4a. Trả về None nếu video không có tiếng."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [find_tool("ffmpeg"), "-v", "error", "-y", "-i", str(video), "-vn", "-c:a", "aac", "-b:a", "192k", str(out)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
        return None
    return out
