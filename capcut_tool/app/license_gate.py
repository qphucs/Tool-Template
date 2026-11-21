"""Secure, fail-closed license activation dialog for the desktop app."""
from __future__ import annotations

import json
import hashlib
import os
import platform
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from .common import run_in_background

LOCAL_LICENSE_ENDPOINT = "http://127.0.0.1:3100/api/license/validate"


def device_fingerprint() -> str:
    """Return an app-scoped hash for this Windows installation, never the raw machine ID."""
    machine_id = ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:
            machine_id, _ = winreg.QueryValueEx(key, "MachineGuid")
    except (ImportError, OSError):
        pass
    if not machine_id:
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "CapCutTemplateTool"
        identity_file = root / "device-id"
        try:
            machine_id = identity_file.read_text(encoding="utf-8").strip()
        except OSError:
            machine_id = ""
        if not machine_id:
            machine_id = str(uuid.uuid4())
            root.mkdir(parents=True, exist_ok=True)
            identity_file.write_text(machine_id, encoding="utf-8")
    return hashlib.sha256(f"capcut-tool:{machine_id}".encode("utf-8")).hexdigest()


def _is_allowed_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint)
    if not parsed.netloc or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return True
    # Plain HTTP is allowed only for a loopback development server on this PC.
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}


def validate_license_request(endpoint: str, license_key: str) -> dict:
    if not _is_allowed_endpoint(endpoint):
        return {"ok": False, "message": "Máy chủ cần dùng HTTPS. Khi chạy thử trên máy này, chỉ chấp nhận địa chỉ localhost."}
    if not license_key.strip():
        return {"ok": False, "message": "Vui lòng nhập key bản quyền do admin cấp."}
    request = Request(
        endpoint,
        data=json.dumps({
            "license_key": license_key.strip(),
            "app": "capcut-tool",
            "device_id": device_fingerprint(),
            "device_name": platform.node() or os.environ.get("COMPUTERNAME", "Unknown device"),
            "device_os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        }).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            result = json.loads(response.read(64 * 1024).decode("utf-8"))
        if not isinstance(result, dict):
            return {"ok": False, "message": "Máy chủ trả về dữ liệu không hợp lệ."}
        if result.get("valid") is True:
            return {
                "ok": True,
                "message": str(result.get("message") or "Key hợp lệ.")[:180],
                "plan": str(result.get("plan") or "")[:50],
                "expires_at": str(result.get("expires_at") or "")[:50],
            }
        return {"ok": False, "message": str(result.get("message") or "Key không hợp lệ, đã hết hạn hoặc đã bị thu hồi.")[:180]}
    except HTTPError as exc:
        return {"ok": False, "message": f"Máy chủ từ chối xác thực (HTTP {exc.code})."}
    except (URLError, TimeoutError, OSError):
        return {"ok": False, "message": "Không kết nối được máy chủ. Hãy mở AI Video Studio trước rồi thử lại."}
    except (ValueError, UnicodeError):
        return {"ok": False, "message": "Máy chủ trả về dữ liệu không đọc được."}


class LicenseDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kích hoạt bản quyền")
        self.setModal(True)
        self.setFixedWidth(500)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        configured_endpoint = os.environ.get("CAPCUT_LICENSE_API_URL", "").strip()
        self.endpoint = configured_endpoint or LOCAL_LICENSE_ENDPOINT
        self.license_plan = ""
        self.license_expires_at = ""

        eyebrow = QLabel("AI VIDEO STUDIO  ·  BẢO MẬT TÀI KHOẢN")
        eyebrow.setObjectName("licenseEyebrow")
        title = QLabel("Kích hoạt bản quyền")
        title.setObjectName("licenseTitle")
        explanation = QLabel("Nhập key bản quyền bạn nhận từ quản trị viên để mở công cụ. Key chỉ được gửi đến máy chủ xác thực và không lưu trên máy này.")
        explanation.setObjectName("licenseDescription")
        explanation.setWordWrap(True)

        self.license_key = QLineEdit()
        self.license_key.setObjectName("licenseInput")
        self.license_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.license_key.setPlaceholderText("Dán key bản quyền tại đây")
        self.license_key.setMaxLength(512)
        self.license_key.setMinimumHeight(44)

        self.server_note = QLabel()
        self.server_note.setObjectName("licenseServerNote")
        self.server_note.setWordWrap(True)
        if configured_endpoint:
            self.server_note.setText("Máy chủ xác thực đã được cấu hình. Key sẽ được kiểm tra trực tuyến.")
        else:
            self.server_note.setText("Đang dùng máy chủ cục bộ. Hãy mở “Run AI Video Studio.bat” trước để kết nối dịch vụ xác thực.")

        self.status = QLabel("")
        self.status.setObjectName("licenseStatus")
        self.status.setWordWrap(True)

        self.toggle_visibility = QPushButton("Hiện key")
        self.toggle_visibility.setObjectName("licenseReveal")
        self.toggle_visibility.setCheckable(True)
        self.toggle_visibility.toggled.connect(self._toggle_key_visibility)

        self.activate = QPushButton("Xác thực và mở công cụ")
        self.activate.setObjectName("primary")
        self.activate.setMinimumHeight(40)
        self.cancel = QPushButton("Thoát")
        self.cancel.setMinimumHeight(40)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self.license_key, 1)
        key_row.addWidget(self.toggle_visibility)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.cancel)
        buttons.addWidget(self.activate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(13)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addLayout(key_row)
        layout.addWidget(self.server_note)
        layout.addWidget(self.status)
        layout.addSpacing(3)
        layout.addLayout(buttons)

        self.setStyleSheet("""
            QDialog { background: #171923; color: #f4f5fb; }
            QLabel#licenseEyebrow { color: #a99aff; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }
            QLabel#licenseTitle { color: #ffffff; font-size: 21pt; font-weight: 700; margin-top: 2px; }
            QLabel#licenseDescription { color: #b9bdcb; font-size: 10pt; line-height: 1.4; }
            QLabel#licenseServerNote { color: #c3b7ff; background: #242238; border: 1px solid #393354; border-radius: 9px; padding: 11px 12px; font-size: 9pt; }
            QLabel#licenseStatus { color: #ffcf83; font-size: 9pt; }
            QLineEdit#licenseInput { background: #222530; border: 1px solid #424657; border-radius: 9px; padding: 0 12px; color: #ffffff; selection-background-color: #7058df; }
            QLineEdit#licenseInput:focus { border: 1px solid #9b87ff; }
            QPushButton { background: #292d39; border: 1px solid #414657; border-radius: 8px; padding: 0 15px; color: #e6e8f0; }
            QPushButton:hover { background: #353a49; }
            QPushButton#primary { background: #7058df; border-color: #806be9; color: #ffffff; font-weight: 700; }
            QPushButton#primary:hover { background: #806be9; }
            QPushButton#primary:disabled { background: #48445f; color: #b7b2cb; }
            QPushButton#licenseReveal { padding: 0 12px; color: #c7c2e3; }
        """)

        self.activate.clicked.connect(self._validate)
        self.cancel.clicked.connect(self.reject)
        self.license_key.returnPressed.connect(self._validate)

    def _toggle_key_visibility(self, visible: bool) -> None:
        self.license_key.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self.toggle_visibility.setText("Ẩn key" if visible else "Hiện key")

    def _validate(self) -> None:
        key = self.license_key.text()
        if not key.strip():
            self.status.setText("Vui lòng nhập key bản quyền do admin cấp.")
            self.license_key.setFocus()
            return
        self.activate.setEnabled(False)
        self.cancel.setEnabled(False)
        self.license_key.setEnabled(False)
        self.toggle_visibility.setEnabled(False)
        self.status.setText("Đang xác thực key với máy chủ…")
        run_in_background(lambda submitted=key: validate_license_request(self.endpoint, submitted), self._validated, self._request_failed)
        key = ""

    def _validated(self, result: dict) -> None:
        self.license_key.clear()
        self.license_key.setEnabled(True)
        self.toggle_visibility.setEnabled(True)
        self.cancel.setEnabled(True)
        self.activate.setEnabled(True)
        if result.get("ok"):
            self.license_plan = str(result.get("plan") or "Standard")[:50]
            self.license_expires_at = str(result.get("expires_at") or "")[:50]
            details = result.get("message", "Key hợp lệ.")
            if result.get("plan"):
                details += f" · Gói {result['plan']}"
            if result.get("expires_at"):
                details += f" · Hết hạn: {result['expires_at']}"
            self.status.setText(details)
            self.accept()
        else:
            self.status.setText(result.get("message", "Key không hợp lệ hoặc đã hết hạn."))
            self.license_key.setFocus()

    def _request_failed(self, _message: str) -> None:
        self.license_key.clear()
        self.license_key.setEnabled(True)
        self.toggle_visibility.setEnabled(True)
        self.cancel.setEnabled(True)
        self.activate.setEnabled(True)
        self.status.setText("Không xác thực được. Hãy kiểm tra máy chủ và kết nối mạng rồi thử lại.")
