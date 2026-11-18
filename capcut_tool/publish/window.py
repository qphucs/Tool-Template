"""Tìm cửa sổ CapCut và chụp màn hình cửa sổ đó (Windows)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

import mss
import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)


@dataclass
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


def window_title(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def window_rect(hwnd: int) -> Rect:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Rect(r.left, r.top, r.right, r.bottom)


def _process_name(hwnd: int) -> str:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = wt.DWORD(260)
        kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value.rsplit("\\", 1)[-1]
    finally:
        kernel32.CloseHandle(handle)


def is_capcut(hwnd: int) -> bool:
    return _process_name(hwnd).lower() == "capcut.exe"


def foreground() -> int:
    return user32.GetForegroundWindow()


def find_capcut() -> int | None:
    """Cửa sổ CapCut lớn nhất đang hiện."""
    found: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd) and is_capcut(hwnd):
            r = window_rect(hwnd)
            found.append((r.width * r.height, hwnd))
        return True

    user32.EnumWindows(callback, 0)
    return max(found)[1] if found else None


def grab(rect: Rect) -> np.ndarray:
    """Chụp vùng màn hình, trả về ảnh BGR cho OpenCV."""
    with mss.MSS() as s:
        img = s.grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
    return np.array(img)[:, :, :3].copy()
