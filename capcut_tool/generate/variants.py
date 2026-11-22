"""Prompt -> nhiều biến thể mẫu khác nhau.

Một kế hoạch biến thể gồm phong cách, tiêu đề/mô tả/hashtag, nhạc được chọn,
seed chọn ảnh và các thay đổi an toàn trên công thức:

- ``beat_offset``: cắt bớt vài beat ở đầu để mẫu dồn và ngắn hơn.
- ``slot_ratio``: giữ lại một phần ô thay, tạo bố cục khác với bản gốc.

Phần này dùng AI khi có cấu hình; không có thì tự lập kế hoạch offline theo
bộ phong cách có sẵn, nên app luôn tạo được mẫu.
"""
from __future__ import annotations

import copy
import random
import re
import zlib
from dataclasses import dataclass, field

from ..ai.client import AIConfig, AIUnavailable, chat_json
from ..caption import templates
from ..caption.writer import Caption, TemplateInfo
from ..formula.learn import media_segments
from .build import build_content, generate_with_caption, template_info


@dataclass
class VariantPlan:
    """Một mẫu sẽ được tạo từ prompt."""

    index: int
    style: str
    title: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    music_index: int = 0
    seed: int = 1
    beat_offset: int = 0
    slot_ratio: float = 1.0
    source: str = "offline"


@dataclass
class BatchResult:
    """Kết quả cả batch để giao diện in ra nhật ký."""

    lines: list[str]
    created: int
    total: int
    plans: list[VariantPlan]


# Phong cách dự phòng khi không có AI. Từ khóa trong prompt sẽ được ưu tiên.
STYLE_PRESETS: list[tuple[str, str]] = [
    ("Tối giản", "tối giản, ít hiệu ứng, cắt đúng beat, tone màu nhẹ"),
    ("Neon", "neon rực rỡ, nháy sáng, tương phản mạnh"),
    ("Retro", "retro 8x, hạt phim, màu ấm, chữ cổ điển"),
    ("Couple", "ảnh couple, tone lãng mạn, chuyển cảnh mềm"),
    ("Dark", "tone tối, đen trắng hoặc xanh lạnh, rung nhẹ"),
    ("Trend", "bắt trend TikTok, nhịp nhanh, chữ to giữa khung"),
    ("Clean", "sạch sẽ, nền sáng, ít hiệu ứng, dễ đọc"),
    ("Cinematic", "điện ảnh, chuyển cảnh mượt, màu điện ảnh"),
    ("Anime", "anime/manga, màu pastel, hiệu ứng lấp lánh"),
    ("Street", "đường phố, tương phản cao, nhịp mạnh"),
]

SEED_OFFSETS = (0, 0, 1, 0, 2)
SEED_RATIOS = (1.0, 1.0, 0.8, 0.9, 0.7)

AI_SYSTEM = """Bạn là đạo diễn nội dung cho kho mẫu CapCut tại Việt Nam.
Nhiệm vụ: chia một yêu cầu thành nhiều biến thể mẫu khác nhau, mỗi biến thể có
phong cách, tiêu đề và hashtag riêng để người dùng có nhiều lựa chọn đăng bài.

Quy tắc:
- Trả về đúng số biến thể được yêu cầu, không trùng tiêu đề, phong cách đa dạng.
- Tiêu đề tối đa 40 ký tự, mô tả 1-2 câu tối đa 150 ký tự.
- 5-8 hashtag, mỗi cái bắt đầu bằng #, không dấu cách.
- Viết tiếng Việt có dấu, được xen từ tiếng Anh phổ biến (edit, trend, beat...).
- Không bịa tên bài hát/ca sĩ, không hứa hẹn sai sự thật.
- beat_offset là số nguyên 0..3: số beat cắt bớt ở đầu (0 = giữ nguyên).
- slot_ratio từ 0.6 đến 1.0: tỉ lệ ô thay ảnh được giữ lại.
- seed là số nguyên dương, khác nhau để chọn ảnh/ngẫu nhiên khác nhau.

Chỉ trả về JSON đúng dạng:
{"variants": [{"style": "...", "title": "...", "description": "...",
"hashtags": ["#..."], "beat_offset": 0, "slot_ratio": 1.0, "seed": 123}]}"""


