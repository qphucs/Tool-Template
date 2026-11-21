"""Local cover artwork and social-video technical checks."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cv2
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen


def cover(video: Path, output: Path, seconds: float, title: str, brand: str, aspect: str):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("OpenCV could not open this video. Try an MP4 or MOV file.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    duration = frames / fps if fps > 0 else 0
    seconds = max(0, min(float(seconds), max(0, duration - 0.05)))
    cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise ValueError("Could not extract a frame at that timestamp.")
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    target = (1080, 1920) if aspect == "vertical" else (1080, 1350) if aspect == "portrait" else (1080, 1080)
    tw, th = target
    image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], int(rgb.strides[0]), QImage.Format.Format_RGB888).copy()
    scaled = image.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    left, top = (scaled.width() - tw) // 2, (scaled.height() - th) // 2
    image = scaled.copy(left, top, tw, th)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    gradient = QLinearGradient(0, 0, 0, th)
    gradient.setColorAt(0, QColor(12, 10, 23, 48))
    gradient.setColorAt(.48, QColor(12, 10, 23, 20))
    gradient.setColorAt(1, QColor(12, 10, 23, 205))
    painter.fillRect(0, 0, tw, th, gradient)
    if brand:
        brand = brand[:28]
        brand_font = QFont("Segoe UI", 28, QFont.Weight.DemiBold)
        painter.setFont(brand_font)
        brand_width = min(500, max(180, QFontMetrics(brand_font).horizontalAdvance(brand) + 46))
        painter.setPen(QPen(QColor(255, 255, 255, 75), 2))
        painter.setBrush(QColor(26, 24, 36, 205))
        painter.drawRoundedRect(QRectF(74, 84, brand_width, 58), 18, 18)
        painter.setPen(QColor(255, 255, 255, 245))
        painter.drawText(QRectF(96, 84, brand_width - 35, 58), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), brand)
    words = title.strip()[:140].split()
    lines, line = [], ""
    title_font = QFont("Segoe UI", max(48, int(tw * .074)), QFont.Weight.Bold)
    metrics = QFontMetrics(title_font)
    for word in words:
        candidate = f"{line} {word}".strip()
        if metrics.horizontalAdvance(candidate) > tw - 148 and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    lines = lines[:4]
    text_top = int(th * .66)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(166, 135, 255, 255))
    painter.drawRoundedRect(QRectF(65, text_top - 34, 13, min(th - 65, text_top + len(lines) * 88) - (text_top - 34)), 6, 6)
    painter.setFont(title_font)
    painter.setPen(QColor(255, 255, 255, 235))
    for i, text in enumerate(lines):
        painter.drawText(105, text_top + i * 83 + metrics.ascent(), text)
    painter.end()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output), "PNG", -1):
        raise ValueError("Could not save the cover PNG.")
    del app
    return {"width": tw, "height": th, "timestamp_s": round(seconds, 2), "file": output.name}


def check(video: Path, platform: str):
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError("Không đọc được thông tin video; hãy xuất lại dưới dạng MP4 hoặc MOV.")
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps, frames = cap.get(cv2.CAP_PROP_FPS), cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    duration = frames / fps if fps > 0 else 0
    ratio = width / height if height else 0
    size = video.stat().st_size
    is_tiktok = platform.startswith("tiktok")
    is_ads = platform.endswith("ads")
    is_vertical = .54 <= ratio <= .57
    aspect_ok = is_vertical if platform != "facebook_feed" else (.54 <= ratio <= .57 or .98 <= ratio <= 1.02 or 1.88 <= ratio <= 1.94)
    dimensions_ok = min(width, height) >= 540 and max(width, height) >= 960
    checks = [
        {"name": "Tỷ lệ khung hình", "status": "pass" if aspect_ok else "warn", "detail": f"{width} × {height} ({ratio:.2f}:1)" if height else "Không đọc được kích thước", "action": "Reels/TikTok: ưu tiên 9:16. Facebook Feed: cân nhắc 1:1, 4:5 hoặc 1.91:1."},
        {"name": "Độ phân giải", "status": "pass" if dimensions_ok else "warn", "detail": f"{width} × {height} px; nên đạt ít nhất khoảng 540 × 960 cho video dọc", "action": "Dùng video có cạnh ngắn từ 540 px và cạnh dài từ 960 px trở lên."},
        {"name": "Thời lượng", "status": "pass" if duration >= (5 if is_tiktok and is_ads else 1) and duration <= 600 else "warn", "detail": f"{duration:.1f} giây" if duration else "Không đọc được thời lượng", "action": "Quảng cáo TikTok cần tối thiểu 5 giây; hãy kiểm tra giới hạn hiện hành của đúng vị trí đăng."},
        {"name": "Dung lượng tệp", "status": "pass" if size <= (500 if is_tiktok else 4096) * 1024 * 1024 else "warn", "detail": f"{size / 1024 / 1024:.1f} MB", "action": "Nén video hoặc giảm bitrate nếu tệp vượt giới hạn tải lên."},
        {"name": "Âm thanh", "status": "manual", "detail": "Chưa kiểm tra track âm thanh bằng bộ giải mã audio.", "action": "Phát thử video, kiểm tra tiếng/nhạc và quyền sử dụng âm thanh."},
        {"name": "Vùng an toàn và nội dung quảng cáo", "status": "manual", "detail": "Cần xem trước chữ, logo, phụ đề và nhãn quảng cáo trên giao diện nền tảng.", "action": "Tránh đặt chữ quan trọng sát mép; xác nhận quyền hình ảnh, nhạc và công bố tài trợ."},
    ]
    return {"platform": platform, "width": width, "height": height, "duration_s": round(duration, 2), "fps": round(fps, 2), "size_bytes": size, "checks": checks, "note": "Đây là rà soát kỹ thuật sơ bộ, không đảm bảo nền tảng sẽ duyệt hoặc phân phối quảng cáo."}

if __name__ == "__main__":
    try:
        payload = json.loads(sys.stdin.read())
        result = cover(Path(payload["video"]), Path(payload["output"]), payload.get("seconds", 0), payload.get("title", ""), payload.get("brand", ""), payload.get("aspect", "vertical")) if payload["action"] == "cover" else check(Path(payload["video"]), payload.get("platform", "facebook_reels"))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        sys.exit(1)
