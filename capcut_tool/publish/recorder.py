"""Ghi lại quy trình đăng mẫu: mỗi lần bấm chuột trong cửa sổ CapCut thì chụp màn hình và lưu vị trí.

    python -m capcut_tool.publish.recorder

Chỉ ghi khi CapCut đang ở trên cùng. Chỉ ghi vị trí chuột, không ghi phím gõ.
Nhấn F10 (hoặc Ctrl+C trong cửa sổ dòng lệnh) để dừng.
"""
from __future__ import annotations

import ctypes
import json
import time
from datetime import datetime
from pathlib import Path

import cv2

from .window import find_capcut, foreground, grab, is_capcut, window_rect, window_title

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "data" / "publish_recording"
VK_LBUTTON, VK_F10 = 0x01, 0x79
CROP = 60  # nửa cạnh vùng cắt quanh điểm bấm, dùng làm ảnh mẫu để nhận diện nút

user32 = ctypes.WinDLL("user32", use_last_error=True)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _pressed(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _cursor() -> tuple[int, int]:
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def record() -> Path:
    # để tọa độ chuột và ảnh chụp cùng hệ pixel thật khi Windows đang phóng to giao diện
    ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    session = RECORDINGS_DIR / datetime.now().strftime("session_%Y%m%d_%H%M%S")
    session.mkdir(parents=True)
    steps = []
    print(f"Đang ghi vào {session}\nThao tác trong CapCut như bình thường. Nhấn F10 để dừng.")

    hwnd = find_capcut()
    if hwnd:
        cv2.imwrite(str(session / "step_00_start.png"), grab(window_rect(hwnd)))

    was_down = False
    try:
        while not _pressed(VK_F10):
            down = _pressed(VK_LBUTTON)
            if down and not was_down:
                fg = foreground()
                if is_capcut(fg):
                    x, y = _cursor()
                    rect = window_rect(fg)
                    shot = grab(rect)  # chụp ngay lúc bấm, trước khi giao diện đổi
                    n = len(steps) + 1
                    rx, ry = x - rect.left, y - rect.top
                    crop = shot[max(ry - CROP, 0):ry + CROP, max(rx - CROP, 0):rx + CROP]
                    marked = shot.copy()
                    cv2.circle(marked, (rx, ry), 18, (0, 0, 255), 3)
                    if shot.size:  # cửa sổ con của CapCut có thể rất nhỏ hoặc đang ẩn
                        cv2.imwrite(str(session / f"step_{n:02d}.png"), marked)
                    if crop.size:
                        cv2.imwrite(str(session / f"step_{n:02d}_crop.png"), crop)
                    steps.append({
                        "step": n, "time": datetime.now().isoformat(timespec="seconds"),
                        "window_title": window_title(fg),
                        "window": [rect.left, rect.top, rect.width, rect.height],
                        "click": [rx, ry],
                        "click_rel": [round(rx / rect.width, 4), round(ry / rect.height, 4)],
                    })
                    (session / "steps.json").write_text(json.dumps(steps, ensure_ascii=False, indent=1), encoding="utf-8")
                    print(f"  bước {n}: bấm tại ({rx}, {ry}) trong cửa sổ {window_title(fg)!r}")
            was_down = down
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass

    hwnd = find_capcut()
    if hwnd:
        cv2.imwrite(str(session / "step_99_end.png"), grab(window_rect(hwnd)))
    print(f"Đã dừng. Ghi được {len(steps)} bước.")
    return session


if __name__ == "__main__":
    record()
