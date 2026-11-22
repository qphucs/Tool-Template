"""Cửa sổ chính của app: các tab Học mẫu, Tạo mẫu, Đăng, Marketing."""
from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget

from .common import Settings
from .generate_tab import GenerateTab
from .license_gate import LicenseDialog
from .learn_tab import LearnTab
from .marketing_tab import MarketingTab
from .publish_tab import PublishTab

STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 10pt; color: #e6e6e6; background: #1e1f22; }
QTabWidget::pane { border: 1px solid #3a3b3f; border-radius: 6px; top: -1px; }
QTabBar::tab { background: #2b2d31; padding: 8px 22px; border: 1px solid #3a3b3f; border-bottom: none;
               border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
QTabBar::tab:selected { background: #1e1f22; color: #ffffff; font-weight: 600; }
QLineEdit, QPlainTextEdit, QComboBox, QListWidget, QTableWidget {
    background: #2b2d31; border: 1px solid #3a3b3f; border-radius: 5px; padding: 4px;
    selection-background-color: #3d6fd6; }
QHeaderView::section { background: #2b2d31; border: none; border-bottom: 1px solid #3a3b3f; padding: 5px; }
QTableWidget { gridline-color: #34363b; }
QPushButton { background: #34363b; border: 1px solid #45474d; border-radius: 5px; padding: 6px 14px; }
QPushButton:hover { background: #3e4046; }
QPushButton:disabled { color: #808080; }
QPushButton#primary { background: #3d6fd6; border-color: #4a7ce0; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #4a7ce0; }
QLabel#muted { color: #9a9ca3; }
QStatusBar { background: #18191c; color: #b8b9c0; border-top: 1px solid #34363b; }
QStatusBar::item { border: none; }
QSplitter::handle { background: #1e1f22; width: 8px; height: 8px; }
QGroupBox { border: 1px solid #3a3b3f; border-radius: 6px; margin-top: 10px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; font-weight: 600; }
"""


class MainWindow(QMainWindow):
    def __init__(self, license_info: dict | None = None):
        super().__init__()
        self.setWindowTitle("CapCut Template Tool")
        self.resize(1180, 760)
        settings = Settings()
        self.learn_tab = LearnTab(settings)
        self.generate_tab = GenerateTab(settings)
        self.publish_tab = PublishTab()
        self.marketing_tab = MarketingTab(settings)

        tabs = QTabWidget()
        tabs.addTab(self.learn_tab, "1. Học mẫu")
        tabs.addTab(self.generate_tab, "2. Tạo mẫu")
        tabs.addTab(self.publish_tab, "3. Đăng")
        tabs.addTab(self.marketing_tab, "4. Marketing FB / TikTok")
        tabs.setCurrentWidget(self.marketing_tab)
        self.setCentralWidget(tabs)

        license_info = license_info or {}
        plan = str(license_info.get("plan") or "Standard")
        expiry = str(license_info.get("expires_at") or "")
        if expiry:
            try:
                expiry_date = datetime.fromisoformat(expiry.replace("Z", "+00:00")).strftime("%d/%m/%Y")
            except ValueError:
                expiry_date = expiry[:10]
            expiry_text = f"Hết hạn: {expiry_date}"
        else:
            expiry_text = "Không thời hạn"
        self.statusBar().showMessage(f"Bản quyền: Gói {plan}  ·  {expiry_text}  ·  Đã kích hoạt trên 1 thiết bị")

        self.learn_tab.formulas_changed.connect(self.generate_tab.reload_formulas)
        self.generate_tab.drafts_created.connect(self.publish_tab.reload)
        self.generate_tab.drafts_created.connect(self.learn_tab.reload)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    license_dialog = LicenseDialog()
    if license_dialog.exec() != LicenseDialog.DialogCode.Accepted:
        return 0
    window = MainWindow({"plan": license_dialog.license_plan,
                         "expires_at": license_dialog.license_expires_at})
    window.show()
    return app.exec()
