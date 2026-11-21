"""Question-driven content drafting with explicit administrator approval."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget,
)

from ..ai.client import AIConfig, chat_json
from .common import Settings, run_in_background


class ContentWorkflowTab(QWidget):
    """Drafts text with Ollama, sends it for review, and gates media prompts."""

    def __init__(self, settings: Settings, apply_callback, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.apply_callback = apply_callback
        self.pending_code = str(settings.get("approval_pending_code", "") or "")
        self.waiting_for_review = bool(self.pending_code)
        self.poll_running = False
        approved = settings.get("marketing_approved_content", {}) or {}
        self.approved_content = approved if isinstance(approved, dict) else {}
        self.media_approved = bool(settings.get("marketing_media_approved", False) and self.approved_content)

        self.product = QLineEdit()
        self.product.setPlaceholderText("Sản phẩm/dịch vụ và điểm nổi bật")
        self.audience = QLineEdit()
        self.audience.setPlaceholderText("Khách hàng mục tiêu")
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("Mục tiêu: tăng đơn, nhận diện, kéo inbox…")
        self.offer = QLineEdit()
        self.offer.setPlaceholderText("Ưu đãi/giá/CTA, có thể để trống")
        self.platform = QComboBox()
        self.platform.addItems(["TikTok", "Facebook", "TikTok + Facebook"])
        self.tone = QComboBox()
        self.tone.addItems(["Tự nhiên, thuyết phục", "Hài hước", "Cao cấp", "Thân thiện", "Chuyên gia"])
        self.model = QLineEdit(str(settings.get("content_ollama_model", "qwen2.5") or "qwen2.5"))
        self.base = QLineEdit(str(settings.get("content_ollama_url", "http://localhost:11434") or "http://localhost:11434"))
        form = QFormLayout()
        form.addRow("Sản phẩm/dịch vụ", self.product)
        form.addRow("Khách hàng", self.audience)
        form.addRow("Mục tiêu", self.goal)
        form.addRow("Ưu đãi / lời kêu gọi", self.offer)
        form.addRow("Nền tảng", self.platform)
        form.addRow("Giọng điệu", self.tone)
        form.addRow("Model Ollama miễn phí", self.model)
        form.addRow("Địa chỉ Ollama", self.base)

        self.generate = QPushButton("Soạn nội dung bằng AI miễn phí")
        self.generate.setObjectName("primary")
        self.draft = QPlainTextEdit()
        self.draft.setPlaceholderText("AI sẽ tạo caption, hashtag, prompt ảnh và prompt video riêng tại đây.")
        self.draft.setMinimumHeight(220)
        self.draft.setReadOnly(True)
        saved_content = settings.get("marketing_content_draft", {}) or {}
        self.content = saved_content if isinstance(saved_content, dict) else {}
        if self.content:
            self.draft.setPlainText(self._format_content(self.content))
        self.send = QPushButton("Gửi admin duyệt")
        self.send.setEnabled(bool(self.content))
        self.channel = QComboBox()
        self.channel.addItem("Telegram Bot", "telegram")
        self.channel.addItem("Zalo OA qua webhook", "zalo")
        self.bot_token = QLineEdit(os.environ.get("APPROVAL_TELEGRAM_BOT_TOKEN", ""))
        self.bot_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.telegram_chat = QLineEdit(str(settings.get("approval_telegram_chat", "") or ""))
        self.telegram_admin = QLineEdit(str(settings.get("approval_telegram_admin", "") or ""))
        self.zalo_url = QLineEdit(str(settings.get("approval_zalo_webhook", "") or ""))
        self.zalo_url.setPlaceholderText("HTTPS webhook do bạn cấu hình để chuyển yêu cầu sang Zalo OA")
        self.zalo_secret = QLineEdit(os.environ.get("APPROVAL_ZALO_WEBHOOK_SECRET", ""))
        self.zalo_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.zalo_recipient = QLineEdit(str(settings.get("approval_zalo_recipient", "") or ""))
        self.approval_code = QLineEdit()
        self.approval_code.setPlaceholderText("Telegram: duyệt bằng /approve MÃ trong chat admin. Zalo: nhập mã admin gửi lại.")
        self.approve_zalo = QPushButton("Xác nhận mã duyệt Zalo")
        self.approve_zalo.setEnabled(False)
        self.apply = QPushButton("Áp dụng prompt đã duyệt vào tạo ảnh/video")
        self.apply.setEnabled(self.media_approved)
        self.status = QLabel("Chưa soạn nội dung. AI chạy local bằng Ollama, không cần API key; cần cài Ollama và tải model trước.")
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")

        approval_form = QFormLayout()
        self.approval_form = approval_form
        approval_form.addRow("Kênh duyệt", self.channel)
        approval_form.addRow("Telegram bot token", self.bot_token)
        approval_form.addRow("Telegram chat ID admin", self.telegram_chat)
        approval_form.addRow("Telegram user ID được duyệt", self.telegram_admin)
        approval_form.addRow("Zalo webhook HTTPS", self.zalo_url)
        approval_form.addRow("Zalo webhook secret (nếu có)", self.zalo_secret)
        approval_form.addRow("Zalo người nhận/đích (tùy webhook)", self.zalo_recipient)
        approval_form.addRow("Mã duyệt", self.approval_code)
        buttons = QHBoxLayout()
        buttons.addWidget(self.send)
        buttons.addWidget(self.approve_zalo)
        buttons.addWidget(self.apply)
        content_page = QWidget()
        layout = QVBoxLayout(content_page)
        layout.addLayout(form)
        layout.addWidget(self.generate)
        layout.addWidget(QLabel("<b>Bản nháp và prompt media (chưa chạy tạo ảnh/video)</b>"))
        layout.addWidget(self.draft, 1)
        layout.addLayout(approval_form)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content_page)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

        self.generate.clicked.connect(self._generate)
        self.send.clicked.connect(self._send_for_approval)
        self.approve_zalo.clicked.connect(self._approve_zalo_code)
        self.apply.clicked.connect(self._apply_approved)
        self.channel.currentIndexChanged.connect(self._channel_changed)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._poll_telegram)
        self.timer.start()
        self._channel_changed()
        if self.waiting_for_review:
            saved_channel = str(settings.get("approval_pending_channel", "telegram") or "telegram")
            channel_index = self.channel.findData(saved_channel)
            if channel_index >= 0:
                self.channel.setCurrentIndex(channel_index)
            self.status.setText(f"Đang chờ admin duyệt mã {self.pending_code}. Giữ app mở để nhận phản hồi Telegram.")
            self.approve_zalo.setEnabled(saved_channel == "zalo")
        elif self.media_approved:
            self.content = self.approved_content
            self.send.setEnabled(True)
            self.apply.setEnabled(True)
            self.draft.setPlainText(self._format_content(self.approved_content))
            self.status.setText("Nội dung đã được admin duyệt trước đó. Chỉ prompt đã duyệt mới được phép tạo media.")

    def _generate(self) -> None:
        answers = {"product": self.product.text().strip(), "audience": self.audience.text().strip(),
                   "goal": self.goal.text().strip(), "offer": self.offer.text().strip(),
                   "platform": self.platform.currentText(), "tone": self.tone.currentText()}
        if not answers["product"] or not answers["audience"] or not answers["goal"]:
            QMessageBox.information(self, "Thiếu thông tin", "Điền sản phẩm, khách hàng và mục tiêu; AI sẽ tự soạn phần còn lại.")
            return
        model, base = self.model.text().strip(), self.base.text().strip().rstrip("/")
        if not model or not base:
            QMessageBox.information(self, "Thiếu Ollama", "Nhập model và địa chỉ Ollama local.")
            return
        self.settings.set("content_ollama_model", model)
        self.settings.set("content_ollama_url", base)
        self.generate.setEnabled(False)
        self.status.setText("Đang soạn nội dung bằng model local…")
        run_in_background(lambda: self._draft_with_ollama(answers, model, base), self._draft_done, self._draft_failed)

    @staticmethod
    def _draft_with_ollama(answers: dict, model: str, base: str) -> dict:
        config = AIConfig(provider="ollama", model=model, base_url=base)
        system = ("Bạn là chuyên gia marketing mạng xã hội Việt Nam. Tạo nội dung rõ ràng, không bịa giá/khuyến mãi. "
                  "Chỉ trả JSON hợp lệ với các khóa caption, hashtags (mảng), image_prompt, video_prompt, "
                  "video_hook, shot_list (mảng), cta. Prompt ảnh/video độc lập; TikTok ưu tiên khung dọc 9:16, "
                  "Facebook Feed/video ưu tiên khung ngang 16:9 "
                  "theo nền tảng; không tự tạo ảnh/video và không xuất bản bài.")
        prompt = ("Dựa trên thông tin sau, hãy tạo một gói nội dung hoàn chỉnh cho đăng mạng xã hội. "
                  "Caption tự nhiên, không cam kết quá mức; prompt ảnh và video tách biệt, mô tả cụ thể để đem sang công cụ tạo media.\n" +
                  json.dumps(answers, ensure_ascii=False))
        return chat_json(system, prompt, config=config, timeout=180)

    def _draft_done(self, result: dict) -> None:
        self.generate.setEnabled(True)
        self.content = result
        self.settings.set("marketing_content_draft", result)
        self.media_approved = False
        self.approved_content = {}
        self.settings.set("marketing_media_approved", False)
        self.settings.set("marketing_approved_content", {})
        self.draft.setPlainText(self._format_content(result))
        self.send.setEnabled(True)
        self.apply.setEnabled(False)
        self.status.setText("Đã soạn xong. Chưa có media nào được tạo; gửi admin duyệt trước khi áp dụng prompt.")

    def _draft_failed(self, message: str) -> None:
        self.generate.setEnabled(True)
        self.status.setText(f"Không gọi được Ollama: {message}. Kiểm tra Ollama đang chạy và đã tải model, ví dụ `ollama pull qwen2.5`.")

    @staticmethod
    def _format_content(data: dict) -> str:
        hashtags = data.get("hashtags", [])
        shots = data.get("shot_list", [])
        if not isinstance(hashtags, list):
            hashtags = [hashtags] if hashtags else []
        if not isinstance(shots, list):
            shots = [shots] if shots else []
        return (f"CAPTION\n{data.get('caption', '')}\n\nHASHTAG\n{' '.join(map(str, hashtags))}\n\n"
                f"HOOK VIDEO\n{data.get('video_hook', '')}\n\nPROMPT ẢNH\n{data.get('image_prompt', '')}\n\n"
                f"PROMPT VIDEO\n{data.get('video_prompt', '')}\n\nSHOT LIST\n" +
                "\n".join(f"• {x}" for x in shots) + f"\n\nCTA\n{data.get('cta', '')}")

    def _save_settings(self) -> None:
        for key, field in (("approval_telegram_chat", self.telegram_chat),
                           ("approval_telegram_admin", self.telegram_admin), ("approval_zalo_webhook", self.zalo_url),
                           ("approval_zalo_recipient", self.zalo_recipient)):
            self.settings.set(key, field.text().strip())

    def _send_for_approval(self) -> None:
        if not hasattr(self, "content"):
            return
        self._save_settings()
        channel = self.channel.currentData()
        code = uuid.uuid4().hex[:8].upper()
        text = (f"YÊU CẦU DUYỆT NỘI DUNG · MÃ {code}\n\n{self.draft.toPlainText()[:3000]}\n\n"
                f"Telegram: /approve {code} hoặc /reject {code} (chỉ user ID admin đã cấu hình).\n"
                "Chưa có ảnh/video nào được tạo. Chỉ sau khi duyệt mới mở prompt media trong app.")
        if channel == "telegram":
            token, chat, admin = self.bot_token.text().strip(), self.telegram_chat.text().strip(), self.telegram_admin.text().strip()
            if not token or not chat or not admin:
                QMessageBox.information(self, "Thiếu cấu hình", "Telegram cần bot token, chat ID admin và Telegram user ID được phép duyệt.")
                return
            send_fn = lambda: self._telegram_send(token, chat, text)
        else:
            url, recipient = self.zalo_url.text().strip(), self.zalo_recipient.text().strip()
            if not url.startswith("https://"):
                QMessageBox.information(self, "Thiếu webhook Zalo", "Nhập URL HTTPS webhook Zalo OA/automation của bạn.")
                return
            payload = {"event": "content_approval_request", "code": code, "recipient": recipient,
                       "content": self.content, "approval_instructions": f"Trả lại mã {code} cho người vận hành để nhập vào app."}
            send_fn = lambda: self._webhook_send(url, payload, self.zalo_secret.text().strip())
        self.send.setEnabled(False)
        self.status.setText("Đang gửi yêu cầu duyệt…")
        self.pending_code = code
        self.waiting_for_review = False
        self.media_approved = False
        self.approved_content = {}
        self.settings.set("marketing_media_approved", False)
        self.settings.set("marketing_approved_content", {})
        self.approve_zalo.setEnabled(False)
        run_in_background(send_fn, lambda _r: self._approval_sent(channel), self._send_failed)

    @staticmethod
    def _telegram_send(token: str, chat: str, text: str):
        return ContentWorkflowTab._post_json(f"https://api.telegram.org/bot{token}/sendMessage", {"chat_id": chat, "text": text})

    @staticmethod
    def _webhook_send(url: str, payload: dict, secret: str):
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return ContentWorkflowTab._post_json(url, payload, headers)

    @staticmethod
    def _post_json(url: str, data: dict, headers: dict | None = None):
        request = urllib.request.Request(url, data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                result = json.loads(response.read(1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read(4096).decode('utf-8', errors='replace')}") from None
        if isinstance(result, dict) and result.get("ok") is False:
            raise RuntimeError(str(result.get("description") or "Dịch vụ từ chối yêu cầu"))
        return result

    def _approval_sent(self, channel: str) -> None:
        self.waiting_for_review = True
        self.status.setText(f"Đã gửi mã duyệt {self.pending_code}. Telegram: admin trả lời /approve {self.pending_code}; Zalo: nhập đúng mã admin đã gửi lại.")
        self.approve_zalo.setEnabled(channel == "zalo")
        self.settings.set("approval_pending_code", self.pending_code)
        self.settings.set("approval_pending_channel", channel)

    def _send_failed(self, message: str) -> None:
        self.send.setEnabled(True)
        self.status.setText(f"Gửi yêu cầu duyệt thất bại: {message}")

    def _channel_changed(self, *_args) -> None:
        telegram = self.channel.currentData() == "telegram"
        for widget in (self.bot_token, self.telegram_chat, self.telegram_admin):
            self.approval_form.setRowVisible(widget, telegram)
        for widget in (self.zalo_url, self.zalo_secret, self.zalo_recipient):
            self.approval_form.setRowVisible(widget, not telegram)
        self.approve_zalo.setVisible(not telegram)
        self.approval_form.setRowVisible(self.approval_code, not telegram)

    def _approve_zalo_code(self) -> None:
        code = self.approval_code.text().strip().upper()
        if not self.waiting_for_review or code != self.pending_code:
            QMessageBox.warning(self, "Mã không đúng", "Chỉ nhập mã duyệt do admin gửi lại qua Zalo.")
            return
        self._mark_approved("Zalo")

    def _poll_telegram(self) -> None:
        if not self.waiting_for_review or self.channel.currentData() != "telegram" or self.poll_running:
            return
        token, admin = self.bot_token.text().strip(), self.telegram_admin.text().strip()
        if not token or not admin:
            return
        self.poll_running = True
        offset = int(self.settings.get("approval_telegram_offset", 0) or 0)
        run_in_background(lambda: self._telegram_updates(token, offset), self._updates_received, self._updates_failed)

    @staticmethod
    def _telegram_updates(token: str, offset: int):
        query = urllib.parse.urlencode({"offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message"])})
        url = f"https://api.telegram.org/bot{token}/getUpdates?{query}"
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read(1024 * 1024).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Telegram getUpdates HTTP {exc.code}") from None

    def _updates_received(self, response: dict) -> None:
        self.poll_running = False
        for update in response.get("result", []) if response.get("ok") else []:
            self.settings.set("approval_telegram_offset", int(update.get("update_id", 0)) + 1)
            message = update.get("message", {})
            if str(message.get("from", {}).get("id", "")) != self.telegram_admin.text().strip():
                continue
            command = str(message.get("text", "")).strip().split()
            if len(command) != 2 or command[1].upper() != self.pending_code:
                continue
            if command[0] == "/approve":
                self._mark_approved("Telegram")
            elif command[0] == "/reject":
                self.waiting_for_review = False
                self.settings.set("approval_pending_code", "")
                self.settings.set("approval_pending_channel", "")
                self.apply.setEnabled(False)
                self.send.setEnabled(True)
                self.status.setText("Admin đã từ chối nội dung. Sửa brief rồi gửi duyệt lại nếu cần.")

    def _updates_failed(self, _message: str) -> None:
        self.poll_running = False

    def _mark_approved(self, channel: str) -> None:
        self.waiting_for_review = False
        self.media_approved = True
        self.approved_content = dict(self.content)
        self.settings.set("marketing_media_approved", True)
        self.settings.set("marketing_approved_content", self.approved_content)
        self.settings.set("approval_pending_code", "")
        self.settings.set("approval_pending_channel", "")
        self.approval_code.clear()
        self.approve_zalo.setEnabled(False)
        self.apply.setEnabled(True)
        self.status.setText(f"Admin đã duyệt qua {channel}. Bấm áp dụng để chuyển prompt; app chưa tự tạo hay đăng media.")

    def _apply_approved(self) -> None:
        if not self.apply.isEnabled() or not self.media_approved:
            return
        self.apply_callback(self.approved_content)
        self.status.setText("Đã áp dụng prompt đã duyệt. Chọn tỷ lệ ngang 16:9 hoặc dọc 9:16 trong tab tạo media rồi mới bấm tạo.")
