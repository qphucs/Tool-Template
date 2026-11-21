"""Python desktop tools for social marketing covers and video preflight checks."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import cv2
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QDoubleSpinBox, QVBoxLayout, QWidget, QPlainTextEdit,
    QTabWidget,
)

from .ai_dialog import AIConfigDialog
from .common import Settings, run_in_background
from .content_workflow import ContentWorkflowTab


class MarketingTab(QWidget):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.video_path: Path | None = None
        self.cover_path: Path | None = None
        self._cover_image: QImage | None = None

        self.video_label = QLabel("Chưa chọn video")
        self.video_label.setObjectName("muted")
        self.choose_video = QPushButton("Chọn video…")
        self.choose_video.setObjectName("primary")
        self.title = QLineEdit()
        self.title.setPlaceholderText("VD: Ưu đãi mùa hè – giảm đến 50%")
        self.brand = QLineEdit()
        self.brand.setPlaceholderText("Tên thương hiệu hoặc tài khoản (không bắt buộc)")
        self.timestamp = QDoubleSpinBox()
        self.timestamp.setRange(0, 86400)
        self.timestamp.setDecimals(1)
        self.timestamp.setSuffix(" giây")
        self.aspect = QComboBox()
        self.aspect.addItem("Dọc 9:16 · Reels/TikTok", "vertical")
        self.aspect.addItem("Dọc 4:5 · Facebook Feed", "portrait")
        self.aspect.addItem("Vuông 1:1 · Feed", "square")
        self.make_cover = QPushButton("Tạo ảnh bìa")
        self.make_cover.setObjectName("primary")
        self.cover_preview = QLabel("Ảnh bìa xem trước sẽ hiện ở đây")
        self.cover_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_preview.setMinimumSize(260, 300)
        self.cover_preview.setStyleSheet("background:#18191c;border:1px dashed #555;border-radius:8px;color:#999;")
        self.save_cover = QPushButton("Lưu ảnh bìa PNG…")
        self.save_cover.setEnabled(False)

        cover_form = QFormLayout()
        cover_form.addRow("Tiêu đề quảng cáo", self.title)
        cover_form.addRow("Thương hiệu", self.brand)
        cover_form.addRow("Lấy khung hình tại", self.timestamp)
        cover_form.addRow("Tỷ lệ ảnh bìa", self.aspect)
        cover_group = QGroupBox("1 · Tạo ảnh bìa từ video")
        cover_layout = QVBoxLayout(cover_group)
        cover_layout.addWidget(self.video_label)
        cover_layout.addWidget(self.choose_video)
        cover_layout.addLayout(cover_form)
        cover_layout.addWidget(self.make_cover)
        cover_layout.addWidget(self.save_cover)

        self.platform = QComboBox()
        self.platform.addItem("Facebook Reels", "facebook_reels")
        self.platform.addItem("Facebook Feed", "facebook_feed")
        self.platform.addItem("TikTok bài đăng thường", "tiktok_organic")
        self.platform.addItem("TikTok quảng cáo In-Feed", "tiktok_ads")
        self.check_video = QPushButton("Kiểm tra video")
        self.check_video.setObjectName("primary")
        self.qc_result = QLabel("Chọn video để rà soát thông số trước khi đăng.")
        self.qc_result.setWordWrap(True)
        self.qc_result.setTextFormat(Qt.TextFormat.RichText)
        qc_group = QGroupBox("2 · Kiểm tra video quảng cáo / bài đăng")
        qc_layout = QVBoxLayout(qc_group)
        qc_row = QHBoxLayout()
        qc_row.addWidget(self.platform, 1)
        qc_row.addWidget(self.check_video)
        qc_layout.addLayout(qc_row)
        qc_layout.addWidget(self.qc_result)
        qc_layout.addWidget(QLabel("Rà soát kỹ thuật sơ bộ; âm thanh, vùng an toàn, quyền nhạc/hình và nhãn tài trợ cần kiểm tra thủ công."), 0, Qt.AlignmentFlag.AlignTop)

        preview_group = QGroupBox("Xem trước ảnh bìa")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.addWidget(self.cover_preview, 1)

        content = QHBoxLayout()
        content.addWidget(cover_group, 3)
        content.addWidget(preview_group, 2)

        self.marketing_tabs = QTabWidget()
        cover_page = QWidget()
        cover_page.setLayout(content)
        self.marketing_tabs.addTab(self._build_image_page(), "Tạo ảnh từ prompt")
        self.marketing_tabs.addTab(self._build_video_page(), "Tạo video từ prompt")
        self.marketing_tabs.addTab(cover_page, "Ảnh bìa từ video")
        self.marketing_tabs.addTab(qc_group, "Kiểm tra bài đăng")
        self.content_workflow = ContentWorkflowTab(settings, self._apply_approved_content)
        self.marketing_tabs.addTab(self.content_workflow, "AI soạn nội dung & duyệt")
        root = QVBoxLayout(self)
        heading = QLabel("Marketing Studio · Facebook / TikTok")
        heading.setStyleSheet("font-size:18px;font-weight:700;padding:4px 0 8px;")
        root.addWidget(heading)
        root.addWidget(self.marketing_tabs, 1)

        self.choose_video.clicked.connect(self._choose_video)
        self.make_cover.clicked.connect(self._make_cover)
        self.save_cover.clicked.connect(self._save_cover)
        self.check_video.clicked.connect(self._check_video)

    def _apply_approved_content(self, content: dict) -> None:
        """Copy approved prompts only; generation remains a deliberate user action."""
        self.image_prompt.setPlainText(str(content.get("image_prompt", "")))
        self.video_prompt.setPlainText(str(content.get("video_prompt", "")))
        platform = self.content_workflow.platform.currentText()
        if "Facebook" in platform:
            self.image_ratio.setCurrentIndex(3)  # landscape
            self.video_platform.setCurrentIndex(1)  # 16:9
        else:
            self.image_ratio.setCurrentIndex(0)  # 9:16
            self.video_platform.setCurrentIndex(0)
        self.marketing_tabs.setCurrentWidget(self.marketing_tabs.widget(0))

    def _build_image_page(self) -> QWidget:
        page = QWidget()
        self.image_prompt = QPlainTextEdit(str(self.settings.get("marketing_image_prompt", "") or ""))
        self.image_prompt.setPlaceholderText("Mô tả ảnh quảng cáo: sản phẩm, bối cảnh, màu sắc, phong cách, ánh sáng và nội dung chữ cần có…")
        self.image_prompt.setMinimumHeight(105)
        self.image_provider = QComboBox()
        self.image_provider.addItem("OpenAI", "openai")
        self.image_provider.addItem("Google Gemini", "gemini")
        self.image_provider.addItem("ComfyUI local · miễn phí", "comfyui")
        saved_provider = str(self.settings.get("marketing_image_provider", "comfyui") or "comfyui")
        provider_index = self.image_provider.findData(saved_provider)
        if provider_index >= 0:
            self.image_provider.setCurrentIndex(provider_index)
        self.image_model = QComboBox()
        self.image_model.setEditable(True)
        self._fill_image_models()
        self.comfyui_url = QLineEdit(str(self.settings.get("comfyui_url", "http://127.0.0.1:8188") or "http://127.0.0.1:8188"))
        self.comfyui_url.setPlaceholderText("http://127.0.0.1:8188 · cần ComfyUI đang chạy")
        self.image_ratio = QComboBox()
        self.image_ratio.addItem("TikTok / Reels · dọc 9:16", ("1024x1536", "9:16"))
        self.image_ratio.addItem("Facebook Feed · 4:5", ("1024x1536", "4:5"))
        self.image_ratio.addItem("Facebook Feed · vuông 1:1", ("1024x1024", "1:1"))
        self.image_ratio.addItem("Facebook ngang · 3:2", ("1536x1024", "3:2"))
        self.image_generate = QPushButton("Tạo ảnh quảng cáo")
        self.image_generate.setObjectName("primary")
        self.image_save = QPushButton("Lưu ảnh PNG…")
        self.image_save.setEnabled(False)
        self.image_configure = QPushButton("Cấu hình AI / API key…")
        self.image_status = QLabel("Ảnh và prompt được tạo riêng, không dùng khung hình video mẫu.")
        self.image_status.setWordWrap(True)
        self.image_status.setObjectName("muted")
        self.image_preview = QLabel("Ảnh tạo bằng AI sẽ hiện tại đây")
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setMinimumSize(320, 360)
        self.image_preview.setStyleSheet("background:#18191c;border:1px dashed #555;border-radius:8px;color:#999;")
        form = QFormLayout()
        self.image_form = form
        form.addRow("Nhà cung cấp AI", self.image_provider)
        form.addRow("Model tạo ảnh", self.image_model)
        form.addRow("ComfyUI URL local", self.comfyui_url)
        form.addRow("Tỷ lệ / nền tảng", self.image_ratio)
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Prompt tạo ảnh</b>"))
        left.addWidget(self.image_prompt, 1)
        left.addLayout(form)
        left.addWidget(self.image_configure)
        left.addWidget(self.image_generate)
        left.addWidget(self.image_save)
        left.addWidget(self.image_status)
        row = QHBoxLayout(page)
        row.addLayout(left, 3)
        row.addWidget(self.image_preview, 2)
        self.image_generate.clicked.connect(self._generate_image)
        self.image_save.clicked.connect(self._save_generated_image)
        self.image_provider.currentIndexChanged.connect(self._fill_image_models)
        self.image_provider.currentIndexChanged.connect(self._toggle_comfyui_fields)
        self.image_configure.clicked.connect(self._configure_image_ai)
        self._toggle_comfyui_fields()
        return page

    def _build_video_page(self) -> QWidget:
        page = QWidget()
        self.video_prompt = QPlainTextEdit(str(self.settings.get("marketing_video_prompt", "") or ""))
        self.video_prompt.setPlaceholderText("Mô tả video riêng: chủ thể, hành động, bối cảnh, chuyển động camera, ánh sáng, nhịp dựng và âm thanh…")
        self.video_prompt.setMinimumHeight(120)
        self.video_platform = QComboBox()
        self.video_platform.addItem("TikTok / Reels · dọc 9:16", ("9:16", "tiktok"))
        self.video_platform.addItem("Facebook video · ngang 16:9", ("16:9", "facebook"))
        self.video_duration = QComboBox()
        self.video_duration.addItem("4 giây", 4)
        self.video_duration.addItem("6 giây", 6)
        self.video_duration.addItem("8 giây", 8)
        self.video_model = QComboBox()
        self.video_model.addItem("Veo 3.1 Fast · tiết kiệm hơn", "veo-3.1-fast-generate-001")
        self.video_model.addItem("Veo 3.1 · chất lượng cao", "veo-3.1-generate-001")
        self.gcp_project = QLineEdit(str(self.settings.get("google_cloud_project", "") or ""))
        self.gcp_project.setPlaceholderText("Google Cloud Project ID")
        self.gcp_location = QLineEdit(str(self.settings.get("google_cloud_location", "us-central1") or "us-central1"))
        self.gcp_location.setPlaceholderText("us-central1")
        self.video_generate = QPushButton("Tạo video bằng Veo")
        self.video_generate.setObjectName("primary")
        self.video_open = QPushButton("Mở video đã tạo")
        self.video_open.setEnabled(False)
        self.video_status = QLabel("Prompt video độc lập với prompt ảnh. Cần Google Cloud Project, Vertex AI và đăng nhập gcloud.")
        self.video_status.setWordWrap(True)
        self.video_status.setObjectName("muted")
        self.video_result_path: Path | None = None
        form = QFormLayout()
        form.addRow("Nền tảng / tỷ lệ", self.video_platform)
        form.addRow("Thời lượng", self.video_duration)
        form.addRow("Model video", self.video_model)
        form.addRow("Google Cloud Project", self.gcp_project)
        form.addRow("Vùng Vertex AI", self.gcp_location)
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Prompt tạo video</b>"))
        layout.addWidget(self.video_prompt, 1)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        buttons.addWidget(self.video_generate)
        buttons.addWidget(self.video_open)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addWidget(self.video_status)
        self.video_generate.clicked.connect(self._generate_video)
        self.video_open.clicked.connect(self._open_generated_video)
        return page

    def _fill_image_models(self, *_args) -> None:
        provider = str(self.image_provider.currentData() or "openai")
        options = {
            "openai": [
                ("gpt-image-2.5-sunburst", "GPT Image 2.5 Sunburst · OpenAI"),
                ("gpt-image-2.5-flare", "GPT Image 2.5 Flare · OpenAI"),
                ("gpt-image-2", "GPT Image 2 · OpenAI"),
            ],
            "gemini": [
                ("gemini-nano-banana-2.1", "Nano Banana 2.1 · chất lượng cao"),
                ("gemini-3.1-flash-image", "Nano Banana 2 · cân bằng"),
                ("gemini-3.1-flash-lite-image", "Nano Banana 2 Lite · nhanh"),
                ("gemini-3-pro-image", "Nano Banana Pro · cao cấp"),
            ],
            "comfyui": [("sd_xl_base_1.0.safetensors", "Checkpoint SDXL (sửa thành tên file model đã cài)")],
        }.get(provider, [])
        selected = str(self.settings.get("marketing_image_model", "") or "")
        self.image_model.blockSignals(True)
        self.image_model.clear()
        for model, label in options:
            self.image_model.addItem(label, model)
        index = self.image_model.findData(selected)
        if index >= 0:
            self.image_model.setCurrentIndex(index)
        self.image_model.blockSignals(False)

    def _toggle_comfyui_fields(self, *_args) -> None:
        local = self.image_provider.currentData() == "comfyui"
        self.image_form.setRowVisible(self.comfyui_url, local)

    def _configure_image_ai(self) -> None:
        AIConfigDialog(self.settings, self).exec()

    def _image_api_key(self, provider: str) -> str:
        env_names = {"openai": ("OPENAI_API_KEY",), "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY")}.get(provider, ())
        for env_name in env_names:
            if os.environ.get(env_name, "").strip():
                return os.environ[env_name].strip()
        if self.settings.get("ai_provider") == provider:
            key = str(self.settings.get("ai_key", "") or "").strip()
            if key:
                return key
        for model in self.settings.get("ai_extra_models", []) or []:
            if isinstance(model, dict) and model.get("provider") == provider and model.get("api_key"):
                return str(model["api_key"]).strip()
        return ""

    def _generate_image(self) -> None:
        prompt = self.image_prompt.toPlainText().strip()
        approved_content = self.content_workflow.approved_content
        if (not self.content_workflow.media_approved or
                prompt != str(approved_content.get("image_prompt", "")).strip()):
            QMessageBox.information(self, "Cần admin duyệt", "Chỉ prompt ảnh đã được admin duyệt mới được gửi tạo. Hãy soạn/gửi duyệt nội dung trước.")
            self.marketing_tabs.setCurrentWidget(self.content_workflow)
            return
        provider = str(self.image_provider.currentData() or "openai")
        model = str(self.image_model.currentData() or self.image_model.currentText() or "").strip()
        api_key = self._image_api_key(provider) if provider != "comfyui" else ""
        if not prompt:
            QMessageBox.information(self, "Thiếu prompt", "Hãy mô tả ảnh quảng cáo cần tạo.")
            return
        if provider == "comfyui" and not self.comfyui_url.text().strip().startswith(("http://", "https://")):
            QMessageBox.information(self, "Thiếu ComfyUI", "Nhập URL ComfyUI local, thường là http://127.0.0.1:8188.")
            return
        if provider != "comfyui" and not api_key:
            service = "OpenAI" if provider == "openai" else "Google Gemini"
            QMessageBox.information(self, "Chưa cấu hình API key", f"Cấu hình {service} trong nút AI / API key trước.")
            return
        if provider != "comfyui":
            if QMessageBox.question(self, "Tạo ảnh AI", f"{self.image_model.currentText()} có thể tính phí cho lượt tạo ảnh này. Tiếp tục?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        size, ratio = self.image_ratio.currentData()
        self.settings.set("marketing_image_prompt", prompt)
        self.settings.set("marketing_image_provider", provider)
        self.settings.set("marketing_image_model", model)
        self.settings.set("comfyui_url", self.comfyui_url.text().strip().rstrip("/"))
        self.image_generate.setEnabled(False)
        self.image_status.setText("Đang tạo ảnh từ prompt…")
        full_prompt = f"{prompt}\nTỷ lệ khung hình mục tiêu {ratio}. Thiết kế quảng cáo mạng xã hội, chủ thể rõ, bố cục gọn, chừa vùng an toàn cho chữ."
        if provider == "openai":
            task = lambda: self._request_openai_image(api_key, model, full_prompt, size, ratio)
        elif provider == "gemini":
            task = lambda: self._request_gemini_image(api_key, model, full_prompt, size, ratio)
        else:
            base = self.comfyui_url.text().strip().rstrip("/")
            task = lambda: self._request_comfyui_image(base, model, full_prompt, size)
        run_in_background(task, self._image_done, self._image_failed)

    @staticmethod
    def _request_comfyui_image(base_url: str, checkpoint: str, prompt: str, size: str) -> bytes:
        import time
        try:
            width, height = (int(part) for part in size.split("x", 1))
        except (ValueError, TypeError):
            width, height = 1024, 1024
        if width > height:
            width, height = 1216, 832
        elif height > width:
            width, height = 832, 1216
        else:
            width = height = 1024
        workflow = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "low quality, blurry, malformed text, watermark", "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": min(width, 1536), "height": min(height, 1536), "batch_size": 1}},
            "5": {"class_type": "KSampler", "inputs": {"seed": int(time.time() * 1000) % 2**32, "steps": 24, "cfg": 6.0, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}},
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "MarketingStudio", "images": ["6", 0]}},
        }
        req = urllib.request.Request(f"{base_url}/prompt", data=json.dumps({"prompt": workflow}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                prompt_id = json.loads(response.read().decode("utf-8"))["prompt_id"]
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ComfyUI không nhận workflow (HTTP {exc.code}): {exc.read(4096).decode('utf-8', errors='replace')}") from None
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(2)
            try:
                with urllib.request.urlopen(f"{base_url}/history/{prompt_id}", timeout=10) as response:
                    history = json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError:
                continue
            outputs = history.get(prompt_id, {}).get("outputs", {})
            images = [image for output in outputs.values() for image in output.get("images", [])]
            if images:
                item = images[0]
                query = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""), "type": item.get("type", "output")})
                with urllib.request.urlopen(f"{base_url}/view?{query}", timeout=30) as response:
                    return response.read(32 * 1024 * 1024)
        raise RuntimeError("Quá thời gian chờ ComfyUI. Kiểm tra model/checkpoint và hàng đợi ComfyUI.")

    @staticmethod
    def _request_openai_image(api_key: str, model: str, prompt: str, size: str, _ratio: str) -> bytes:
        body = json.dumps({"model": model, "prompt": prompt, "size": size}).encode("utf-8")
        request = urllib.request.Request("https://api.openai.com/v1/images/generations", data=body,
                                         headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read(32 * 1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(64 * 1024).decode("utf-8")).get("error", {}).get("message", "")
            except Exception:
                detail = ""
            raise RuntimeError(detail or f"OpenAI từ chối yêu cầu (HTTP {exc.code}).") from None
        images = result.get("data") or []
        if not images or not images[0].get("b64_json"):
            raise RuntimeError("OpenAI không trả về ảnh.")
        return base64.b64decode(images[0]["b64_json"])

    @staticmethod
    def _request_gemini_image(api_key: str, model: str, prompt: str, _size: str, ratio: str) -> bytes:
        body = json.dumps({
            "model": model,
            "input": prompt,
            "response_format": {"type": "image", "mime_type": "image/png", "aspect_ratio": ratio},
        }).encode("utf-8")
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/interactions",
            data=body,
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json", "Api-Revision": "2026-05-20"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                result = json.loads(response.read(64 * 1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_data = json.loads(exc.read(64 * 1024).decode("utf-8"))
                detail = error_data.get("error", {}).get("message", "")
            except Exception:
                detail = ""
            raise RuntimeError(detail or f"Gemini từ chối yêu cầu (HTTP {exc.code}).") from None
        output_image = result.get("output_image")
        encoded = output_image.get("data") if isinstance(output_image, dict) else None
        if not encoded:
            for step in result.get("steps", []):
                for item in step.get("content", []):
                    if item.get("type") == "image" and item.get("data"):
                        encoded = item["data"]
                        break
                if encoded:
                    break
        if not encoded:
            raise RuntimeError("Gemini không trả về ảnh.")
        return base64.b64decode(encoded)

    def _image_done(self, image_bytes: bytes) -> None:
        self.image_generate.setEnabled(True)
        self._generated_image = image_bytes
        pixmap = QPixmap()
        if not pixmap.loadFromData(image_bytes):
            self._image_failed("Không đọc được ảnh từ model đã chọn.")
            return
        self.image_preview.setPixmap(pixmap.scaled(self.image_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.image_save.setEnabled(True)
        self.image_status.setText("Đã tạo ảnh. Dùng Lưu ảnh PNG để chọn nơi lưu file.")

    def _image_failed(self, message: str) -> None:
        self.image_generate.setEnabled(True)
        self.image_status.setText(f"Tạo ảnh thất bại: {message}")

    def _save_generated_image(self) -> None:
        image_bytes = getattr(self, "_generated_image", b"")
        if not image_bytes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Lưu ảnh quảng cáo", "anh_quang_cao.png", "PNG (*.png)")
        if path:
            Path(path).write_bytes(image_bytes)
            self.image_status.setText(f"Đã lưu ảnh: {path}")

    def _generate_video(self) -> None:
        prompt = self.video_prompt.toPlainText().strip()
        approved_content = self.content_workflow.approved_content
        if (not self.content_workflow.media_approved or
                prompt != str(approved_content.get("video_prompt", "")).strip()):
            QMessageBox.information(self, "Cần admin duyệt", "Chỉ prompt video đã được admin duyệt mới được gửi tạo. Hãy soạn/gửi duyệt nội dung trước.")
            self.marketing_tabs.setCurrentWidget(self.content_workflow)
            return
        project = self.gcp_project.text().strip()
        location = self.gcp_location.text().strip() or "us-central1"
        if not prompt:
            QMessageBox.information(self, "Thiếu prompt", "Hãy nhập mô tả video TikTok/Facebook cần tạo.")
            return
        if not project:
            QMessageBox.information(self, "Thiếu Google Cloud Project", "Nhập Project ID đã bật Vertex AI.")
            return
        if QMessageBox.question(self, "Tạo video bằng Veo", "Veo là dịch vụ trả phí. Lượt tạo video có thể phát sinh phí Google Cloud. Tiếp tục?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        self.settings.set("marketing_video_prompt", prompt)
        self.settings.set("google_cloud_project", project)
        self.settings.set("google_cloud_location", location)
        aspect, _platform = self.video_platform.currentData()
        duration = int(self.video_duration.currentData())
        model = str(self.video_model.currentData())
        output = Path(__file__).resolve().parents[2] / "data" / "marketing" / f"video_{datetime.now():%Y%m%d_%H%M%S}.mp4"
        self.video_generate.setEnabled(False)
        self.video_status.setText("Đang gửi prompt tới Veo… Quá trình có thể mất vài phút.")
        run_in_background(lambda: self._request_veo_video(project, location, model, prompt, aspect, duration, output), self._video_done, self._video_failed)

    @staticmethod
    def _request_veo_video(project: str, location: str, model: str, prompt: str, aspect: str, duration: int, output: Path) -> Path:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("Thiếu google-genai. Chạy pip install -r requirements.txt trong môi trường .venv.") from exc
        try:
            client = genai.Client(vertexai=True, project=project, location=location)
            operation = client.models.generate_videos(
                model=model,
                source=types.GenerateVideosSource(prompt=prompt),
                config=types.GenerateVideosConfig(aspect_ratio=aspect, duration_seconds=duration),
            )
            while not operation.done:
                import time
                time.sleep(15)
                operation = client.operations.get(operation)
            response = operation.response
            if not response or not response.generated_videos:
                raise RuntimeError("Veo không trả về video. Kiểm tra quyền Vertex AI, vùng và hạn mức dự án.")
            generated = response.generated_videos[0].video
            output.parent.mkdir(parents=True, exist_ok=True)
            client.files.download(file=generated)
            generated.save(str(output))
            if not output.exists() or output.stat().st_size == 0:
                raise RuntimeError("Không tải được video kết quả từ Vertex AI.")
            return output
        except Exception as exc:
            raise RuntimeError(str(exc)) from None

    def _video_done(self, path: Path) -> None:
        self.video_generate.setEnabled(True)
        self.video_result_path = path
        self.video_open.setEnabled(True)
        self.video_status.setText(f"Đã tạo video. Tệp được lưu tại: {path}")

    def _video_failed(self, message: str) -> None:
        self.video_generate.setEnabled(True)
        self.video_status.setText(f"Tạo video thất bại: {message}")

    def _open_generated_video(self) -> None:
        if self.video_result_path and self.video_result_path.exists():
            os.startfile(self.video_result_path)

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video quảng cáo", self.settings.get("marketing_video_dir", ""),
            "Video (*.mp4 *.mov *.m4v *.mkv *.webm *.avi)",
        )
        if not path:
            return
        self.video_path = Path(path)
        self.settings.set("marketing_video_dir", str(self.video_path.parent))
        self.video_label.setText(f"Video: {self.video_path.name}")
        try:
            self.timestamp.setMaximum(max(0.0, self._video_info()["duration"] - .1))
        except Exception as exc:
            QMessageBox.warning(self, "Không đọc được video", str(exc))
            self.video_path = None
            self.video_label.setText("Chưa chọn video")
            return
        if not self.title.text().strip():
            self.title.setText(self.video_path.stem)
        self.qc_result.setText("Đã chọn video. Có thể tạo ảnh bìa hoặc kiểm tra trước khi đăng.")
        self.save_cover.setEnabled(False)

    def _video_info(self) -> dict:
        if not self.video_path:
            raise ValueError("Hãy chọn video trước.")
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise ValueError("Không đọc được video. Thử tệp MP4 hoặc MOV.")
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        cap.release()
        return {"width": width, "height": height, "fps": fps, "duration": frames / fps if fps else 0,
                "size": self.video_path.stat().st_size}

    def _make_cover(self) -> None:
        if not self.video_path:
            QMessageBox.information(self, "Chọn video", "Hãy chọn video trước khi tạo ảnh bìa.")
            return
        headline = self.title.text().strip()
        if not headline:
            QMessageBox.information(self, "Thiếu tiêu đề", "Nhập tiêu đề muốn hiện trên ảnh bìa.")
            return
        cap = cv2.VideoCapture(str(self.video_path))
        cap.set(cv2.CAP_PROP_POS_MSEC, self.timestamp.value() * 1000)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            QMessageBox.warning(self, "Không lấy được khung hình", "Thử chọn thời điểm khác trong video.")
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        source = QImage(rgb.data, rgb.shape[1], rgb.shape[0], int(rgb.strides[0]), QImage.Format.Format_RGB888).copy()
        mode = self.aspect.currentData()
        dimensions = {"vertical": (1080, 1920), "portrait": (1080, 1350), "square": (1080, 1080)}
        width, height = dimensions[mode]
        scaled = source.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        image = scaled.copy((scaled.width() - width) // 2, (scaled.height() - height) // 2, width, height)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        shade = QLinearGradient(0, 0, 0, height)
        shade.setColorAt(0, QColor(15, 14, 22, 40))
        shade.setColorAt(.55, QColor(15, 14, 22, 20))
        shade.setColorAt(1, QColor(15, 14, 22, 215))
        painter.fillRect(0, 0, width, height, shade)
        brand = self.brand.text().strip()[:28]
        if brand:
            painter.setPen(QPen(QColor(255, 255, 255, 90), 2))
            painter.setBrush(QColor(25, 24, 34, 210))
            painter.drawRoundedRect(QRectF(64, 72, 470, 70), 16, 16)
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Segoe UI", 30, QFont.Weight.DemiBold))
            painter.drawText(QRectF(88, 72, 430, 70), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), brand)
        title_font = QFont("Segoe UI", 76 if mode == "vertical" else 64, QFont.Weight.Bold)
        metrics = QFontMetrics(title_font)
        words, lines, line = headline[:140].split(), [], ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if metrics.horizontalAdvance(candidate) > width - 150 and line:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        lines = lines[:4]
        top = int(height * .66)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(164, 133, 255))
        painter.drawRoundedRect(QRectF(62, top - 20, 14, min(height - 55, top + len(lines) * 94) - top + 20), 7, 7)
        painter.setPen(QColor("white"))
        painter.setFont(title_font)
        for index, line in enumerate(lines):
            painter.drawText(105, top + index * 88 + metrics.ascent(), line)
        painter.end()
        self.cover_path = self.video_path.with_name(f"{self.video_path.stem}_cover.png")
        self._cover_image = image.copy()
        self.cover_preview.setPixmap(QPixmap.fromImage(image).scaled(self.cover_preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.save_cover.setEnabled(True)
        self.qc_result.setText(f"Đã tạo ảnh bìa xem trước · {width} × {height} px. Nhấn Lưu ảnh bìa PNG để chọn nơi lưu.")

    def _save_cover(self) -> None:
        if self.cover_path is None or self._cover_image is None:
            return
        default = str(self.cover_path)
        path, _ = QFileDialog.getSaveFileName(self, "Lưu ảnh bìa", default, "PNG image (*.png)")
        if not path:
            return
        self._cover_image.save(path, "PNG")
        self.cover_path = Path(path)
        QMessageBox.information(self, "Đã lưu ảnh bìa", f"Ảnh bìa đã lưu tại:\n{path}")

    def _check_video(self) -> None:
        try:
            info = self._video_info()
        except Exception as exc:
            QMessageBox.information(self, "Chọn video", str(exc))
            return
        platform = self.platform.currentData()
        ratio = info["width"] / info["height"] if info["height"] else 0
        tiktok = platform.startswith("tiktok")
        is_ad = platform == "tiktok_ads"
        if platform == "facebook_feed":
            ratio_ok = .54 <= ratio <= .57 or .98 <= ratio <= 1.02 or 1.88 <= ratio <= 1.94
            ratio_name = "9:16, 1:1 hoặc 1.91:1 cho Feed"
        else:
            ratio_ok = .54 <= ratio <= .57
            ratio_name = "9:16 cho Reels/TikTok"
        dimensions_ok = min(info["width"], info["height"]) >= 540 and max(info["width"], info["height"]) >= 960
        checks = [
            ("Tỷ lệ khung", ratio_ok, f"{ratio:.2f}:1 · mục tiêu: {ratio_name}"),
            ("Độ phân giải", dimensions_ok, f"{info['width']} × {info['height']} px · nên tối thiểu khoảng 540 × 960 cho video dọc"),
            ("Thời lượng", 5 <= info["duration"] <= 600 if is_ad else 0 < info["duration"] <= 600, f"{info['duration']:.1f} giây"),
            ("Dung lượng", info["size"] <= (500 if tiktok else 4096) * 1024 * 1024, f"{info['size'] / 1048576:.1f} MB"),
        ]
        rows = []
        for name, passed, detail in checks:
            color, label = ("#55c99a", "ĐẠT") if passed else ("#f0b45e", "CẦN XEM LẠI")
            rows.append(f'<p><b style="color:{color}">{label}</b> · <b>{name}:</b> {detail}</p>')
        rows.append(f'<p><b>THỦ CÔNG</b> · Nghe thử âm thanh, xem chữ trong vùng an toàn, kiểm tra quyền dùng nhạc/hình và công bố tài trợ.</p>')
        rows.append('<p style="color:#999">Rà soát kỹ thuật sơ bộ; không đảm bảo nền tảng duyệt hoặc phân phối quảng cáo.</p>')
        self.qc_result.setText(f"<b>{self.platform.currentText()}</b> · {info['fps']:.2f} fps<br>" + "".join(rows))
