"""Tab Đăng: hồ sơ các mẫu đã tạo, sửa tiêu đề/hashtag, sao chép để dán vào CapCut khi đăng."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..caption.writer import TemplateInfo, write_caption
from ..generate.build import OUTPUTS_DIR
from .common import error, open_capcut, run_in_background

PENDING, POSTED = "chờ đăng", "đã đăng"


class PublishTab(QWidget):
    def __init__(self):
        super().__init__()
        self.records: list[tuple[Path, dict]] = []
        self.current: tuple[Path, dict] | None = None

        self.show_posted = QCheckBox("Hiện cả mẫu đã đăng")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Project", "Tạo lúc", "Trạng thái"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        left = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("<b>Mẫu đã tạo</b>"))
        row.addStretch()
        row.addWidget(self.show_posted)
        left.addLayout(row)
        left.addWidget(self.table, 1)

        self.info = QLabel(wordWrap=True)
        self.title = QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(90)
        self.hashtags = QLineEdit()
        self.source = QLabel()
        self.source.setObjectName("muted")
        copy_title = QPushButton("Sao chép tiêu đề")
        copy_desc = QPushButton("Sao chép mô tả + hashtag")
        self.rewrite_btn = QPushButton("Nhờ AI viết lại")
        save_btn = QPushButton("Lưu")
        open_btn = QPushButton("Mở CapCut")
        self.posted_btn = QPushButton("Đánh dấu đã đăng")
        self.posted_btn.setObjectName("primary")

        form = QFormLayout()
        form.addRow("Tiêu đề:", self.title)
        form.addRow("Mô tả:", self.description)
        form.addRow("Hashtag:", self.hashtags)
        form.addRow("", self.source)

        copy_row = QHBoxLayout()
        for b in (copy_title, copy_desc, self.rewrite_btn, save_btn):
            copy_row.addWidget(b)
        copy_row.addStretch()
        action_row = QHBoxLayout()
        action_row.addStretch()
        action_row.addWidget(open_btn)
        action_row.addWidget(self.posted_btn)

        note = QLabel("Tự động đăng sẽ được bật khi tài khoản CapCut của bạn đăng được mẫu. "
                      "Hiện tại: mở CapCut, chọn project, rồi dán tiêu đề và hashtag đã sao chép.")
        note.setWordWrap(True)
        note.setObjectName("muted")

        right = QVBoxLayout()
        right.addWidget(self.info)
        right.addLayout(form)
        right.addLayout(copy_row)
        right.addStretch()
        right.addWidget(note)
        right.addLayout(action_row)

        splitter = QSplitter()
        for layout in (left, right):
            w = QWidget()
            w.setLayout(layout)
            splitter.addWidget(w)
        splitter.setSizes([480, 620])
        QVBoxLayout(self).addWidget(splitter)

        self.show_posted.toggled.connect(self.reload)
        self.table.currentCellChanged.connect(lambda r, *_: self._show(r))
        copy_title.clicked.connect(lambda: self._copy(self.title.text()))
        copy_desc.clicked.connect(lambda: self._copy(f"{self.description.toPlainText().strip()}\n{self.hashtags.text().strip()}"))
        save_btn.clicked.connect(self._save)
        self.rewrite_btn.clicked.connect(self._rewrite)
        open_btn.clicked.connect(lambda: open_capcut(self))
        self.posted_btn.clicked.connect(self._toggle_posted)
        self.reload()

    def reload(self) -> None:
        records = []
        if OUTPUTS_DIR.exists():
            for p in OUTPUTS_DIR.glob("*.json"):
                try:
                    records.append((p, json.loads(p.read_text(encoding="utf-8"))))
                except (OSError, ValueError):
                    continue
        if not self.show_posted.isChecked():
            records = [r for r in records if r[1].get("status") != POSTED]
        self.records = sorted(records, key=lambda r: r[1].get("created", ""), reverse=True)
        self.table.setRowCount(len(self.records))
        for i, (_, rec) in enumerate(self.records):
            self.table.setItem(i, 0, QTableWidgetItem(rec["draft_name"]))
            created = rec.get("created", "")
            self.table.setItem(i, 1, QTableWidgetItem(f"{created[8:10]}/{created[5:7]} {created[11:16]}" if created else ""))
            status = QTableWidgetItem(rec.get("status", PENDING))
            status.setForeground(Qt.darkGreen if rec.get("status") == POSTED else Qt.darkYellow)
            self.table.setItem(i, 2, status)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        if self.records:
            self.table.selectRow(0)
            self._show(0)
        else:
            self.current = None
            self.info.setText("Chưa có mẫu nào. Hãy tạo mẫu ở tab Tạo mẫu.")
            for w in (self.title, self.hashtags):
                w.clear()
            self.description.clear()

    def _show(self, row: int) -> None:
        if row < 0 or row >= len(self.records):
            return
        self.current = self.records[row]
        rec = self.current[1]
        materials = ", ".join(Path(m).name for m in rec.get("materials", []))
        self.info.setText(
            f"<b>{rec['draft_name']}</b><br>Công thức {rec['formula']} · nhạc {Path(rec['music']).name} · "
            f"dài {rec['duration_s']:.1f}s<br>Ô thay: {materials or 'giữ nguyên'}")
        c = rec["caption"]
        self.title.setText(c["title"])
        self.description.setPlainText(c["description"])
        self.hashtags.setText(" ".join(c["hashtags"]))
        self.source.setText(f"Nguồn: {c['source']}" + (f" ({c['note']})" if c.get("note") else ""))
        self.posted_btn.setText("Đánh dấu chờ đăng" if rec.get("status") == POSTED else "Đánh dấu đã đăng")

    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def _write_record(self) -> None:
        path, rec = self.current
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")

    def _save(self) -> None:
        if self.current is None:
            return
        c = self.current[1]["caption"]
        c["title"] = self.title.text().strip()
        c["description"] = self.description.toPlainText().strip()
        c["hashtags"] = [t if t.startswith("#") else f"#{t}" for t in self.hashtags.text().split()]
        c["source"], c["note"] = "bạn sửa tay", ""
        self._write_record()
        self._show(self.table.currentRow())

    def _toggle_posted(self) -> None:
        if self.current is None:
            return
        rec = self.current[1]
        rec["status"] = PENDING if rec.get("status") == POSTED else POSTED
        self._write_record()
        self.reload()

    def _rewrite(self) -> None:
        if self.current is None:
            return
        rec = self.current[1]
        if "template_info" not in rec:
            error(self, "Mẫu này được tạo trước khi app có tính năng viết lại, hãy sửa tay.")
            return
        info = TemplateInfo(**rec["template_info"])
        self.rewrite_btn.setEnabled(False)
        self.rewrite_btn.setText("Đang viết…")
        target = self.current

        def done(caption):
            self.rewrite_btn.setEnabled(True)
            self.rewrite_btn.setText("Nhờ AI viết lại")
            target[1]["caption"] = caption.to_dict()
            self.current = target
            self._write_record()
            self._show(self.table.currentRow())

        def failed(message):
            self.rewrite_btn.setEnabled(True)
            self.rewrite_btn.setText("Nhờ AI viết lại")
            error(self, message)

        run_in_background(lambda: write_caption(info), done, failed)
