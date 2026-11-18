"""Phần dùng chung của app: chạy việc nặng ở luồng nền, lưu cài đặt, hộp thoại."""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SETTINGS_PATH = DATA_DIR / "settings.json"


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # báo mọi lỗi lên giao diện thay vì làm app im lặng
            traceback.print_exc()
            self.signals.failed.emit(str(e) or type(e).__name__)
        else:
            self.signals.done.emit(result)


_running: set[_Task] = set()


def run_in_background(fn: Callable[[], Any], on_done: Callable[[Any], None],
                      on_failed: Callable[[str], None]) -> None:
    """Chạy fn ở luồng nền để giao diện không bị đơ (dò beat, ghi project…)."""
    task = _Task(fn)
    _running.add(task)

    def finish(callback, value):
        _running.discard(task)
        callback(value)

    task.signals.done.connect(lambda r: finish(on_done, r))
    task.signals.failed.connect(lambda e: finish(on_failed, e))
    QThreadPool.globalInstance().start(task)


class Settings:
    """Nhớ lựa chọn gần nhất của bạn (thư mục nguyên liệu, gợi ý phong cách…)."""

    def __init__(self):
        try:
            self.data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, key: str, default: Any = "") -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")


def error(parent: QWidget, message: str) -> None:
    QMessageBox.warning(parent, "Có lỗi", message)


def capcut_exe() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "CapCut" / "Apps" / "CapCut.exe"


def open_capcut(parent: QWidget) -> None:
    exe = capcut_exe()
    if exe.exists():
        os.startfile(exe)
    else:
        error(parent, f"Không tìm thấy CapCut ở {exe}")