def plan_variants(formula: dict, prompt: str, count: int, music_count: int = 1,
                  settings=None, config: AIConfig | None = None) -> tuple[list[VariantPlan], str]:
    """Lập kế hoạch ``count`` biến thể. Trả về (danh sách, ghi chú cho nhật ký)."""
    count = max(1, min(30, int(count)))
    prompt = (prompt or "").strip()
    resolved = (config or AIConfig.load(settings)).resolve()
    if resolved is None:
        return _offline_plans(prompt, count, music_count), \
               "Chưa cấu hình AI — dùng kế hoạch offline theo bộ phong cách có sẵn."

    try:
        data = chat_json(AI_SYSTEM, _ai_prompt(formula, prompt, count, music_count),
                         config=resolved)
        raw = data.get("variants", data.get("items", []))
        plans = _normalize_plans(raw, count, music_count, source="AI prompt")
        if not plans:
            raise AIUnavailable("AI không trả về biến thể nào")
        return plans, f"AI đã lập {len(plans)} biến thể."
    except AIUnavailable as exc:
        return _offline_plans(prompt, count, music_count), \
               f"AI không dùng được ({exc}) — chuyển sang kế hoạch offline."
    except Exception as exc:  # AI trả dữ liệu lạ vẫn không được làm hỏng batch
        return _offline_plans(prompt, count, music_count), \
               f"Lỗi AI ({exc}) — chuyển sang kế hoạch offline."


def _ai_prompt(formula: dict, prompt: str, count: int, music_count: int) -> str:
    tempo = formula.get("music", {}).get("tempo", 0) or 0
    beats = formula.get("end_beat", 0) - formula.get("start_beat", 0)
    seconds = beats * 60 / tempo if tempo else 0
    names = [s.get("name", "?") for s in media_segments(formula)]
    lines = [
        f"Tạo {count} biến thể mẫu CapCut.",
        f"Khung mẫu: {formula.get('name', '?')} · {len(formula.get('slots', []))} ô thay "
        f"· khoảng {seconds:.1f} giây · {tempo:.0f} BPM.",
        f"Các đoạn ảnh/clip gốc: {', '.join(names[:12]) or 'không rõ'}.",
        f"Số bài nhạc có thể dùng: {max(1, music_count)}.",
    ]
    if prompt:
        lines.append(f"Yêu cầu của người dùng: {prompt}")
    else:
        lines.append("Người dùng không nêu yêu cầu riêng; hãy chọn các phong cách đang hợp trend.")
    lines.append(f"Hãy trả về đúng {count} biến thể trong JSON.")
    return "\n".join(lines)


def _normalize_plans(raw, count: int, music_count: int, source: str) -> list[VariantPlan]:
    if isinstance(raw, dict):
        raw = raw.get("variants", raw.get("items", []))
    if not isinstance(raw, list):
        return []

    plans: list[VariantPlan] = []
    for i, item in enumerate(raw[:count]):
        if not isinstance(item, dict):
            continue
        style = str(item.get("style") or item.get("name") or "").strip()
        if not style:
            style = STYLE_PRESETS[i % len(STYLE_PRESETS)][0]
        title = str(item.get("title") or "").strip()[:60]
        description = str(item.get("description") or "").strip()[:200]
        hashtags = _clean_tags(item.get("hashtags"))
        try:
            beat_offset = int(round(float(item.get("beat_offset", 0))))
        except (TypeError, ValueError):
            beat_offset = 0
        try:
            slot_ratio = float(item.get("slot_ratio", 1.0))
        except (TypeError, ValueError):
            slot_ratio = 1.0
        try:
            seed = int(item.get("seed", 0))
        except (TypeError, ValueError):
            seed = 0
        plans.append(VariantPlan(
            index=i,
            style=style[:80],
            title=title,
            description=description,
            hashtags=hashtags,
            music_index=i % max(1, music_count),
            seed=seed or (1009 * (i + 1)),
            beat_offset=max(0, min(3, beat_offset)),
            slot_ratio=max(0.6, min(1.0, slot_ratio)),
            source=source,
        ))

    # AI trả thiếu thì bù bằng phong cách offline, không để thiếu mẫu.
    if len(plans) < count:
        plans.extend(_offline_plans("", count - len(plans), music_count,
                                    start=len(plans), source="offline bù"))
    return plans[:count]


