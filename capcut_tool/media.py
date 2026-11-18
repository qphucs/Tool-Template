"""Gọi FFmpeg/FFprobe để đọc thông tin ảnh, clip, nhạc."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def find_tool(name: str) -> str:
    exe = shutil.which(name)
    if exe:
        return exe
    # winget không cập nhật PATH cho tiến trình đang chạy
    packages = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    found = sorted(packages.glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"))
    if not found:
        raise FileNotFoundError(f"Không tìm thấy {name}")
    return str(found[-1])


@dataclass
class MediaInfo:
    path: Path
    kind: str          # "photo" | "video" | "audio"
    width: int
    height: int
    duration_s: float  # 0 với ảnh
    has_audio: bool


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    cmd = [find_tool("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", str(path)]
    info = json.loads(subprocess.run(cmd, capture_output=True, check=True).stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = float(info.get("format", {}).get("duration") or 0)
    if path.suffix.lower() in IMAGE_EXT:
        kind = "photo"
    elif video is not None and path.suffix.lower() in VIDEO_EXT:
        kind = "video"
    else:
        kind = "audio"
    return MediaInfo(path, kind, int(video.get("width", 0)) if video else 0,
                     int(video.get("height", 0)) if video else 0,
                     0.0 if kind == "photo" else duration, has_audio)
