"""Dò beat của file nhạc và đổi qua lại giữa giây và vị trí beat."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np

from ..media import find_tool

SR = 22050
HOP = 256  # ~11.6 ms mỗi bước, mịn hơn mặc định 512 để điểm cắt sát khung hình


def load_audio(path: str | Path) -> np.ndarray:
    """Giải mã mọi định dạng nhạc (m4a, mp3, wav…) thành mono float32 bằng FFmpeg."""
    cmd = [find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


@dataclass
class BeatGrid:
    """Danh sách thời điểm beat (giây, tính từ đầu file nhạc)."""
    tempo: float
    times: np.ndarray
    strengths: np.ndarray  # độ mạnh tương đối 0..1 tại mỗi beat

    @property
    def period(self) -> float:
        return 60.0 / self.tempo

    def to_beat(self, t: float) -> float:
        """Giây -> vị trí beat (số thực). Ngoài vùng có beat thì ngoại suy theo tempo."""
        times = self.times
        if t <= times[0]:
            return (t - times[0]) / self.period
        if t >= times[-1]:
            return len(times) - 1 + (t - times[-1]) / self.period
        i = int(np.searchsorted(times, t, side="right")) - 1
        return i + (t - times[i]) / (times[i + 1] - times[i])

    def to_time(self, b: float) -> float:
        """Vị trí beat -> giây. Ngược lại của to_beat."""
        times = self.times
        if b <= 0:
            return times[0] + b * self.period
        last = len(times) - 1
        if b >= last:
            return times[-1] + (b - last) * self.period
        i = int(b)
        return times[i] + (b - i) * (times[i + 1] - times[i])

    def scaled(self, factor: float) -> "BeatGrid":
        """factor 2: thêm beat ở giữa mỗi cặp beat (nửa nhịp); factor 0.5: chỉ giữ beat chẵn."""
        if factor == 2:
            mids = (self.times[:-1] + self.times[1:]) / 2
            times = np.empty(len(self.times) + len(mids))
            times[0::2], times[1::2] = self.times, mids
            strengths = np.empty_like(times)
            strengths[0::2], strengths[1::2] = self.strengths, self.strengths[:-1] / 2
            return BeatGrid(self.tempo * 2, times, strengths)
        if factor == 0.5:
            return BeatGrid(self.tempo / 2, self.times[0::2], self.strengths[0::2])
        return self

    def to_dict(self) -> dict:
        return {"tempo": round(self.tempo, 3), "times": [round(float(t), 4) for t in self.times],
                "strengths": [round(float(s), 3) for s in self.strengths]}


def detect_beats(path: str | Path) -> BeatGrid:
    y = load_audio(path)
    onset = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    tempo, frames = librosa.beat.beat_track(onset_envelope=onset, sr=SR, hop_length=HOP,
                                            units="frames", trim=False)
    if len(frames) < 2:
        raise ValueError(f"Không dò được beat trong {path}")
    times = librosa.frames_to_time(frames, sr=SR, hop_length=HOP)
    strengths = onset[frames] / (onset[frames].max() or 1.0)
    return BeatGrid(float(np.atleast_1d(tempo)[0]), times, strengths)
