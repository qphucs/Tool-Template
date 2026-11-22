"""Tab Tạo mẫu: chọn công thức (khung mẫu bạn đã edit), nhạc và ảnh rồi tạo project mới trong CapCut."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..ai.client import AIConfig, status
from ..formula.learn import list_formulas
from ..generate.build import build_content, generate, make_caption
from ..generate.compose import BeatPlan, default_plan, music_grid
from ..generate.describe import parse_description
from ..generate.variants import plan_variants, run_batch
from ..generate.writer import capcut_running
from ..media import IMAGE_EXT, VIDEO_EXT
from .ai_dialog import AIConfigDialog
from .beat_editor import BeatEditorDialog
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

        # link động theo beat
        self.beat_plans: dict[str, BeatPlan] = {}
        self.dynamic = QCheckBox("Link động: tự cắt / lặp công thức theo độ dài và beat của nhạc (không cần nhạc đúng độ dài)")
        self.dynamic.setChecked(bool(settings.get("dynamic_beat", True)))
        self.beat_btn = QPushButton("Chia beat & chọn chuyển cảnh…")
        self.edit_desc = QLineEdit(settings.get("edit_description"),
                                   placeholderText="Miêu tả cách edit (áp cho bài chưa chia beat), vd: chuyển cảnh ở beat 8, bỏ pixelate, dài 20 giây")
        self.beat_label = QLabel()
        self.beat_label.setObjectName("muted")
        self.beat_label.setWordWrap(True)
        beat_box = QGroupBox("Nhịp & chuyển cảnh")
        bl = QVBoxLayout(beat_box)
        row = QHBoxLayout()
        row.addWidget(self.dynamic, 1)
        row.addWidget(self.beat_btn)
        bl.addLayout(row)
        bl.addWidget(self.edit_desc)
        bl.addWidget(self.beat_label)

        self.style_hint = QLineEdit(settings.get("style_hint"), placeholderText="Gợi ý phong cách cho AI viết tiêu đề, ví dụ: ảnh couple, tone neon")
        self.dry_btn = QPushButton("Chạy thử (không ghi vào CapCut)")
        self.create_btn = QPushButton("Tạo mẫu trong CapCut")
        self.create_btn.setObjectName("primary")
        self.log = QPlainTextEdit(readOnly=True)

        # prompt tạo nhiều biến thể
        self.prompt = QPlainTextEdit(settings.get("variant_prompt"),
                                     placeholderText="Ví dụ: tạo 8 mẫu cho ảnh couple: 3 tone tối giản, "
                                                     "2 neon, 2 retro, 1 điện ảnh. Ưu tiên nhịp nhanh, chữ to.")
        self.prompt.setMaximumHeight(78)
        self.count = QSpinBox()
        self.count.setRange(1, 30)
        try:
            self.count.setValue(int(settings.get("variant_count", 6) or 6))
        except (TypeError, ValueError):
            self.count.setValue(6)
        self.vary = QCheckBox("Biến tấu công thức (cắt bớt beat đầu, đổi số ô thay)")
        self.vary.setChecked(bool(settings.get("variant_vary", True)))
        self.ai_label = QLabel()
        self.ai_label.setObjectName("muted")
        self.ai_config_btn = QPushButton("Cấu hình AI…")
        self.batch_dry_btn = QPushButton("Chạy thử prompt")
        self.batch_btn = QPushButton("Tạo nhiều mẫu theo prompt")
        self.batch_btn.setObjectName("primary")

        prompt_box = QGroupBox("Prompt tạo nhiều mẫu")
        prompt_row = QHBoxLayout()
        prompt_row.addWidget(self.prompt, 1)
        side = QVBoxLayout()
        side.addWidget(QLabel("Số mẫu:"))
        side.addWidget(self.count)
        side.addWidget(self.vary)
        side.addStretch()
        prompt_row.addLayout(side)
        prompt_bottom = QHBoxLayout()
        prompt_bottom.addWidget(self.ai_label, 1)
        prompt_bottom.addWidget(self.ai_config_btn)
        prompt_bottom.addWidget(self.batch_dry_btn)
        prompt_bottom.addWidget(self.batch_btn)
        prompt_layout = QVBoxLayout(prompt_box)
        prompt_layout.addLayout(prompt_row)
        prompt_layout.addLayout(prompt_bottom)

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
        layout.addWidget(beat_box)
        layout.addWidget(prompt_box)
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
        self.batch_dry_btn.clicked.connect(lambda: self._run_batch(dry=True))
        self.batch_btn.clicked.connect(lambda: self._run_batch(dry=False))
        self.ai_config_btn.clicked.connect(self._configure_ai)
        self.beat_btn.clicked.connect(self._open_beat_editor)
        self.dynamic.toggled.connect(self._dynamic_toggled)
        self.edit_desc.textChanged.connect(lambda _t: self._update_beat_label())
        self.music_list.currentRowChanged.connect(lambda _r: self._update_beat_label())
        self.reload_formulas()
        self._update_enabled()
        self._update_ai_label()
        self._dynamic_toggled(self.dynamic.isChecked())

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
        self._update_beat_label()

    # ---------- nhịp & chuyển cảnh ----------
    def _beat_key(self, formula: dict, music: str | None) -> str:
        return f"{formula['name']}|{music or '__nhac_khung__'}"

    def _current_music(self) -> tuple[bool, str | None]:
        """(có nhạc để chia không, đường dẫn nhạc hoặc None = nhạc của khung mẫu)."""
        if self.keep_music.isChecked():
            return True, None
        item = self.music_list.currentItem() or (self.music_list.item(0) if self.music_list.count() else None)
        return (item is not None), (item.data(Qt.UserRole) if item else None)

    def _dynamic_toggled(self, on: bool) -> None:
        self.settings.set("dynamic_beat", on)
        for w in (self.beat_btn, self.edit_desc):
            w.setEnabled(on)
        self._update_beat_label()

    def _update_beat_label(self) -> None:
        if not hasattr(self, "beat_label"):
            return
        f = self._formula()
        if f is None or not self.dynamic.isChecked():
            self.beat_label.setText("" if f is None else
                                    "Đang dùng cách cũ: co giãn đúng công thức, nhạc dài hơn công thức sẽ bị cắt.")
            return
        ok, music = self._current_music()
        if not ok:
            self.beat_label.setText("Thêm nhạc rồi bấm Chia beat để chọn beat chuyển cảnh cho từng bài.")
            return
        name = Path(music).name if music else "nhạc của khung mẫu"
        plan = self.beat_plans.get(self._beat_key(f, music))
        if plan is None:
            self.beat_label.setText(f"{name}: chưa chia beat — tool tự đặt chuyển cảnh sau đúng số beat như công thức"
                                    + (" và áp miêu tả." if self.edit_desc.text().strip() else "."))
            return
        end = "hết nhạc" if plan.end_index is None else f"beat {plan.end_index - plan.start_index + 1:g}"
        removed = f", bỏ {', '.join(plan.remove_effects)}" if plan.remove_effects else ""
        self.beat_label.setText(f"{name}: bắt đầu beat {plan.start_index + 1}, chuyển cảnh ở beat "
                                f"{plan.transition_index - plan.start_index + 1}, kết thúc {end}, "
                                f"chia beat {plan.density:g}×{removed}.")

    def _open_beat_editor(self) -> None:
        f = self._formula()
        if f is None:
            error(self, "Chưa có khung mẫu nào.")
            return
        ok, music = self._current_music()
        if not ok:
            error(self, "Hãy thêm nhạc (và chọn bài cần chia) trước.")
            return
        if music is None and not Path(f["music"]["path"]).is_file():
            error(self, f"Không còn file nhạc gốc của khung mẫu: {f['music']['path']}")
            return
        key = self._beat_key(f, music)
        self.settings.set("edit_description", self.edit_desc.text())
        dlg = BeatEditorDialog(f, music, self.beat_plans.get(key), self.settings, self,
                               description=self.edit_desc.text())
        if dlg.exec():
            self.beat_plans[key] = dlg.result_plan()
            self._formula_changed()

    def _plan_for(self, formula: dict, description: str, config: AIConfig, log: list[str]):
        """Hàm chọn kế hoạch beat cho từng bài (gọi ở luồng nền)."""
        chosen = dict(self.beat_plans)
        cache: dict[str, BeatPlan | None] = {}

        def plan_for(music):
            key = self._beat_key(formula, music)
            if key in chosen:
                return chosen[key]
            if not description:
                return None
            if key not in cache:
                path = music or formula["music"]["path"]
                grid = music_grid(path)
                base = default_plan(formula, grid, music is None)
                plan, notes, source = parse_description(description, formula, grid, base, config=config)
                log.append(f"   miêu tả [{source}] cho {Path(path).name}: " + ("; ".join(notes) or "không áp được ý nào"))
                cache[key] = plan
            return cache[key]
        return plan_for

    def _update_slot_hint(self) -> None:
        f = self._formula()
        if f is None:
            return
        need, have = len(f["slots"]), self.photo_list.count()
        mark = "✓" if need == have else "⚠"
        self.slot_hint.setText(f"{mark} Khung mẫu có {need} ô thay, bạn đã chọn {have}. Ảnh thứ 1 vào ô xuất hiện đầu tiên.")

    def _update_enabled(self) -> None:
        self._update_beat_label()
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
    def _collect_inputs(self):
        """Kiểm tra lựa chọn chung cho cả tạo đơn và tạo hàng loạt."""
        formula = self._formula()
        if formula is None:
            error(self, "Chưa có khung mẫu nào. Hãy học khung mẫu ở tab Học mẫu trước.")
            return None
        if self.other_music.isChecked():
            musics = _paths(self.music_list)
            if not musics:
                error(self, "Bạn chưa thêm bài nhạc nào.")
                return None
        else:
            musics = [None]
        ordered = self.ordered.isChecked()
        if ordered:
            materials = _paths(self.photo_list)
            if len(materials) != len(formula["slots"]):
                error(self, f"Khung mẫu có {len(formula['slots'])} ô thay nên cần đúng {len(formula['slots'])} ảnh/clip, "
                            f"bạn đang chọn {len(materials)}.")
                return None
        else:
            materials = self.materials.text().strip()
            if not materials or not Path(materials).is_dir():
                error(self, "Hãy chọn thư mục ảnh/clip.")
                return None
            self.settings.set("materials_dir", materials)
        return formula, musics, materials, ordered

    def _ask_close_capcut(self) -> bool:
        while capcut_running():
            answer = QMessageBox.question(
                self, "CapCut đang mở",
                "Hãy tắt CapCut trước khi tạo mẫu, để CapCut không ghi đè danh sách project.\n\n"
                "Tắt xong bấm Thử lại.",
                QMessageBox.Retry | QMessageBox.Cancel)
            if answer != QMessageBox.Retry:
                return False
        return True

    def _run(self, dry: bool) -> None:
        inputs = self._collect_inputs()
        if inputs is None:
            return
        formula, musics, materials, _ = inputs
        if not dry and not self._ask_close_capcut():
            return
        self.settings.set("style_hint", self.style_hint.text())

        hint = self.style_hint.text().strip()
        stamp = datetime.now().strftime("%d%m %H%M")
        dynamic = self.dynamic.isChecked()
        description = self.edit_desc.text().strip() if dynamic else ""
        self.settings.set("edit_description", self.edit_desc.text())
        config = AIConfig.load(self.settings)
        self._set_busy(True)
        self._write(f"\n=== {'Chạy thử' if dry else 'Tạo mẫu'} · khung {formula['name']} · {len(musics)} mẫu"
                    + (" · link động" if dynamic else ""))
        lines: list[str] = []  # nhật ký phân tích miêu tả được ghi vào đây trước
        plan_for = self._plan_for(formula, description, config, lines) if dynamic else (lambda _m: None)

        def work():
            for music in musics:
                label = Path(music).name if music else "nhạc của khung mẫu"
                name = f"{formula['name']} - {Path(music).stem if music else 'ảnh mới'} {stamp}"
                try:
                    beat_plan = plan_for(music)
                    if dry:
                        result = build_content(formula, music, materials, beat_plan=beat_plan, dynamic=dynamic)
                        caption, where = make_caption(formula, result, hint), "chưa ghi"
                    else:
                        folder, result, caption = generate(formula, music, materials, name, style_hint=hint,
                                                           beat_plan=beat_plan, dynamic=dynamic)
                        where = f"đã tạo project {folder.name}"
                except Exception as e:
                    lines.append(f"✗ {label}: {e}")
                    continue
                source = caption.source + (f" ({caption.note})" if caption.note else "")
                cut = (f"\n   nhạc ngắn hơn công thức nên đã cắt bớt {result.truncated_s:.1f}s cuối mẫu"
                       if result.truncated_s > 0.05 else "")
                if result.summary:
                    cut += f"\n   ghép: {result.summary}"
                lines.append(
                    f"✓ {label}: {result.tempo:.0f} BPM, dài {result.duration_s:.1f}s, {where}{cut}\n"
                    f"   ô thay: {', '.join(p.name for p in result.materials)}\n"
                    f"   tiêu đề [{source}]: {caption.title}\n"
                    f"   hashtag: {' '.join(caption.hashtags)}")
            return lines

        run_in_background(work, lambda lines: self._done(lines, dry), self._failed)

    def _run_batch(self, dry: bool) -> None:
        inputs = self._collect_inputs()
        if inputs is None:
            return
        formula, musics, materials, ordered = inputs
        if not dry and not self._ask_close_capcut():
            return

        prompt = self.prompt.toPlainText().strip()
        hint = self.style_hint.text().strip()
        count = self.count.value()
        vary = self.vary.isChecked()
        self.settings.set("style_hint", hint)
        self.settings.set("variant_prompt", prompt)
        self.settings.set("variant_count", count)
        self.settings.set("variant_vary", vary)
        config = AIConfig.load(self.settings)

        full_prompt = prompt
        if hint:
            full_prompt = f"{prompt}\nPhong cách chung: {hint}".strip()

        stamp = datetime.now().strftime("%d%m %H%M")
        dynamic = self.dynamic.isChecked()
        description = self.edit_desc.text().strip() if dynamic else ""
        self.settings.set("edit_description", self.edit_desc.text())
        self._set_busy(True)
        self._write(f"\n=== {'Chạy thử prompt' if dry else 'Tạo nhiều mẫu'} · khung {formula['name']} · {count} mẫu"
                    + (" · link động" if dynamic else ""))
        desc_log: list[str] = []
        plan_for = self._plan_for(formula, description, config, desc_log) if dynamic else None

        def work():
            plans, note = plan_variants(formula, full_prompt, count, len(musics), config=config)
            lines = [f"Kế hoạch: {note}"]
            lines.extend(f"   {p.index + 1}. {p.style} · {p.source}" for p in plans)
            batch = run_batch(formula, plans, musics, materials,
                              dry=dry, stamp=stamp, ordered=ordered, vary=vary,
                              dynamic=dynamic, plan_for=plan_for)
            return lines + desc_log + batch.lines, batch.created, batch.total

        run_in_background(work, lambda result: self._batch_done(result, dry), self._failed)

    def _done(self, lines: list[str], dry: bool) -> None:
        for line in lines:
            self._write(line)
        self._set_busy(False)
        created = sum(line.startswith("✓") for line in lines)
        if dry:
            return
        if created:
            total = sum(line.startswith(("✓", "✗")) for line in lines)
            self._write(f"Đã tạo {created}/{total} mẫu. Mở CapCut để xem; hồ sơ đăng nằm ở tab Đăng.")
            self.drafts_created.emit()
        else:
            self._write("Không tạo được mẫu nào, xem lỗi ở trên.")

    def _batch_done(self, result, dry: bool) -> None:
        lines, created, total = result
        for line in lines:
            self._write(line)
        self._set_busy(False)
        if dry:
            return
        if created:
            self._write(f"Đã tạo {created}/{total} mẫu. Mở CapCut để xem; hồ sơ đăng nằm ở tab Đăng.")
            self.drafts_created.emit()
        else:
            self._write("Không tạo được mẫu nào, xem lỗi ở trên.")

    def _failed(self, message: str) -> None:
        self._write(f"✗ Lỗi: {message}")
        self._set_busy(False)

    def _configure_ai(self) -> None:
        dialog = AIConfigDialog(self.settings, self)
        if dialog.exec():
            self._update_ai_label()

    def _update_ai_label(self) -> None:
        self.ai_label.setText(status(self.settings))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_ai_label()

    def _set_busy(self, busy: bool) -> None:
        self.dry_btn.setEnabled(not busy)
        self.create_btn.setEnabled(not busy)
        self.batch_dry_btn.setEnabled(not busy)
        self.batch_btn.setEnabled(not busy)
        self.create_btn.setText("Đang xử lý…" if busy else "Tạo mẫu trong CapCut")
        self.batch_btn.setText("Đang tạo…" if busy else "Tạo nhiều mẫu theo prompt")
