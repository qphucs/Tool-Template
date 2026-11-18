"""Đọc chữ trong video mẫu bằng EasyOCR (có tiếng Việt), gộp theo thời gian xuất hiện."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from .motion import ShotMotion
from .overlay import to_reference
from .shots import Shot

SAMPLE_FPS = 4          # đọc 4 khung mỗi giây là đủ bắt chữ hiện ít nhất 0,25 giây
OCR_WIDTH = 540
MIN_CONFIDENCE = 0.45
SURE_CONFIDENCE = 0.8   # chữ chỉ thấy ở một lần đọc thì phải chắc chắn mới giữ
# logo CapCut/TikTok hay bị OCR đọc lệch: "ZCapCur", "~Cut", "apCut"…
WATERMARK = re.compile(r"cap\s*c|apc|ca?p?cu[rt]|~\s*cut|tik\s*tok|^id[:\s]", re.IGNORECASE)

_reader = None


def _get_reader():
    global _reader
    if _reader is None:
        import easyocr  # nạp chậm, chỉ khi cần
        _reader = easyocr.Reader(["vi", "en"], gpu=False, verbose=False)
    return _reader


@dataclass
class TextItem:
    text: str
    start: int            # khung
    end: int
    box: tuple[float, float, float, float]  # x, y, w, h theo tỉ lệ khung hình
    color: tuple[int, int, int]             # màu chữ RGB ước lượng
    height_ratio: float   # chiều cao chữ / chiều cao khung, để ước cỡ chữ
    confidence: float = 0.0
    reads: int = 1        # số lần đọc thấy
    centers: list = field(default_factory=list, repr=False)  # (khung, x, y) tâm chữ mỗi lần đọc


def _text_color(frame: np.ndarray, box) -> tuple[int, int, int]:
    x0, y0, x1, y1 = box
    crop = frame[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
    if len(crop) < 4:
        return (255, 255, 255)
    gray = crop.mean(axis=1)
    # chữ thường là nhóm điểm sáng nhất hoặc tối nhất; lấy nhóm khác nền nhiều hơn
    bright, dark = crop[gray > np.percentile(gray, 80)], crop[gray < np.percentile(gray, 20)]
    pick = bright if abs(bright.mean() - crop.mean()) >= abs(dark.mean() - crop.mean()) else dark
    b, g, r = pick.mean(axis=0)
    return int(r), int(g), int(b)


def _key(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def _attached_to_photo(t: TextItem, shot: Shot, motion: ShotMotion) -> bool:
    """Chữ có sẵn trong ảnh (biển số, bảng hiệu) chuyển động cùng ảnh: trên màn hình nó di chuyển,
    nhưng đưa về khung tham chiếu thì đứng yên. Chữ chèn thêm thì ngược lại."""
    if len(t.centers) < 2:
        return False
    screen = np.array([(x, y) for _, x, y in t.centers])
    mapped = []
    for i, x, y in t.centers:
        m = to_reference(motion, min(max(i - shot.start, 0), len(motion.raw["scale"]) - 1), 1, 1)
        mapped.append(m @ np.array([x, y, 1.0]))
    spread = lambda pts: float(np.ptp(np.asarray(pts), axis=0).max())
    return spread(screen) > 0.015 and spread(mapped) < spread(screen) / 2


def read_texts(frames: list[np.ndarray], fps: float, full_frames=None,
               shot_motions: list[tuple[Shot, ShotMotion]] = ()) -> list[TextItem]:
    """frames: khung đã thu nhỏ; full_frames: hàm lấy khung gốc theo chỉ số (đọc chữ nét hơn) nếu có.
    shot_motions: cảnh và chuyển động của nó, để bỏ chữ có sẵn trong ảnh, chỉ giữ chữ được chèn thêm."""
    reader = _get_reader()
    get = full_frames or (lambda i: frames[i])
    step = max(int(round(fps / SAMPLE_FPS)), 1)
    found: list[TextItem] = []
    for i in range(0, len(frames), step):
        frame = get(i)
        if frame is None:
            continue
        if frame.shape[1] > OCR_WIDTH:  # đọc trên khung 540px: nhanh hơn nhiều mà chữ vẫn rõ
            frame = cv2.resize(frame, (OCR_WIDTH, round(frame.shape[0] * OCR_WIDTH / frame.shape[1])),
                               interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        for points, text, conf in reader.readtext(frame):
            text = text.strip()
            if conf < MIN_CONFIDENCE or len(text) < 2 or WATERMARK.search(text):
                continue
            if len(text) <= 5 and not re.search(r"[^\W\d_]", text):
                continue  # mảnh số/ký hiệu ngắn (biển số, số nhà) gần như luôn là chi tiết trong ảnh
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            box = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
            rel = (box[0] / w, box[1] / h, (box[2] - box[0]) / w, (box[3] - box[1]) / h)
            center = (i, rel[0] + rel[2] / 2, rel[1] + rel[3] / 2)
            same = next((t for t in found if _key(t.text) == _key(text) and i - t.end <= step
                         and abs(t.box[0] - rel[0]) < 0.15 and abs(t.box[1] - rel[1]) < 0.15), None)
            if same:
                same.end = i + step
                same.reads += 1
                same.confidence = max(same.confidence, float(conf))
                same.centers.append(center)
            else:
                found.append(TextItem(text, i, i + step, rel, _text_color(frame, box), rel[3],
                                      float(conf), centers=[center]))
    kept = []
    for t in found:
        t.end = min(t.end, len(frames))
        owner = next(((s, m) for s, m in shot_motions if s.start <= t.start < s.end), None)
        if owner and _attached_to_photo(t, *owner):
            continue
        if t.reads >= 2 or t.confidence >= SURE_CONFIDENCE:
            kept.append(t)
    return kept


def frame_reader(path):
    """Hàm đọc khung gốc theo chỉ số, để OCR trên ảnh nét thay vì ảnh đã thu nhỏ."""
    cap = cv2.VideoCapture(str(path))

    def get(i: int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        return frame if ok else None

    return get
