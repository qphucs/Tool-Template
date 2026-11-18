"""Tab Từ video mẫu: phân tích video mẫu, tách nhạc và hiện bản hướng dẫn để bạn edit khung mẫu trong CapCut."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QSplitter, QVBoxLayout, QWidget,
)

from ..analyze.guide import build_guide
from ..analyze.run import ANALYSIS_DIR, analyze_video
from ..library import effects as library
from .common import Settings, error, open_capcut, run_in_background

VIDEO_FILTER = "Video (*.mp4 *.mov *.m4v *.mkv *.webm *.avi)"


class _Progress(QObject):
    message = Signal(str)  # phát từ luồng nền, Qt tự chuyển về luồng giao diện


class VideoTab(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.folder: Path | None = None
        self.progress = _Progress()

        self.pick_btn = QPushButton("Chọn video mẫu…")
        self.pick_btn.setObjectName("primary")
        self.read_text = QCheckBox("Đọc chữ (OCR, chậm hơn vài phút)", checked=False)
        self.status = QLabel("Chọn một video mẫu để bắt đầu.")
        self.status.setObjectName("muted")
        self.history = QComboBox()
        self.summary = QLabel(alignment=Qt.AlignCenter)
        self.summary.setMinimumHeight(200)
        scroll = QScrollArea()
        scroll.setWidget(self.summary)
        scroll.setWidgetResizable(True)
        self.guide = QPlainTextEdit(readOnly=True)
        copy_btn = QPushButton("Sao chép hướng dẫn")
        music_btn = QPushButton("Mở thư mục nhạc đã tách")
        capcut_btn = QPushButton("Mở CapCut")

        top = QHBoxLayout()
        top.addWidget(self.pick_btn)
        top.addWidget(self.read_text)
        top.addStretch()
        top.addWidget(QLabel("Đã phân tích:"))
        top.addWidget(self.history, 1)

        steps = QLabel(
            "<b>Cách dùng:</b> 1) Chọn video mẫu, tool tách nhạc và ghi lại nhịp cắt, chuyển động, hiệu ứng. "
            "2) Trong CapCut, edit một project giống video mẫu theo hướng dẫn bên dưới, dùng nhạc đã tách. "
            "3) Sang tab <b>Học mẫu</b> học project đó. 4) Sang tab <b>Tạo mẫu</b> thay ảnh để ra mẫu mới.")
        steps.setWordWrap(True)

        bottom = QHBoxLayout()
        bottom.addWidget(copy_btn)
        bottom.addWidget(music_btn)
        bottom.addStretch()
        bottom.addWidget(capcut_btn)

        split = QSplitter(Qt.Vertical)
        split.addWidget(scroll)
        split.addWidget(self.guide)
        split.setSizes([300, 360])

        layout = QVBoxLayout(self)
        layout.addWidget(steps)
        layout.addLayout(top)
        layout.addWidget(self.status)
        layout.addWidget(split, 1)
        layout.addLayout(bottom)

        self.pick_btn.clicked.connect(self._pick)
        self.history.currentIndexChanged.connect(self._load_selected)
        self.progress.message.connect(self.status.setText)
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.guide.toPlainText()))
        music_btn.clicked.connect(self._open_music)
        capcut_btn.clicked.connect(lambda: open_capcut(self))
        self._reload_history()

    def _reload_history(self, select: Path | None = None) -> None:
        folders = sorted((p for p in ANALYSIS_DIR.glob("*") if (p / "analysis.json").exists()),
                         key=lambda p: (p / "analysis.json").stat().st_mtime, reverse=True) if ANALYSIS_DIR.exists() else []
        self.history.blockSignals(True)
        self.history.clear()
        for p in folders:
            self.history.addItem(p.name[:60], p)
        self.history.blockSignals(False)
        if select is not None:
            self.history.setCurrentIndex(max(self.history.findData(select), 0))
        if folders:
            self._load_selected()

    def _load_selected(self) -> None:
        folder = self.history.currentData()
        if folder is None:
            return
        self._show(Path(folder))

    def _show(self, folder: Path) -> None:
        self.folder = folder
        analysis = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
        pix = QPixmap(str(folder / "summary.jpg"))
        if not pix.isNull():
            self.summary.setPixmap(pix.scaledToWidth(min(pix.width(), 1100), Qt.SmoothTransformation))
        try:
            lib = library.load()
        except Exception:
            lib = None
        self.guide.setPlainText(build_guide(analysis, lib))
        self.status.setText(f"Video: {analysis['video']['path']}")

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn video mẫu", self.settings.get("video_dir"), VIDEO_FILTER)
        if not path:
            return
        self.settings.set("video_dir", str(Path(path).parent))
        self.pick_btn.setEnabled(False)
        read_text = self.read_text.isChecked()
        run_in_background(lambda: analyze_video(path, read_text=read_text, progress=self.progress.message.emit),
                          self._done, self._failed)

    def _done(self, result) -> None:
        self.pick_btn.setEnabled(True)
        _, folder = result
        self._reload_history(select=folder)

    def _failed(self, message: str) -> None:
        self.pick_btn.setEnabled(True)
        self.status.setText("Phân tích lỗi.")
        error(self, message)

    def _open_music(self) -> None:
        if self.folder is None:
            error(self, "Chưa có video nào được phân tích.")
            return
        os.startfile(self.folder)
