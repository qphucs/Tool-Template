"""Viết tiêu đề, mô tả, hashtag cho mẫu CapCut.

Dùng Claude API khi có thông tin đăng nhập (biến ANTHROPIC_API_KEY hoặc `ant auth login`);
nếu không có hoặc gọi lỗi thì dùng câu mẫu dự phòng trong templates.py.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic

from . import templates

MODEL = os.environ.get("CAPTION_MODEL", "claude-opus-5-5")

SYSTEM = """Bạn viết tiêu đề và hashtag cho mẫu (template) CapCut đăng lên kho mẫu của CapCut tại Việt Nam.
Người xem lướt nhanh, nên tiêu đề phải ngắn, bắt trend, dễ hiểu ngay đây là mẫu gì và hợp với ai.
Viết bằng tiếng Việt có dấu, có thể xen từ tiếng Anh phổ biến trong cộng đồng edit (edit, trend, beat, glitch…).
Không bịa tên bài hát hay ca sĩ nếu thông tin không có. Không dùng từ ngữ phản cảm hay hứa hẹn sai sự thật."""

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Tiêu đề tối đa 40 ký tự"},
        "description": {"type": "string", "description": "Mô tả 1-2 câu, tối đa 150 ký tự"},
        "hashtags": {"type": "array", "items": {"type": "string"},
                     "description": "5-8 hashtag, mỗi cái bắt đầu bằng #, không dấu cách"},
    },
    "required": ["title", "description", "hashtags"],
    "additionalProperties": False,
}


@dataclass
class TemplateInfo:
    """Thông tin về mẫu mới, dùng làm ngữ cảnh khi viết tiêu đề."""
    formula: str
    music_name: str
    tempo: float
    duration_s: float
    slot_count: int
    effects: list[str] = field(default_factory=list)
    style_hint: str = ""   # gợi ý phong cách của bạn, ví dụ "ảnh couple, tone neon"


@dataclass
class Caption:
    title: str
    description: str
    hashtags: list[str]
    source: str            # "claude" hoặc "mẫu dự phòng"
    note: str = ""         # lý do dùng dự phòng, nếu có

    def to_dict(self) -> dict:
        return asdict(self)


def effects_summary(content: dict, limit: int = 8) -> list[str]:
    """Các hiệu ứng, transition, animation dùng nhiều nhất trong project, để mô tả phong cách."""
    names = Counter()
    for category in ("video_effects", "transitions", "effects"):
        for m in content["materials"].get(category, []):
            if m.get("name"):
                names[m["name"]] += 1
    return [n for n, _ in names.most_common(limit)]


def _prompt(info: TemplateInfo) -> str:
    lines = [
        f"Mẫu dài {info.duration_s:.1f} giây, nhịp {info.tempo:.0f} BPM, giật theo beat nhạc.",
        f"Số ô cho người dùng thay ảnh/video: {info.slot_count}.",
        f"Tên file nhạc: {info.music_name}",
    ]
    if info.effects:
        lines.append("Hiệu ứng chính: " + ", ".join(info.effects))
    if info.style_hint:
        lines.append(f"Phong cách: {info.style_hint}")
    lines.append("Hãy viết tiêu đề, mô tả và hashtag cho mẫu này.")
    return "\n".join(lines)


def _normalize(data: dict) -> tuple[str, str, list[str]]:
    tags = []
    for t in data["hashtags"]:
        t = "#" + t.strip().lstrip("#").replace(" ", "")
        if len(t) > 1 and t not in tags:
            tags.append(t)
    return data["title"].strip()[:60], data["description"].strip()[:200], tags[:8]


class MissingCredentials(RuntimeError):
    pass


def write_with_claude(info: TemplateInfo) -> Caption:
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": _prompt(info)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            # nếu bộ lọc an toàn từ chối, API tự chạy lại trên model dự phòng do Anthropic chọn
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except TypeError as e:
        # SDK báo TypeError khi không tìm thấy key hay hồ sơ đăng nhập nào
        if "authentication method" in str(e):
            raise MissingCredentials("Chưa có Claude API key") from e
        raise
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude từ chối yêu cầu")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Câu trả lời bị cắt ngang")
    text = next(b.text for b in response.content if b.type == "text")
    title, description, hashtags = _normalize(json.loads(text))
    return Caption(title, description, hashtags, "claude")


def write_caption(info: TemplateInfo) -> Caption:
    try:
        return write_with_claude(info)
    except MissingCredentials as e:
        note = str(e)
    except anthropic.AuthenticationError:
        note = "API key không hợp lệ"
    except anthropic.RateLimitError:
        note = "Claude API đang quá tải hoặc hết hạn mức"
    except anthropic.APIConnectionError:
        note = "Không kết nối được Claude API"
    except anthropic.APIStatusError as e:
        note = f"Claude API lỗi {e.status_code}"
    except anthropic.AnthropicError as e:
        note = f"Lỗi Claude API: {e}"
    except (RuntimeError, ValueError, KeyError) as e:
        note = str(e)
    caption = templates.fallback_caption(info)
    caption.note = note
    return caption


def save_caption(caption: Caption, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(caption.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
