"""Hộp thoại cấu hình model AI: Claude, model free hoặc Ollama local."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from ..ai.client import ENV_KEYS, MODEL_CHOICES, AIConfig, PROVIDERS, chat_json
from .common import Settings


class AIConfigDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Cấu hình AI")
        self.setMinimumWidth(720)

        self.provider = QComboBox()
        self.provider.addItem("Tự động dò key có sẵn", "auto")
        for key, info in PROVIDERS.items():
            self.provider.addItem(info["label"], key)

        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("Chọn hoặc gõ tên model")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.base = QLineEdit()
        self.base.setPlaceholderText("Để trống dùng địa chỉ mặc định của nhà cung cấp")

        self.status = QLabel(wordWrap=True)
        self.status.setObjectName("muted")

        form = QFormLayout()
        form.addRow("Nhà cung cấp", self.provider)
        form.addRow("Model", self.model)
        form.addRow("API key", self.key)
        form.addRow("Base URL", self.base)

        self.custom_prompt = QPlainTextEdit()
        self.custom_prompt.setPlaceholderText(
            "Ví dụ: Ưu tiên video ngắn 15–30 giây, nhịp nhanh, caption tiếng Việt tự nhiên, "
            "không chọn project thiếu nhạc nền…"
        )
        self.custom_prompt.setMaximumHeight(100)
        form.addRow("Prompt hướng dẫn AI", self.custom_prompt)

        self.extra_slots = []
        ensemble = QGroupBox("Kết hợp tối đa 3 model (mỗi model sau sẽ rà soát kết quả trước)")
        ensemble_form = QFormLayout(ensemble)
        for number in (2, 3):
            enabled = QCheckBox(f"Dùng model {number}")
            provider = QComboBox()
            for key, info in PROVIDERS.items():
                if key != "custom":
                    provider.addItem(info["label"], key)
            model = QComboBox()
            model.setEditable(True)
            key = QLineEdit()
            key.setEchoMode(QLineEdit.Password)
            key.setPlaceholderText("Dùng biến môi trường nếu để trống")
            model_row = QHBoxLayout()
            model_row.addWidget(provider, 2)
            model_row.addWidget(model, 3)
            key_row = QHBoxLayout()
            key_row.addWidget(key)
            slot = {"number": number, "enabled": enabled, "provider": provider,
                    "model": model, "key": key}
            self.extra_slots.append(slot)
            provider.currentIndexChanged.connect(
                lambda _index, current=slot: self._extra_provider_changed(current)
            )
            ensemble_form.addRow(enabled, model_row)
            ensemble_form.addRow("API key model " + str(number), key_row)
        self.ensemble_note = QLabel(
            "Model miễn phí/trả phí có sẵn trong danh sách provider. Mỗi dịch vụ cần API key "
            "riêng (có thể để trống nếu đã đặt biến môi trường); Ollama chạy local miễn phí. "
            "Khi chọn 2–3 model, mỗi model sau sẽ nhận JSON của model trước để rà soát và tổng hợp."
        )
        self.ensemble_note.setWordWrap(True)
        self.ensemble_note.setObjectName("muted")

        note = QLabel(
            "Model free: OpenRouter (model có đuôi :free), Groq và Google Gemini có hạn mức "
            "miễn phí; Ollama chạy local không cần key. Key được lưu trong data/settings.json "
            "trên máy này — đừng chia sẻ file đó. Để trống ô key nếu đã đặt biến môi trường "
            "(ANTHROPIC_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY…).\n"
            "Veo 3 là model tạo video, không viết được kế hoạch mẫu CapCut; hãy dùng Veo 3 "
            "tạo clip riêng rồi đưa clip vào CapCut.")
        note.setWordWrap(True)
        note.setObjectName("muted")

        check_btn = QPushButton("Kiểm tra kết nối")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(check_btn)
        row.addStretch()
        row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(ensemble)
        layout.addWidget(self.ensemble_note)
        layout.addWidget(note)
        layout.addWidget(self.status)
        layout.addLayout(row)

        self.provider.currentIndexChanged.connect(self._provider_changed)
        check_btn.clicked.connect(self._check)
        self._load()

    # ---------- dữ liệu ----------
    def _load(self) -> None:
        provider = str(self.settings.get("ai_provider", "auto") or "auto")
        index = self.provider.findData(provider)
        self.provider.blockSignals(True)
        self.provider.setCurrentIndex(max(index, 0))
        self.provider.blockSignals(False)

        preset = PROVIDERS.get(provider, {})
        desired = str(self.settings.get("ai_model", "") or preset.get("model", ""))
        self._set_models(provider, desired)
        self.custom_prompt.setPlainText(str(self.settings.get("ai_custom_prompt", "") or ""))
        saved_extras = self.settings.get("ai_extra_models", []) or []
        for slot, saved in zip(self.extra_slots, saved_extras):
            if not isinstance(saved, dict):
                continue
            slot["enabled"].setChecked(True)
            extra_provider = str(saved.get("provider", "openrouter"))
            extra_index = slot["provider"].findData(extra_provider)
            if extra_index >= 0:
                slot["provider"].setCurrentIndex(extra_index)
            self._extra_provider_changed(slot)
            extra_model = str(saved.get("model", ""))
            if extra_model and slot["model"].findText(extra_model) < 0:
                slot["model"].addItem(extra_model)
            slot["model"].setCurrentText(extra_model)
            slot["key"].setText(str(saved.get("api_key", "")))
        self.base.setText(str(self.settings.get("ai_base_url", "") or preset.get("base_url", "")))
        self.key.setText(str(self.settings.get("ai_key", "") or ""))
        self._update_help()

    def _provider_changed(self) -> None:
        provider = self.provider.currentData()
        preset = PROVIDERS.get(provider, {})
        self._set_models(provider, preset.get("model", ""))

    def _extra_provider_changed(self, slot: dict) -> None:
        provider = str(slot["provider"].currentData() or "")
        options = MODEL_CHOICES.get(provider, [])
        desired = slot["model"].currentText()
        preset = PROVIDERS.get(provider, {})
        slot["model"].blockSignals(True)
        slot["model"].clear()
        slot["model"].addItems(options)
        if desired and slot["model"].findText(desired) < 0:
            slot["model"].addItem(desired)
        slot["model"].setCurrentText(desired or preset.get("model", ""))
        slot["model"].blockSignals(False)
        self.base.setText(preset.get("base_url", ""))
        self._update_help()

    def _set_models(self, provider: str, desired: str) -> None:
        options = MODEL_CHOICES.get(provider, [])
        self.model.blockSignals(True)
        self.model.clear()
        self.model.addItems(options)
        if desired and desired not in options:
            self.model.addItem(desired)
        self.model.setCurrentText(desired or (options[0] if options else ""))
        self.model.blockSignals(False)

    def _update_help(self) -> None:
        provider = self.provider.currentData()
        env = ENV_KEYS.get(provider, ())
        if provider == "auto":
            self.key.setPlaceholderText("Để trống = tự dò biến môi trường")
            self.model.lineEdit().setPlaceholderText("Để trống = tự chọn model của provider có key")
        elif provider == "ollama":
            self.key.setPlaceholderText("Không cần key (chạy local)")
            self.model.lineEdit().setPlaceholderText("Chọn hoặc gõ tên model đã pull")
        elif env:
            self.key.setPlaceholderText(f"Để trống nếu đã đặt {env[0]}")
            self.model.lineEdit().setPlaceholderText("Chọn hoặc gõ tên model")
        else:
            self.key.setPlaceholderText("Nhập API key của dịch vụ")
            self.model.lineEdit().setPlaceholderText("Chọn hoặc gõ tên model")

    def _config(self) -> AIConfig:
        extras = []
        for slot in self.extra_slots:
            if not slot["enabled"].isChecked():
                continue
            provider = str(slot["provider"].currentData() or "")
            model = slot["model"].currentText().strip()
            if not model:
                continue
            extras.append({
                "provider": provider,
                "model": model,
                "api_key": slot["key"].text().strip(),
                "base_url": PROVIDERS.get(provider, {}).get("base_url", ""),
            })
        return AIConfig(
            provider=str(self.provider.currentData()),
            model=self.model.currentText().strip(),
            api_key=self.key.text().strip(),
            base_url=self.base.text().strip(),
            extra_models=extras,
            custom_prompt=self.custom_prompt.toPlainText().strip(),
        )

    def _save(self) -> None:
        config = self._config()
        self.settings.set("ai_provider", config.provider)
        self.settings.set("ai_model", config.model)
        self.settings.set("ai_key", config.api_key)
        self.settings.set("ai_base_url", config.base_url)
        self.settings.set("ai_extra_models", config.extra_models)
        self.settings.set("ai_custom_prompt", config.custom_prompt)
        self.accept()

    # ---------- kiểm tra ----------
    def _check(self) -> None:
        config = self._config()
        self.status.setText("Đang kiểm tra kết nối… (có thể mất vài giây)")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            chat_json(
                "Bạn kiểm tra kết nối. Chỉ trả về JSON.",
                'Trả về đúng JSON {"ok": true}.',
                config=config,
                timeout=20,
            )
        except Exception as exc:
            self.status.setText(f"✗ {exc}")
        else:
            self.status.setText("✓ Kết nối OK, model trả về JSON hợp lệ.")
        finally:
            QApplication.restoreOverrideCursor()
