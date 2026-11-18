"""Tab Tạo mẫu: chọn công thức (khung mẫu bạn đã edit), nhạc và ảnh rồi tạo project mới trong CapCut."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QVBoxLayout, QWidget,
)

from ..formula.learn import list_formulas
from ..generate.build import build_content, generate, make_caption
from ..generate.writer import capcut_running
from ..media import IMAGE_EXT, VIDEO_EXT
from .common import Settings, error, run_in_background

AUDIO_FILTER = "Nhạc (*.mp3 *.m4a *.wav *.aac *.flac *.ogg)"
MEDIA_FILTER = "Ảnh/clip (" + " ".join(f"*{e}" for e in sorted(IMAGE_EXT | VIDEO_EXT)) + ")"


def _file_list(height: int) -> QListWidget:
    w = QListWidget()
    w.setMaximumHeight(height)
    return w


def _add_files(widget: QListWidget, files: list[str]) -> None:
    """Hiện tên file cho gọn; đường dẫn đầy đủ nằm trong dữ liệu và tooltip."""
    for f in files:
        item = QListWidgetItem(f"{widget.count() + 1}. {Path(f).name}")
        item.setData(Qt.UserRole, f)
        item.setToolTip(f)
        widget.addItem(item)


def _paths(widget: QListWidget) -> list[str]:
    return [widget.item(i).data(Qt.UserRole) for i in range(widget.count())]


def _renumber(widget: QListWidget) -> None:
    for i in range(widget.count()):
        item = widget.item(i)
        item.setText(f"{i + 1}. {Path(item.data(Qt.UserRole)).name}")


class GenerateTab(QWidget):
    drafts_created = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.formulas: list[dict] = []

        self.formula_box = QComboBox()
        self.formula_info = QLabel()
        self.formula_info.setObjectName("muted")

        # nhạc
        self.keep_music = QRadioButton("Giữ nhạc của khung mẫu (nhịp giữ nguyên như bạn đã edit)", checked=True)
        self.other_music = QRadioButton("Dùng nhạc khác, mỗi bài một mẫu (tool tự căn theo beat)")
        self.music_list = _file_list(110)
        self.add_music = QPushButton("Thêm nhạc…")
        self.remove_music = QPushButton("Bỏ bài đã chọn")
        music_box = QGroupBox("Nhạc")
        mv = QVBoxLayout(music_box)
        mv.addWidget(self.keep_music)
        mv.addWidget(self.other_music)
        row = QHBoxLayout()
        row.addWidget(self.music_list, 1)
        col = QVBoxLayout()
        col.addWidget(self.add_music)
        col.addWidget(self.remove_music)
        col.addStretch()
        row.addLayout(col)
        mv.addLayout(row)
        music_group = QButtonGroup(self)
        music_group.addButton(self.keep_music)
        music_group.addButton(self.other_music)

        # ảnh
        self.ordered = QRadioButton("Chọn ảnh/clip theo thứ tự ô thay", checked=True)
        self.random = QRadioButton("Lấy ngẫu nhiên trong một thư mục")
        self.photo_list = _file_list(150)
        self.add_photos = QPushButton("Thêm ảnh/clip…")
        self.up_btn = QPushButton("Lên")
        self.down_btn = QPushButton("Xuống")
        self.remove_photo = QPushButton("Bỏ")
        self.slot_hint = QLabel()
        self.materials = QLineEdit(settings.get("materials_dir"))
        self.pick_materials = QPushButton("Chọn thư mục…")
        photo_box = QGroupBox("Ảnh / clip")
        pv = QVBoxLayout(photo_box)
        pv.addWidget(self.ordered)
        pv.addWidget(self.slot_hint)
        row = QHBoxLayout()
        row.addWidget(self.photo_list, 1)
        col = QVBoxLayout()
        for b in (self.add_photos, self.up_btn, self.down_btn, self.remove_photo):
            col.addWidget(b)
        col.addStretch()
        row.addLayout(col)
        pv.addLayout(row)
        pv.addWidget(self.random)
        row = QHBoxLayout()
        row.addWidget(self.materials, 1)
        row.addWidget(self.pick_materials)
        pv.addLayout(row)
        photo_group = QButtonGroup(self)
        photo_group.addButton(self.ordered)
        photo_group.addButton(self.random)

        self.style_hint = QLineEdit(settings.get("style_hint"), placeholderText="Gợi ý phong cách cho AI viết tiêu đề, ví dụ: ảnh couple, tone neon")
        self.dry_btn = QPushButton("Chạy thử (không ghi vào CapCut)")
        self.create_btn = QPushButton("Tạo mẫu trong CapCut")
        self.create_btn.setObjectName("primary")
        self.log = QPlainTextEdit(readOnly=True)

        top = QHBoxLayout()
        top.addWidget(QLabel("Khung mẫu:"))
        top.addWidget(self.formula_box, 1)
        boxes = QHBoxLayout()
        boxes.addWidget(photo_box, 3)
        boxes.addWidget(music_box, 2)
        buttons = QHBoxLayout()
        buttons.addWidget(self.style_hint, 1)
        buttons.addWidget(self.dry_btn)
        buttons.addWidget(self.create_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.formula_info)
        layout.addLayout(boxes)
        layout.addLayout(buttons)
        layout.addWidget(QLabel("Nhật ký:"))
        layout.addWidget(self.log, 1)

        self.formula_box.currentIndexChanged.connect(self._formula_changed)
        self.add_music.clicked.connect(self._add_music)
        self.remove_music.clicked.connect(lambda: self._remove_selected(self.music_list))
        self.add_photos.clicked.connect(self._add_photos)
        self.remove_photo.clicked.connect(lambda: self._remove_selected(self.photo_list))
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn.clicked.connect(lambda: self._move(1))
        self.pick_materials.clicked.connect(self._pick_materials)
        for b in (self.keep_music, self.other_music, self.ordered, self.random):
            b.toggled.connect(self._update_enabled)
        self.dry_btn.clicked.connect(lambda: self._run(dry=True))
        self.create_btn.clicked.connect(lambda: self._run(dry=False))
        self.reload_formulas()
        self._update_enabled()

    # ---------- trạng thái ----------
    def reload_formulas(self) -> None:
        current = self.formula_box.currentText()
        self.formulas = list_formulas()
        self.formula_box.blockSignals(True)
        self.formula_box.clear()
        for f in self.formulas:
            self.formula_box.addItem(f["name"])
        if current:
            self.formula_box.setCurrentText(current)
        self.formula_box.blockSignals(False)
        self._formula_changed()

    def _formula(self) -> dict | None:
        i = self.formula_box.currentIndex()
        return self.formulas[i] if 0 <= i < len(self.formulas) else None

    def _formula_changed(self) -> None:
        f = self._formula()
        if f is None:
            self.formula_info.setText("Chưa có khung mẫu nào. Hãy edit một project trong CapCut rồi học nó ở tab Học mẫu.")
            self.slot_hint.setText("")
            return
        music = Path(f["music"]["path"])
        self.formula_info.setText(f"Học từ project {f['source']['draft_name']} · nhạc gốc {music.name} · "
                                  f"{f['music']['tempo']:.0f} BPM · {len(f['slots'])} ô thay")
        self._update_slot_hint()

    def _update_slot_hint(self) -> None:
        f = self._formula()
        if f is None:
            return
        need, have = len(f["slots"]), self.photo_list.count()
        mark = "✓" if need == have else "⚠"
        self.slot_hint.setText(f"{mark} Khung mẫu có {need} ô thay, bạn đã chọn {have}. Ảnh thứ 1 vào ô xuất hiện đầu tiên.")

    def _update_enabled(self) -> None:
        for w in (self.music_list, self.add_music, self.remove_music):
            w.setEnabled(self.other_music.isChecked())
        for w in (self.photo_list, self.add_photos, self.up_btn, self.down_btn, self.remove_photo):
            w.setEnabled(self.ordered.isChecked())
        for w in (self.materials, self.pick_materials):
            w.setEnabled(self.random.isChecked())

    # ---------- danh sách file ----------
    def _add_music(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn nhạc đã cắt sẵn", self.settings.get("music_dir"), AUDIO_FILTER)
        if files:
            self.settings.set("music_dir", str(Path(files[0]).parent))
            _add_files(self.music_list, files)

    def _add_photos(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn ảnh/clip theo thứ tự ô", self.settings.get("photo_dir"), MEDIA_FILTER)
        if files:
            self.settings.set("photo_dir", str(Path(files[0]).parent))
            _add_files(self.photo_list, files)
            self._update_slot_hint()

    def _remove_selected(self, widget: QListWidget) -> None:
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))
        _renumber(widget)
        self._update_slot_hint()

    def _move(self, step: int) -> None:
        row = self.photo_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.photo_list.count():
            return
        item = self.photo_list.takeItem(row)
        self.photo_list.insertItem(target, item)
        _renumber(self.photo_list)
        self.photo_list.setCurrentRow(target)

    def _pick_materials(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục ảnh/clip", self.materials.text())
        if folder:
            self.materials.setText(folder)

    def _write(self, text: str) -> None:
        self.log.appendPlainText(text)

    # ---------- chạy ----------
    def _run(self, dry: bool) -> None:
        formula = self._formula()
        if formula is None:
            error(self, "Chưa có khung mẫu nào. Hãy học khung mẫu ở tab Học mẫu trước.")
            return
        if self.other_music.isChecked():
            musics = _paths(self.music_list)
            if not musics:
                error(self, "Bạn chưa thêm bài nhạc nào.")
                return
        else:
            musics = [None]
        if self.ordered.isChecked():
            materials = _paths(self.photo_list)
            if len(materials) != len(formula["slots"]):
                error(self, f"Khung mẫu có {len(formula['slots'])} ô thay nên cần đúng {len(formula['slots'])} ảnh/clip, "
                            f"bạn đang chọn {len(materials)}.")
                return
        else:
            materials = self.materials.text().strip()
            if not materials or not Path(materials).is_dir():
                error(self, "Hãy chọn thư mục ảnh/clip.")
                return
            self.settings.set("materials_dir", materials)
        if not dry:
            while capcut_running():
                answer = QMessageBox.question(
                    self, "CapCut đang mở",
                    "Hãy tắt CapCut trước khi tạo mẫu, để CapCut không ghi đè danh sách project.\n\n"
                    "Tắt xong bấm Thử lại.",
                    QMessageBox.Retry | QMessageBox.Cancel)
                if answer != QMessageBox.Retry:
                    return
        self.settings.set("style_hint", self.style_hint.text())

        hint = self.style_hint.text().strip()
        stamp = datetime.now().strftime("%d%m %H%M")
        self._set_busy(True)
        self._write(f"\n=== {'Chạy thử' if dry else 'Tạo mẫu'} · khung {formula['name']} · {len(musics)} mẫu")

        def work():
            lines = []
            for music in musics:
                label = Path(music).name if music else "nhạc của khung mẫu"
                name = f"{formula['name']} - {Path(music).stem if music else 'ảnh mới'} {stamp}"
                try:
                    if dry:
                        result = build_content(formula, music, materials)
                        caption, where = make_caption(formula, result, hint), "chưa ghi"
                    else:
                        folder, result, caption = generate(formula, music, materials, name, style_hint=hint)
                        where = f"đã tạo project {folder.name}"
                except Exception as e:
                    lines.append(f"✗ {label}: {e}")
                    continue
                source = caption.source + (f" ({caption.note})" if caption.note else "")
                cut = (f"\n   nhạc ngắn hơn công thức nên đã cắt bớt {result.truncated_s:.1f}s cuối mẫu"
                       if result.truncated_s > 0.05 else "")
                lines.append(
                    f"✓ {label}: {result.tempo:.0f} BPM, dài {result.duration_s:.1f}s, {where}{cut}\n"
                    f"   ô thay: {', '.join(p.name for p in result.materials)}\n"
                    f"   tiêu đề [{source}]: {caption.title}\n"
                    f"   hashtag: {' '.join(caption.hashtags)}")
            return lines

        run_in_background(work, lambda lines: self._done(lines, dry), self._failed)

    def _done(self, lines: list[str], dry: bool) -> None:
        for line in lines:
            self._write(line)
        self._set_busy(False)
        created = sum(line.startswith("✓") for line in lines)
        if dry:
            return
        if created:
            self._write(f"Đã tạo {created}/{len(lines)} mẫu. Mở CapCut để xem; hồ sơ đăng nằm ở tab Đăng.")
            self.drafts_created.emit()
        else:
            self._write("Không tạo được mẫu nào, xem lỗi ở trên.")

    def _failed(self, message: str) -> None:
        self._write(f"✗ Lỗi: {message}")
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.dry_btn.setEnabled(not busy)
        self.create_btn.setEnabled(not busy)
        self.create_btn.setText("Đang xử lý…" if busy else "Tạo mẫu trong CapCut")
