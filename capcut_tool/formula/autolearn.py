"""Tự học hàng loạt: chọn project theo prompt rồi học tất cả.

Prompt có thể là câu tự nhiên, ví dụ:

    project dưới 15 giây, tên có remix
    học các mẫu couple tone neon
    "couple" dưới 20 giây

Có cấu hình AI thì AI đọc tên/độ dài project để chọn; không có AI thì dùng
bộ lọc từ khóa và độ dài. Project đã học được bỏ qua để không học lại.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..ai.client import AIConfig, AIUnavailable, chat_json
from ..capcut.drafts import DraftInfo
from .learn import learn, save

STOPWORDS = {
    "project", "projects", "mau", "mẫu", "video", "videos", "nhac", "nhạc", "anh", "ảnh",
    "clip", "cac", "các", "nhung", "những", "cua", "của", "co", "có", "va", "và",
    "hoac", "hoặc", "duoi", "dưới", "tren", "trên", "giay", "giây", "ngan", "ngắn",
    "dai", "dài", "hon", "hơn", "ten", "tên", "chua", "chứa", "hoc", "học", "tu", "tự",
    "dong", "động", "loai", "loại", "bo", "bỏ", "giu", "giữ", "chi", "chỉ", "lay", "lấy",
    "tat", "tất", "ca", "cả", "trong", "ngoai", "ngoài", "da", "đã", "la", "là",
    "mot", "một", "giup", "giúp", "muon", "muốn", "het", "hết", "toan", "toàn",
    "bo", "bộ", "nay", "này", "do", "đó", "kia", "nào", "nao", "theo", "voi", "với",
    "cung", "cùng", "khi", "thi", "thì", "cho", "được", "duoc", "mới", "moi",
    "tạo", "tao", "làm", "lam", "ra", "nhiều", "nhieu", "kiểu", "kieu", "phong",
    "cách", "cach", "thể", "the", "hãy", "hay", "giùm", "dum", "giúp", "giup",
    "đến", "den", "tới", "toi", "quá", "qua",
}

AI_SYSTEM = """Bạn giúp chọn project CapCut để học thành công thức mẫu.
Người dùng mô tả bằng tiếng Việt. Bạn nhận được danh sách project kèm độ dài.
Hãy chọn các project phù hợp nhất với yêu cầu; nếu yêu cầu không nói rõ thì
chọn tất cả. Chỉ trả về JSON đúng dạng {"indices": [0, 2, 5]}."""


@dataclass
class BatchLearnResult:
    learned: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    selected: int = 0


def parse_filters(prompt: str) -> dict:
    """Tách độ dài và từ khóa từ prompt tiếng Việt."""
    text = (prompt or "").lower().replace(",", ".")
    max_s = min_s = None

    match = re.search(r"(?:dưới|ngắn hơn|ít hơn|tối đa|không quá|<=?)\s*(\d+(?:\.\d+)?)\s*(?:giây|s\b)", text)
    if match:
        max_s = float(match.group(1))
    match = re.search(r"(?:trên|dài hơn|nhiều hơn|tối thiểu|>=?)\s*(\d+(?:\.\d+)?)\s*(?:giây|s\b)", text)
    if match:
        min_s = float(match.group(1))
    match = re.search(r"(?:từ)\s*(\d+(?:\.\d+)?)\s*(?:đến|tới|-)\s*(\d+(?:\.\d+)?)\s*(?:giây|s\b)", text)
    if match:
        min_s, max_s = sorted((float(match.group(1)), float(match.group(2))))

    quoted: list[str] = []
    for match in re.finditer(r'"([^"]+)"|\'([^\']+)\'', prompt):
        value = (match.group(1) or match.group(2) or "").strip().lower()
        if value:
            quoted.append(value)
    words = [w for w in re.findall(r"[0-9a-zA-ZÀ-ỹ]+", prompt.lower())
             if len(w) >= 3 and not re.fullmatch(r"\d+(?:\.\d+)?s?", w)
             and w not in STOPWORDS]
    keywords = quoted or words
    return {"max_s": max_s, "min_s": min_s, "keywords": keywords, "quoted": quoted}


def select_drafts(drafts: list[DraftInfo], prompt: str,
                  config: AIConfig | None = None,
                  already_ids: set[str] | None = None,
                  use_ai: bool = True,
                  learning_instruction: str = "") -> tuple[list[DraftInfo], str]:
    """Chọn project cần học. Trả về (danh sách, ghi chú để hiện cho người dùng)."""
    already_ids = already_ids or set()
    pool = [d for d in drafts if d.id not in already_ids]
    if not pool:
        return [], "Không còn project nào chưa học."
    if not (prompt or "").strip():
        return pool, f"Sẽ học tất cả {len(pool)} project đang hiện."

    filters = parse_filters(prompt)
    by_duration = [
        d for d in pool
        if (filters["min_s"] is None or d.duration_s >= filters["min_s"])
        and (filters["max_s"] is None or d.duration_s <= filters["max_s"])
    ]
    by_keyword = [
        d for d in by_duration
        if not filters["keywords"]
        or any(word in d.name.lower() for word in filters["keywords"])
    ]

    resolved = config.resolve() if (config and use_ai) else None
    if resolved is not None:
        try:
            selected = _ai_select(by_duration, prompt, resolved, learning_instruction)
            if selected:
                return selected, (
                    f"AI chọn {len(selected)}/{len(pool)} project theo prompt. "
                    f"Trong đó {len(by_keyword)} project khớp từ khóa.")
            note = "AI không chọn project nào"
        except AIUnavailable as exc:
            note = f"AI lỗi: {exc}"
        except Exception as exc:
            note = f"AI trả dữ liệu lạ: {exc}"
        return by_keyword, f"{note} — dùng bộ lọc từ khóa: {len(by_keyword)}/{len(pool)} project."

    return by_keyword, f"Bộ lọc từ khóa chọn {len(by_keyword)}/{len(pool)} project."


def _ai_select(candidates: list[DraftInfo], prompt: str, config: AIConfig,
               learning_instruction: str = "") -> list[DraftInfo]:
    if not candidates:
        return []
    lines = [f"{i}. {d.name} — {d.duration_s:.1f}s" for i, d in enumerate(candidates)]
    text = "\n".join([
        f"Yêu cầu: {prompt}",
        f"Danh sách {len(candidates)} project:",
        *lines,
        'Chọn các project phù hợp và trả về JSON {"indices": [...]}.',
    ])
    system = AI_SYSTEM
    if learning_instruction.strip():
        system += "\n\nHƯỚNG DẪN HỌC RIÊNG CỦA NGƯỜI DÙNG:\n" + learning_instruction.strip()[:4000]
    data = chat_json(system, text, config=config)
    raw = data.get("indices", data.get("projects", []))
    chosen: list[DraftInfo] = []
    for value in raw if isinstance(raw, list) else []:
        try:
            index = int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(candidates) and candidates[index] not in chosen:
            chosen.append(candidates[index])
    return chosen


def learn_batch(drafts: list[DraftInfo], progress=None) -> BatchLearnResult:
    """Học từng project, ghi công thức, gom lỗi lại."""
    result = BatchLearnResult(selected=len(drafts))
    for i, draft in enumerate(drafts, 1):
        try:
            formula = learn(draft)
            save(formula)
            result.learned.append(
                f"{draft.name} · {formula['music']['tempo']:.0f} BPM · "
                f"{len(formula['slots'])} ô thay")
        except Exception as exc:
            result.failed.append(f"{draft.name}: {exc}")
        if progress is not None:
            progress(i, len(drafts), draft.name)
    return result
