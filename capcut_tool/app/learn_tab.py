"""Tab Học mẫu: chọn project CapCut để học công thức, chỉnh ô thay của từng công thức."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..capcut.drafts import DraftInfo, list_drafts
from ..formula.learn import learn, list_formulas, media_segments, save, set_slots
from .common import error, run_in_background

SHORT_DRAFT_S = 30  # mẫu của bạn dưới 15 giây; để rộng ra một chút


class LearnTab(QWidget):
    formulas_changed = Signal()

    def __init__(self):
        super().__init__()
        self.drafts: list[DraftInfo] = []
        self.formulas: list[dict] = []
        self.current: dict | None = None

        # bên trái: project CapCut
        self.search = QLineEdit(placeholderText="Tìm project theo tên…")
        self.only_short = QCheckBox(f"Chỉ project dưới {SHORT_DRAFT_S} giây", checked=True)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Project", "Độ dài", "Sửa lần cuối", "Công thức"])
        self.table.setIconSize(QPixmap(48, 64).size())
        self.table.verticalHeader().setDefaultSectionSize(70)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.learn_btn = QPushButton("Học công thức từ các project đã tick")
        self.learn_btn.setObjectName("primary")
        refresh = QPushButton("Tải lại danh sách")

        left = QVBoxLayout()
        left.addWidget(QLabel("<b>1. Tick project mẫu để học</b>"))
        row = QHBoxLayout()
        row.addWidget(self.search, 1)
        row.addWidget(self.only_short)
        left.addLayout(row)
        left.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addStretch()
        row.addWidget(self.learn_btn)
        left.addLayout(row)

        # bên phải: công thức đã học và ô thay
        self.formula_list = QListWidget()
        self.slot_table = QTableWidget(0, 4)
        self.slot_table.setHorizontalHeaderLabels(["Ô thay", "Track", "Vị trí (beat)", "Ảnh/clip gốc"])
        self.slot_table.verticalHeader().hide()
        self.slot_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.formula_info = QLabel(wordWrap=True)
        self.save_slots_btn = QPushButton("Lưu ô thay")

        right = QVBoxLayout()
        right.addWidget(QLabel("<b>2. Công thức đã học</b>"))
        right.addWidget(self.formula_list, 1)
        right.addWidget(self.formula_info)
        right.addWidget(QLabel("Tick các đoạn mà người dùng mẫu được thay ảnh/video:"))
        right.addWidget(self.slot_table, 2)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.save_slots_btn)
        right.addLayout(row)

        splitter = QSplitter()
        for layout in (left, right):
            w = QWidget()
            w.setLayout(layout)
            splitter.addWidget(w)
        splitter.setSizes([620, 480])
        outer = QVBoxLayout(self)
        outer.addWidget(splitter)

        self.search.textChanged.connect(self._fill_drafts)
        self.only_short.toggled.connect(self._fill_drafts)
        refresh.clicked.connect(self.reload)
        self.learn_btn.clicked.connect(self._learn_checked)
        self.formula_list.currentRowChanged.connect(self._show_formula)
        self.save_slots_btn.clicked.connect(self._save_slots)
        self.reload()

    # ---------- project ----------
    def reload(self) -> None:
        try:
            self.drafts = list_drafts()
        except OSError as e:
            error(self, f"Không đọc được danh sách project CapCut: {e}")
            self.drafts = []
        self._reload_formulas()
        self._fill_drafts()

    def _fill_drafts(self) -> None:
        learned = {f["source"]["draft_id"]: f for f in self.formulas}
        text = self.search.text().strip().lower()
        shown = [d for d in self.drafts
                 if (not text or text in d.name.lower())
                 and (not self.only_short.isChecked() or d.duration_s < SHORT_DRAFT_S)]
        self.table.setRowCount(len(shown))
        for r, d in enumerate(shown):
            name = QTableWidgetItem(d.name)
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.Unchecked)
            name.setData(Qt.UserRole, d)
            if d.cover:
                name.setIcon(QIcon(QPixmap(str(d.cover)).scaled(48, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(f"{d.duration_s:.1f}s"))
            self.table.setItem(r, 2, QTableWidgetItem(f"{d.modified:%d/%m/%Y %H:%M}"))
            f = learned.get(d.id)
            status = f"Đã học · {f['alignment']['on_beat_ratio']:.0%} khớp beat" if f else ""
            self.table.setItem(r, 3, QTableWidgetItem(status))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def _learn_checked(self) -> None:
        drafts = [self.table.item(r, 0).data(Qt.UserRole) for r in range(self.table.rowCount())
                  if self.table.item(r, 0).checkState() == Qt.Checked]
        if not drafts:
            error(self, "Bạn chưa tick project nào.")
            return
        self.learn_btn.setEnabled(False)
        self.learn_btn.setText(f"Đang học {len(drafts)} project…")

        def work():
            results, failures = [], []
            for d in drafts:
                try:
                    results.append(save(learn(d)).stem)
                except Exception as e:
                    failures.append(f"{d.name}: {e}")
            return results, failures

        run_in_background(work, self._learn_done, self._learn_failed)

    def _learn_done(self, result) -> None:
        learned, failures = result
        self._reset_learn_btn()
        self.reload()
        self.formulas_changed.emit()
        if failures:
            error(self, "Một số project không học được:\n" + "\n".join(failures))

    def _learn_failed(self, message: str) -> None:
        self._reset_learn_btn()
        error(self, message)

    def _reset_learn_btn(self) -> None:
        self.learn_btn.setEnabled(True)
        self.learn_btn.setText("Học công thức từ các project đã tick")

    # ---------- công thức ----------
    def _reload_formulas(self) -> None:
        self.formulas = list_formulas()
        self.formula_list.blockSignals(True)
        self.formula_list.clear()
        for f in self.formulas:
            item = QListWidgetItem(f"{f['name']}   ·   {f['music']['tempo']:.0f} BPM   ·   {len(f['slots'])} ô thay")
            self.formula_list.addItem(item)
        self.formula_list.blockSignals(False)
        if self.formulas:
            self.formula_list.setCurrentRow(0)
            self._show_formula(0)
        else:
            self.current = None
            self.slot_table.setRowCount(0)
            self.formula_info.setText("Chưa có công thức nào. Hãy tick project bên trái rồi bấm Học.")

    def _show_formula(self, row: int) -> None:
        if row < 0 or row >= len(self.formulas):
            return
        f = self.current = self.formulas[row]
        a = f["alignment"]
        self.formula_info.setText(
            f"Học từ project <b>{f['source']['draft_name']}</b> lúc {f['created'].replace('T', ' ')}. "
            f"{a['on_beat_ratio']:.0%} mốc khớp beat, lệch tối đa {a['max_error_ms']:.0f} ms.")
        segments = media_segments(f)
        self.slot_table.setRowCount(len(segments))
        for r, s in enumerate(segments):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if s["id"] in f["slots"] else Qt.Unchecked)
            check.setData(Qt.UserRole, s["id"])
            self.slot_table.setItem(r, 0, check)
            self.slot_table.setItem(r, 1, QTableWidgetItem(str(s["track"])))
            self.slot_table.setItem(r, 2, QTableWidgetItem(f"{s['start_beat']:g} → {s['end_beat']:g}"))
            self.slot_table.setItem(r, 3, QTableWidgetItem(s["name"]))
        self.slot_table.resizeColumnsToContents()
        self.slot_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

    def _save_slots(self) -> None:
        if self.current is None:
            return
        ids = [self.slot_table.item(r, 0).data(Qt.UserRole) for r in range(self.slot_table.rowCount())
               if self.slot_table.item(r, 0).checkState() == Qt.Checked]
        if not ids:
            error(self, "Mẫu cần ít nhất một ô thay.")
            return
        set_slots(self.current, ids)
        row = self.formula_list.currentRow()
        self._reload_formulas()
        self.formula_list.setCurrentRow(row)
        self.formulas_changed.emit()
