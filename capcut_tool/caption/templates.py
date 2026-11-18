"""Câu mẫu dự phòng khi không gọi được Claude API. Bạn có thể sửa hoặc thêm câu tùy ý."""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .writer import Caption, TemplateInfo

TITLES = [
    "Giật beat cực cuốn {slots} ảnh",
    "Mẫu edit giật nhạc {seconds}s",
    "Trend giật beat hot nhất",
    "Edit ảnh theo nhạc siêu mượt",
    "Beat sync {slots} ảnh cực chất",
    "Mẫu giật beat cho ảnh đẹp",
]

DESCRIPTIONS = [
    "Chỉ cần thay {slots} ảnh là có ngay video giật theo nhạc cực cuốn.",
    "Mẫu {seconds} giây giật đúng nhịp, thay ảnh của bạn và đăng ngay.",
    "Hiệu ứng khớp beat, chuyển cảnh mượt, hợp đăng TikTok và Reels.",
]

BASE_TAGS = ["#capcut", "#maucapcut", "#capcuttemplate", "#trend", "#edit"]
STYLE_TAGS = ["#giatbeat", "#beatsync", "#xuhuong", "#editanh", "#trending", "#fyp"]


def fallback_caption(info: "TemplateInfo", rng: random.Random | None = None) -> "Caption":
    from .writer import Caption

    rng = rng or random.Random()
    values = {"slots": info.slot_count, "seconds": round(info.duration_s)}
    title = rng.choice(TITLES).format(**values)
    description = rng.choice(DESCRIPTIONS).format(**values)
    hashtags = BASE_TAGS[:3] + rng.sample(STYLE_TAGS, 4)
    return Caption(title, description, hashtags, "mẫu dự phòng")