def _offline_plans(prompt: str, count: int, music_count: int,
                   start: int = 0, source: str = "offline") -> list[VariantPlan]:
    words = set(_words(prompt))
    ranked = sorted(
        STYLE_PRESETS,
        key=lambda preset: -len(words & set(_words(preset[0] + " " + preset[1]))),
    )
    base = zlib.crc32(prompt.encode("utf-8")) or 1
    plans: list[VariantPlan] = []
    for n in range(count):
        i = start + n
        style, description = ranked[i % len(ranked)]
        plans.append(VariantPlan(
            index=i,
            style=style,
            title="",
            description="",
            hashtags=[],
            music_index=i % max(1, music_count),
            seed=(base * 7919 + i * 104729) & 0x7FFFFFFF,
            beat_offset=SEED_OFFSETS[i % len(SEED_OFFSETS)],
            slot_ratio=SEED_RATIOS[i % len(SEED_RATIOS)],
            source=source,
        ))
    return plans


def apply_plan(formula: dict, plan: VariantPlan, vary: bool = True,
               allow_slot_variation: bool = True) -> dict:
    """Áp thay đổi an toàn của kế hoạch lên bản sao công thức."""
    varied = copy.deepcopy(formula)
    if not vary:
        return varied

    offset = max(0, min(4, int(plan.beat_offset or 0)))
    if offset:
        start = float(varied.get("start_beat", 0))
        end = float(varied.get("end_beat", 0))
        if start + offset < end - 0.5:
            varied["start_beat"] = round(start + offset, 4)

    slots = list(varied.get("slots") or [])
    ratio = max(0.6, min(1.0, float(plan.slot_ratio or 1.0)))
    if allow_slot_variation and ratio < 0.999 and len(slots) > 1:
        keep = max(1, min(len(slots), round(len(slots) * ratio)))
        chosen = set(random.Random(plan.seed).sample(slots, keep))
        varied["slots"] = [sid for sid in slots if sid in chosen]
        for segment in varied.get("segments", []):
            segment["is_slot"] = segment.get("id") in chosen
    return varied


def caption_for(plan: VariantPlan, info: TemplateInfo) -> Caption:
    """Tạo caption từ kế hoạch; thiếu dữ liệu thì dùng câu mẫu dự phòng."""
    values = {
        "slots": info.slot_count,
        "seconds": round(info.duration_s),
        "tempo": round(info.tempo),
        "formula": info.formula,
    }
    title = _fill(plan.title, values)[:60].strip()
    if not title:
        caption = templates.fallback_caption(info, random.Random(plan.seed))
        caption.note = caption.note or "prompt không có tiêu đề"
        return caption

    description = _fill(plan.description, values)[:200].strip()
    if not description:
        description = random.Random(plan.seed).choice(templates.DESCRIPTIONS).format(**values)
    hashtags = _clean_tags(plan.hashtags)
    if len(hashtags) < 3:
        hashtags = _clean_tags(list(hashtags) + templates.BASE_TAGS[:3] + templates.STYLE_TAGS[:4])
    return Caption(title, description, hashtags[:8],
                   "AI prompt" if plan.source == "AI prompt" else "prompt offline")


