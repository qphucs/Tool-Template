"""Bảng chia beat: dò beat của nhạc input, chọn beat bắt đầu / chuyển cảnh / kết thúc
giống tính năng beat của CapCut, xem trước cách công thức được cắt và lặp."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
    QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from ..ai.client import AIConfig
from ..audio.beats import SR, BeatGrid, load_audio
from ..formula.learn import save as save_formula
from ..generate.compose import (
    BeatPlan, Structure, apply_density, clamp_structure, default_plan, default_structure,
    music_grid, plan_pieces,
)
from ..generate.describe import effect_names, parse_description
from .common import error, run_in_background

try:  # nghe thử nhạc; thiếu QtMultimedia thì vẫn dùng được bảng beat
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover
    QMediaPlayer = None

PART_COLORS = {
    "đầu": QColor(70, 130, 220, 70),
    "lặp trước chuyển cảnh": QColor(120, 160, 240, 110),
    "bùng": QColor(240, 150, 50, 90),
    "lặp": QColor(70, 190, 110, 70),
    "kết": QColor(170, 100, 220, 90),
}


def summarize_structure(formula: dict, st: Structure) -> str:
    s0, end = float(formula["start_beat"]), float(formula["end_beat"])
    return (f"Công thức: phần đầu {st.transition - s0:g} beat → chuyển cảnh ở beat "
            f"{round(st.transition - round(s0)) + 1:g} → bùng {st.loop_start - st.transition:g} beat → "
            f"lặp {st.loop_end - st.loop_start:g} beat → kết {end - st.loop_end:g} beat "
            f"({formula['music']['tempo']:.0f} BPM)")


class BeatView(QWidget):
    """Dạng sóng + vạch beat + vùng màu các phần. Bấm vào beat để chọn chuyển cảnh."""
    beat_clicked = Signal(int)
    beat_menu = Signal(int, str)  # index, hành động

    def __init__(self):
        super().__init__()
        self.env: np.ndarray = np.zeros(0)
        self.env_rate = 1.0        # số điểm envelope mỗi giây
        self.duration = 1.0
        self.grid: BeatGrid | None = None
        self.offset_s = 0.0
        self.plan: BeatPlan | None = None
        self.pieces = []
        self.playhead: float | None = None
        self.px_per_s = 60.0
        self.setFixedHeight(200)
        self.setMouseTracking(True)

    def set_audio(self, env: np.ndarray, rate: float, duration: float) -> None:
        self.env, self.env_rate, self.duration = env, rate, max(duration, 0.1)
        self._resize()

    def set_zoom(self, px_per_s: float) -> None:
        self.px_per_s = px_per_s
        self._resize()

    def _resize(self) -> None:
        self.setMinimumWidth(int(self.duration * self.px_per_s) + 40)
        self.update()

    def x(self, t: float) -> float:
        return 20 + t * self.px_per_s

    def beat_time(self, i: float) -> float:
        return self.grid.to_time(i) + self.offset_s

    def nearest_beat(self, x: float) -> int | None:
        if self.grid is None:
            return None
        t = (x - 20) / self.px_per_s - self.offset_s
        return int(round(self.grid.to_beat(t)))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor(24, 25, 28))
        top, bottom = 26, h - 22
        mid = (top + bottom) / 2

        # vùng các phần
        if self.grid is not None and self.pieces:
            for piece in self.pieces:
                x1, x2 = self.x(self.beat_time(piece.out_a)), self.x(self.beat_time(piece.out_b))
                p.fillRect(QRectF(x1, top, max(x2 - x1, 1), bottom - top), PART_COLORS.get(piece.part, QColor(90, 90, 90, 60)))
                p.setPen(QPen(QColor(255, 255, 255, 50), 1, Qt.DashLine))
                p.drawLine(QPointF(x1, top), QPointF(x1, bottom))

        # dạng sóng
        if len(self.env):
            p.setPen(QPen(QColor(120, 170, 255, 170), 1))
            peak = float(self.env.max()) or 1.0
            step = max(1, int(self.env_rate / self.px_per_s))
            for i in range(0, len(self.env), step):
                t = i / self.env_rate
                amp = float(self.env[i:i + step].max()) / peak * (bottom - top) / 2 * 0.95
                xx = self.x(t)
                p.drawLine(QPointF(xx, mid - amp), QPointF(xx, mid + amp))

        # vạch beat
        if self.grid is not None:
            font = QFont(self.font())
            font.setPointSize(7)
            p.setFont(font)
            plan = self.plan
            start = plan.start_index if plan else 0
            for i, t0 in enumerate(self.grid.times):
                t = t0 + self.offset_s
                xx = self.x(t)
                strong = (i - start) % 4 == 0
                p.setPen(QPen(QColor(255, 255, 255, 130 if strong else 60), 1))
                p.drawLine(QPointF(xx, bottom), QPointF(xx, bottom - (14 if strong else 7)))
                label = i - start + 1
                if label >= 1 and (self.px_per_s >= 45 or strong):
                    p.setPen(QColor(220, 220, 220) if strong else QColor(150, 150, 150))
                    p.drawText(QPointF(xx + 2, h - 6), str(label))
            # mốc bắt đầu / chuyển cảnh / kết thúc
            if plan:
                marks = [(plan.start_index + 0.0, "Bắt đầu", QColor(90, 200, 255)),
                         (float(plan.transition_index), "Chuyển cảnh", QColor(255, 80, 80))]
                if plan.end_index is not None:
                    marks.append((float(plan.end_index), "Kết thúc", QColor(200, 140, 255)))
                for beat, text, color in marks:
                    xx = self.x(self.beat_time(beat))
                    p.setPen(QPen(color, 2))
                    p.drawLine(QPointF(xx, top - 4), QPointF(xx, bottom))
                    p.drawText(QPointF(xx + 3, top - 8), text)

        if self.playhead is not None:
            xx = self.x(self.playhead)
            p.setPen(QPen(QColor(255, 230, 80), 2))
            p.drawLine(QPointF(xx, 0), QPointF(xx, h))
        p.end()

    def mousePressEvent(self, event) -> None:
        i = self.nearest_beat(event.position().x())
        if i is None or self.grid is None:
            return
        i = max(0, min(i, len(self.grid.times) - 1))
        if event.button() == Qt.LeftButton:
            self.beat_clicked.emit(i)
        elif event.button() == Qt.RightButton:
            menu = QMenu(self)
            actions = {
                menu.addAction(f"Chuyển cảnh ở beat này"): "transition",
                menu.addAction("Video bắt đầu từ beat này"): "start",
                menu.addAction("Kết thúc video ở beat này"): "end",
                menu.addAction("Nghe thử từ beat này"): "play",
            }
            chosen = menu.exec(event.globalPosition().toPoint())
            if chosen in actions:
                self.beat_menu.emit(i, actions[chosen])


class BeatEditorDialog(QDialog):
    """Chọn cách công thức được ghép lên một bài nhạc."""

    def __init__(self, formula: dict, music_path: str | None, plan: BeatPlan | None,
                 settings, parent=None, description: str = ""):
        super().__init__(parent)
        self.formula = formula
        self.same_music = music_path is None
        self.music_path = Path(music_path or formula["music"]["path"])
        self.settings = settings
        self.structure = default_structure(formula)
        self.saved_structure = self.structure
        self.raw_grid: BeatGrid | None = None
        self.plan: BeatPlan | None = plan
        self._updating = False
        self.setWindowTitle(f"Chia beat & chuyển cảnh — {self.music_path.name}")
        self.resize(1100, 760)

        self.info = QLabel(summarize_structure(formula, self.structure), wordWrap=True)
        self.music_info = QLabel("Đang dò beat…")
        self.music_info.setObjectName("muted")
        self.view = BeatView()
        scroll = QScrollArea()
        scroll.setWidget(self.view)
        scroll.setWidgetResizable(False)
        scroll.setFixedHeight(222)
        self.scroll = scroll
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(15, 250)
        self.zoom.setValue(60)

        self.density = QComboBox()
        for text, value in (("½ — gộp đôi beat (thưa)", 0.5), ("1× — beat dò được", 1.0), ("2× — chia đôi beat (dày)", 2.0)):
            self.density.addItem(text, value)
        self.offset = QSpinBox()
        self.offset.setRange(-500, 500)
        self.offset.setSuffix(" ms")
        self.offset.setToolTip("Dời toàn bộ vạch beat sớm (âm) hoặc muộn (dương) cho khớp tai nghe")
        self.start = QSpinBox()
        self.start.setRange(1, 9999)
        self.start.setToolTip("Video bắt đầu ở beat thứ mấy của bài nhạc")
        self.transition = QSpinBox()
        self.transition.setRange(2, 9999)
        self.transition.setToolTip("Đếm từ đầu video: beat 1 là beat mở đầu video")
        self.to_end = QCheckBox("Tới hết nhạc")
        self.end = QDoubleSpinBox()
        self.end.setRange(2, 9999)
        self.end.setDecimals(2)
        self.end.setSingleStep(1)
        self.end.setToolTip("Beat kết thúc, đếm từ đầu video")

        # nâng cao: cấu trúc công thức
        self.st_transition = self._beat_spin()
        self.st_loop_start = self._beat_spin()
        self.st_loop_end = self._beat_spin()
        self.st_unit = self._beat_spin(0.25, 64)
        self.loop_period = QDoubleSpinBox()
        self.loop_period.setRange(0, 256)
        self.loop_period.setSingleStep(1)
        self.loop_period.setSpecialValueText("theo công thức")
        self.effects = QListWidget()
        self.effects.setMaximumHeight(110)
        for name in effect_names(formula):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.effects.addItem(item)

        self.description = QPlainTextEdit(description)
        self.description.setPlaceholderText(
            "Miêu tả cách edit, ví dụ: chuyển cảnh ở beat 8, bỏ 2 giây đầu nhạc, dài 20 giây, bỏ hiệu ứng pixelate, "
            "lặp trước chuyển cảnh 2 beat, beat sớm 30ms")
        self.description.setMaximumHeight(64)
        self.describe_btn = QPushButton("Phân tích miêu tả")
        self.describe_note = QLabel(wordWrap=True)
        self.describe_note.setObjectName("muted")
        self.preview = QLabel(wordWrap=True)
        self.play_btn = QPushButton("▶ Nghe thử")
        self.play_tr_btn = QPushButton("Nghe từ chuyển cảnh")
        self.suggest_btn = QPushButton("Gợi ý beat mạnh")
        self.suggest_btn.setToolTip("Dời chuyển cảnh tới beat mạnh nhất trong khoảng ±2 beat")

        # bố cục
        controls = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(self.density)
        row.addWidget(QLabel("Lệch beat:"))
        row.addWidget(self.offset)
        row.addStretch()
        controls.addRow("Chia beat:", row)
        row = QHBoxLayout()
        row.addWidget(self.start)
        row.addWidget(QLabel("   Chuyển cảnh ở beat:"))
        row.addWidget(self.transition)
        row.addWidget(self.suggest_btn)
        row.addWidget(QLabel("   Kết thúc ở beat:"))
        row.addWidget(self.end)
        row.addWidget(self.to_end)
        row.addStretch()
        controls.addRow("Bắt đầu ở beat:", row)

        adv = QGroupBox("Nâng cao: cấu trúc khung mẫu (beat của nhạc gốc) và hiệu ứng")
        adv.setCheckable(True)
        adv.setChecked(False)
        adv_body = QWidget()
        al = QHBoxLayout(adv_body)
        form = QFormLayout()
        form.addRow("Chuyển cảnh ở beat:", self.st_transition)
        form.addRow("Đoạn lặp từ beat:", self.st_loop_start)
        form.addRow("Đoạn lặp tới beat:", self.st_loop_end)
        form.addRow("Lặp trước chuyển cảnh (beat):", self.st_unit)
        form.addRow("Độ dài 1 vòng lặp (beat):", self.loop_period)
        al.addLayout(form)
        ev = QVBoxLayout()
        ev.addWidget(QLabel("Hiệu ứng giữ lại (bỏ tick để bỏ):"))
        ev.addWidget(self.effects)
        al.addLayout(ev, 1)
        advl = QVBoxLayout(adv)
        advl.addWidget(adv_body)
        adv.toggled.connect(adv_body.setVisible)
        adv_body.setVisible(False)

        desc_row = QHBoxLayout()
        desc_row.addWidget(self.description, 1)
        desc_row.addWidget(self.describe_btn)

        zoom_row = QHBoxLayout()
        zoom_row.addWidget(self.music_info, 1)
        zoom_row.addWidget(self.play_btn)
        zoom_row.addWidget(self.play_tr_btn)
        zoom_row.addWidget(QLabel("Thu phóng:"))
        zoom_row.addWidget(self.zoom)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Dùng cách chia này")
        buttons.button(QDialogButtonBox.Cancel).setText("Huỷ")

        layout = QVBoxLayout(self)
        layout.addWidget(self.info)
        layout.addLayout(zoom_row)
        layout.addWidget(QLabel("Bấm chuột trái vào một beat để đặt chuyển cảnh; chuột phải để chọn bắt đầu / kết thúc / nghe thử."))
        layout.addWidget(scroll)
        layout.addLayout(controls)
        layout.addWidget(QLabel("<b>Miêu tả để tool tự chỉnh</b>"))
        layout.addLayout(desc_row)
        layout.addWidget(self.describe_note)
        layout.addWidget(adv)
        layout.addWidget(self.preview)
        layout.addWidget(buttons)
        self.ok_btn = buttons.button(QDialogButtonBox.Ok)
        self.ok_btn.setEnabled(False)

        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        self.zoom.valueChanged.connect(lambda v: self.view.set_zoom(float(v)))
        self.view.beat_clicked.connect(self._set_transition_index)
        self.view.beat_menu.connect(self._menu_action)
        for w in (self.start, self.transition, self.offset):
            w.valueChanged.connect(self._controls_changed)
        self.end.valueChanged.connect(self._controls_changed)
        self.to_end.toggled.connect(self._controls_changed)
        self.density.currentIndexChanged.connect(self._density_changed)
        for w in (self.st_transition, self.st_loop_start, self.st_loop_end, self.st_unit, self.loop_period):
            w.valueChanged.connect(self._controls_changed)
        self.effects.itemChanged.connect(lambda _i: self._controls_changed())
        self.describe_btn.clicked.connect(self._describe)
        self.suggest_btn.clicked.connect(self._suggest)
        self.play_btn.clicked.connect(self._toggle_play)
        self.play_tr_btn.clicked.connect(lambda: self._play_from(self.view.beat_time(self.plan.transition_index) - 1.0))

        self.player = None
        if QMediaPlayer is not None:
            self.player = QMediaPlayer(self)
            self.audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self.audio_out)
            self.player.setSource(QUrl.fromLocalFile(str(self.music_path)))
            self.timer = QTimer(self)
            self.timer.setInterval(30)
            self.timer.timeout.connect(self._tick)
        else:
            self.play_btn.setEnabled(False)
            self.play_tr_btn.setEnabled(False)

        self._fill_structure()
        self._set_enabled(False)
        run_in_background(self._analyze, self._analyzed, self._failed)

    # ---------- dò beat ----------
    def _beat_spin(self, lo: float = -8, hi: float = 999) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(2)
        s.setSingleStep(0.25)
        return s

    def _analyze(self):
        y = load_audio(self.music_path)
        hop = 256
        n = len(y) // hop
        env = np.sqrt((y[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n else np.zeros(1)
        grid = music_grid(self.music_path)
        return env, SR / hop, len(y) / SR, grid

    def _analyzed(self, result) -> None:
        env, rate, duration, grid = result
        self.duration = duration
        self.raw_grid = grid
        self.view.set_audio(env, rate, duration)
        if self.plan is None:
            self.plan = default_plan(self.formula, grid, self.same_music, structure=self.structure)
        self._set_enabled(True)
        self._load_plan(self.plan)
        self._apply_description_if_any()

    def _failed(self, message: str) -> None:
        self.music_info.setText(f"Không dò được beat: {message}")
        error(self, f"Không dò được beat của {self.music_path.name}: {message}")

    def _set_enabled(self, on: bool) -> None:
        for w in (self.density, self.offset, self.start, self.transition, self.end, self.to_end,
                  self.describe_btn, self.suggest_btn, self.ok_btn):
            w.setEnabled(on)

    def _apply_description_if_any(self) -> None:
        if self.description.toPlainText().strip() and self.plan and not self.plan.note:
            self._describe()

    # ---------- đồng bộ điều khiển ----------
    def _grid(self) -> BeatGrid:
        return apply_density(self.raw_grid, self.plan.density)

    def _fill_structure(self) -> None:
        self._updating = True
        st = self.structure
        self.st_transition.setValue(st.transition)
        self.st_loop_start.setValue(st.loop_start)
        self.st_loop_end.setValue(st.loop_end)
        self.st_unit.setValue(st.intro_unit)
        self._updating = False

    def _load_plan(self, plan: BeatPlan) -> None:
        self._updating = True
        g = apply_density(self.raw_grid, plan.density)
        n = len(g.times)
        self.density.setCurrentIndex(max(0, self.density.findData(plan.density)))
        self.offset.setValue(int(round(plan.offset_ms)))
        self.start.setRange(1, n)
        self.start.setValue(plan.start_index + 1)
        self.transition.setRange(2, max(2, n + 8))
        self.transition.setValue(plan.transition_index - plan.start_index + 1)
        self.to_end.setChecked(plan.end_index is None)
        self.end.setEnabled(plan.end_index is not None)
        end_label = (plan.end_index if plan.end_index is not None else g.to_beat(self.duration)) - plan.start_index + 1
        self.end.setValue(float(end_label))
        self.loop_period.setValue(plan.loop_period or 0)
        if plan.intro_unit:
            self.st_unit.setValue(plan.intro_unit)
        removed = {r.lower() for r in plan.remove_effects}
        self.effects.blockSignals(True)
        for i in range(self.effects.count()):
            item = self.effects.item(i)
            item.setCheckState(Qt.Unchecked if item.text().lower() in removed else Qt.Checked)
        self.effects.blockSignals(False)
        self._updating = False
        self._sync_structure()
        self.music_info.setText(f"{self.music_path.name}: {g.tempo:.0f} BPM · {n} beat · dài {self.duration:.1f}s")
        self._refresh()

    def _read_controls(self) -> BeatPlan:
        start = self.start.value() - 1
        removed = [self.effects.item(i).text() for i in range(self.effects.count())
                   if self.effects.item(i).checkState() != Qt.Checked]
        return replace(
            self.plan,
            offset_ms=float(self.offset.value()),
            start_index=start,
            transition_index=start + self.transition.value() - 1,
            end_index=None if self.to_end.isChecked() else start + self.end.value() - 1,
            remove_effects=removed,
            intro_unit=None,  # nằm trong cấu trúc công thức (ô "Lặp trước chuyển cảnh")
            loop_period=self.loop_period.value() or None,
        )

    def _controls_changed(self, *_args) -> None:
        if self._updating or self.raw_grid is None:
            return
        self.end.setEnabled(not self.to_end.isChecked())
        self._sync_structure()
        self.plan = self._read_controls()
        self._refresh()

    def _sync_structure(self) -> None:
        self.structure = clamp_structure(Structure(self.st_transition.value(), self.st_loop_start.value(),
                                                   self.st_loop_end.value(), self.st_unit.value()), self.formula)
        self.info.setText(summarize_structure(self.formula, self.structure))

    def _density_changed(self) -> None:
        if self._updating or self.raw_grid is None:
            return
        new = float(self.density.currentData())
        old = self.plan.density
        if new == old:
            return
        f = new / old
        p = self._read_controls()
        self.plan = replace(p, density=new, start_index=int(round(p.start_index * f)),
                            transition_index=int(round(p.transition_index * f)),
                            end_index=None if p.end_index is None else p.end_index * f)
        self._load_plan(self.plan)

    def _set_transition_index(self, i: int) -> None:
        if i <= self.plan.start_index:
            return
        self.transition.setValue(i - self.plan.start_index + 1)

    def _menu_action(self, i: int, action: str) -> None:
        p = self.plan
        if action == "transition":
            self._set_transition_index(i)
        elif action == "start":
            d = i - p.start_index
            self.plan = replace(p, start_index=i, transition_index=p.transition_index + d,
                                end_index=None if p.end_index is None else p.end_index + d)
            self._load_plan(self.plan)
        elif action == "end":
            if i > p.transition_index:
                self.to_end.setChecked(False)
                self.end.setValue(i - p.start_index + 1)
        elif action == "play":
            self._play_from(self.view.beat_time(i))

    def _refresh(self) -> None:
        g = self._grid()
        self.view.grid = g
        self.view.offset_s = self.plan.offset_ms / 1000
        self.view.plan = self.plan
        end_beat = self.plan.end_index if self.plan.end_index is not None else g.to_beat(self.duration - self.view.offset_s)
        try:
            pieces = plan_pieces(self.formula, self.structure, self.plan, end_beat)
            self.view.pieces = pieces
            parts: dict[str, float] = {}
            for piece in pieces:
                parts[piece.part] = parts.get(piece.part, 0.0) + piece.out_b - piece.out_a
            start_s = max(g.to_time(self.plan.start_index) + self.view.offset_s, 0)
            end_s = min(g.to_time(end_beat) + self.view.offset_s, self.duration)
            colors = {"đầu": "#4682dc", "lặp trước chuyển cảnh": "#78a0f0", "bùng": "#f09632", "lặp": "#46be6e", "kết": "#aa64dc"}
            text = " · ".join(f"<span style='color:{colors.get(k, '#ccc')}'>■</span> {k} {v:.4g} beat" for k, v in parts.items())
            removed = f" · bỏ: {', '.join(self.plan.remove_effects)}" if self.plan.remove_effects else ""
            self.preview.setText(f"<b>Video {end_s - start_s:.1f}s</b> (giây {start_s:.1f} → {end_s:.1f} của nhạc): {text}{removed}")
            self.ok_btn.setEnabled(True)
        except ValueError as e:
            self.view.pieces = []
            self.preview.setText(f"<span style='color:#ff7070'>⚠ {e}</span>")
            self.ok_btn.setEnabled(False)
        self.view.update()

    # ---------- miêu tả / gợi ý ----------
    def _describe(self) -> None:
        text = self.description.toPlainText().strip()
        if not text or self.raw_grid is None:
            return
        self.describe_btn.setEnabled(False)
        self.describe_note.setText("Đang phân tích miêu tả…")
        base = self._read_controls()
        config = AIConfig.load(self.settings)
        run_in_background(lambda: parse_description(text, self.formula, self.raw_grid, base, config=config),
                          self._described, self._describe_failed)

    def _described(self, result) -> None:
        plan, notes, source = result
        self.describe_btn.setEnabled(True)
        plan.note = "; ".join(notes)
        self.plan = plan
        self._load_plan(plan)
        self.describe_note.setText(f"[{source}] " + ("; ".join(notes) if notes else
                                   "Không tìm thấy ý nào áp được. Thử: 'chuyển cảnh ở beat 8, bỏ pixelate, dài 20 giây'."))

    def _describe_failed(self, message: str) -> None:
        self.describe_btn.setEnabled(True)
        self.describe_note.setText(f"Lỗi phân tích miêu tả: {message}")

    def _suggest(self) -> None:
        g = self._grid()
        t = self.plan.transition_index
        lo, hi = max(self.plan.start_index + 1, t - 2), min(len(g.strengths) - 1, t + 2)
        if hi < lo:
            return
        best = max(range(lo, hi + 1), key=lambda i: float(g.strengths[i]))
        self._set_transition_index(best)

    # ---------- nghe thử ----------
    def _toggle_play(self) -> None:
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.timer.stop()
            self.play_btn.setText("▶ Nghe thử")
        else:
            start = max(self._grid().to_time(self.plan.start_index) + self.plan.offset_ms / 1000, 0)
            if self.player.position() / 1000 < start or self.view.playhead is None:
                self.player.setPosition(int(start * 1000))
            self.player.play()
            self.timer.start()
            self.play_btn.setText("⏸ Dừng")

    def _play_from(self, t: float) -> None:
        if self.player is None:
            return
        self.player.setPosition(int(max(t, 0) * 1000))
        self.player.play()
        self.timer.start()
        self.play_btn.setText("⏸ Dừng")

    def _tick(self) -> None:
        t = self.player.position() / 1000
        self.view.playhead = t
        self.view.update()
        self.scroll.ensureVisible(int(self.view.x(t)), 10, 200, 10)
        if self.player.playbackState() != QMediaPlayer.PlayingState:
            self.timer.stop()
            self.play_btn.setText("▶ Nghe thử")

    # ---------- kết thúc ----------
    def _accept(self) -> None:
        self.plan = self._read_controls()
        self.plan.note = self.plan.note or ""
        if self.structure != self.saved_structure:
            self.formula["structure"] = self.structure.to_dict()
            save_formula(self.formula)
        if self.player is not None:
            self.player.stop()
        self.accept()

    def reject(self) -> None:
        if self.player is not None:
            self.player.stop()
        super().reject()

    def result_plan(self) -> BeatPlan:
        return self.plan