def rotate_materials(materials, index: int):
    """Xoay danh sách ảnh/clip để mỗi biến thể dùng thứ tự khác nhau."""
    if not isinstance(materials, list) or len(materials) <= 1:
        return materials
    shift = index % len(materials)
    return materials[shift:] + materials[:shift]


def run_batch(formula: dict, plans: list[VariantPlan], musics: list,
              materials, *, dry: bool, stamp: str, ordered: bool,
              vary: bool = True, dynamic: bool = False, plan_for=None) -> BatchResult:
    """Tạo toàn bộ biến thể, gom lỗi từng mẫu để không dừng cả batch."""
    lines: list[str] = []
    created = 0

    for plan in plans:
        label = f"{plan.index + 1}/{len(plans)} · {plan.style}"
        try:
            varied = apply_plan(formula, plan, vary=vary, allow_slot_variation=not ordered)
            music = musics[plan.music_index % len(musics)] if musics else None
            mats = rotate_materials(materials, plan.index) if ordered else materials
            name = _variant_name(formula.get("name", "Mẫu"), plan, stamp)
            changes = []
            if varied.get("start_beat") != formula.get("start_beat"):
                changes.append(f"cắt {round(float(varied['start_beat']) - float(formula['start_beat'])):g} beat đầu")
            if len(varied.get("slots", [])) != len(formula.get("slots", [])):
                changes.append(f"giữ {len(varied['slots'])}/{len(formula['slots'])} ô thay")

            beat_plan = plan_for(music) if plan_for else None
            if dry:
                result = build_content(varied, music, mats, seed=plan.seed,
                                       beat_plan=beat_plan, dynamic=dynamic)
                info = template_info(varied, result, plan.style)
                caption = caption_for(plan, info)
                where = "chưa ghi"
            else:
                folder, result, caption = generate_with_caption(
                    varied, music, mats, name,
                    caption_factory=lambda info, p=plan: caption_for(p, info),
                    seed=plan.seed, style_hint=plan.style,
                    beat_plan=beat_plan, dynamic=dynamic,
                )
                where = f"đã tạo project {folder.name}"
                created += 1

            cut = (f", cắt {result.truncated_s:.1f}s cuối"
                   if result.truncated_s > 0.05 else "")
            extra = f" · {', '.join(changes)}" if changes else ""
            if result.summary:
                extra += f"\n   ghép: {result.summary}"
            lines.append(
                f"✓ {label}: {result.tempo:.0f} BPM, {result.duration_s:.1f}s, "
                f"{len(result.slots)} ô thay, {where}{cut}{extra}\n"
                f"   tiêu đề: {caption.title}\n"
                f"   hashtag: {' '.join(caption.hashtags)}")
        except Exception as exc:
            lines.append(f"✗ {label}: {exc}")

    return BatchResult(lines, created, len(plans), plans)


# ---------------------------------------------------------------- helpers
def _variant_name(formula_name: str, plan: VariantPlan, stamp: str) -> str:
    raw = f"{formula_name} - {plan.style} {plan.index + 1:02d} {stamp}"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", raw)
    safe = re.sub(r"\s+", " ", safe).strip().rstrip(".")
    return (safe or f"Mẫu {plan.index + 1:02d} {stamp}")[:90]


def _words(text: str) -> list[str]:
    return re.findall(r"[0-9a-zA-ZÀ-ỹ]+", (text or "").lower())


def _fill(text: str, values: dict) -> str:
    if not text:
        return ""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), text)


def _clean_tags(tags) -> list[str]:
    if not isinstance(tags, (list, tuple)):
        tags = re.split(r"[\s,]+", str(tags or ""))
    out: list[str] = []
    for tag in tags:
        tag = "#" + str(tag).strip().lstrip("#").replace(" ", "")
        if len(tag) > 1 and tag not in out:
            out.append(tag)
    return out[:8]
