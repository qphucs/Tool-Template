"""Kho hiệu ứng: gom hiệu ứng, transition, chế độ hòa trộn, animation và mẫu chữ từ mọi project CapCut của bạn.

Mỗi mục giữ nguyên JSON gốc của CapCut (để dựng project mới đúng cấu trúc) kèm nhãn *kiểu* hiệu ứng,
dùng để chọn hiệu ứng thay cho kiểu mà bước phân tích video nhận ra.

    python -m capcut_tool.library.effects     # xây lại kho và in tóm tắt
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path

from ..capcut.drafts import list_drafts

LIBRARY_PATH = Path(__file__).resolve().parents[2] / "data" / "effect_library.json"

# nhãn kiểu hiệu ứng theo từ khoá trong tên (tên tiếng Anh hoặc tiếng Việt của CapCut)
TAGS = {
    "blur": r"blur|mờ|nhoè|nhòe|defocus",
    "shake": r"shak|lắc|rung|jitter|vibrat|earthquake|tremor",
    "rgb_split": r"chromatic|rgb|glitch|signal|tách màu|color split|aberration",
    "flash": r"flash|shine|sáng|\blight|strobe|nháy",
    "dark_flash": r"black|dark|fade|tối|shadow",
    "pixelate": r"pixel|mosaic|vỡ|block",
    "zoom_pulse": r"zoom|pulse|phóng|bounce|nhún",
    "color_shift": r"color|hue|màu|tint|rainbow|chrome",
    "particles": r"particle|sparkle|star|dust|hạt|lấp lánh|bling",
}
# kiểu transition mà bước phân tích nhận ra -> từ khoá tên transition CapCut
TRANSITION_TAGS = {
    "mix": r"^mix$|dissolve|fade|hòa|blend",
    "blur": r"blur|mờ|shine",
    "flash": r"flash|shine|sáng",
    "zoom": r"zoom|phóng|pull|push",
    "slide": r"slide|trượt|swipe|switch|wipe",
    "shake": r"shake|lắc|rung",
}
# chế độ hòa trộn cho lớp phủ: tên CapCut theo thứ tự ưu tiên
BLENDS = {
    "screen": ["Screen", "Lọc màu", "Color dodge", "Brighten", "Lighten"],
    "multiply": ["Multiply", "Nhân", "Darken", "Color burn"],
    "normal": ["Normal", "Overlay"],
}


def _tags(name: str, table: dict[str, str]) -> list[str]:
    low = name.lower()
    return [tag for tag, pattern in table.items() if re.search(pattern, low)]


def _cached(m: dict) -> bool:
    path = m.get("path") or ""
    return bool(path) and os.path.exists(path)


def build_library() -> dict:
    lib: dict = {"video_effects": {}, "transitions": {}, "mix_modes": {}, "animations": {},
                 "text_samples": [], "built_from": 0}
    usage: Counter = Counter()
    for d in list_drafts():
        try:
            c = json.loads(d.content_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lib["built_from"] += 1
        mats = c["materials"]
        index = {m["id"]: (cat, m) for cat, items in mats.items() if isinstance(items, list)
                 for m in items if isinstance(m, dict) and "id" in m}

        for m in mats.get("video_effects", []):
            _add(lib["video_effects"], m, _tags(m.get("name", ""), TAGS), usage, "video_effects")
        for m in mats.get("transitions", []):
            _add(lib["transitions"], m, _tags(m.get("name", ""), TRANSITION_TAGS), usage, "transitions")
        for m in mats.get("effects", []):
            if m.get("type") == "mix_mode":
                _add(lib["mix_modes"], m, [], usage, "mix_modes", key=m.get("name"))
        for m in mats.get("material_animations", []):
            for a in m.get("animations", []):
                _add(lib["animations"], a, _tags(a.get("name", ""), TAGS), usage, "animations")

        # mẫu chữ: lấy vài đoạn chữ đơn giản kèm các vật liệu nó tham chiếu, để dựng chữ mới cùng cấu trúc
        if len(lib["text_samples"]) < 5:
            for track in c["tracks"]:
                if track["type"] != "text":
                    continue
                for seg in track["segments"][:1]:
                    cat, mat = index.get(seg["material_id"], ("", {}))
                    if cat == "texts" and mat.get("content", "").startswith("{"):
                        refs = {r: index[r] for r in seg.get("extra_material_refs", []) if r in index}
                        lib["text_samples"].append({"segment": seg, "material": mat,
                                                    "refs": [{"category": rc, "material": rm} for rc, rm in refs.values()],
                                                    "draft": d.name})
                        break
    for group in ("video_effects", "transitions", "mix_modes", "animations"):
        for key, entry in lib[group].items():
            entry["uses"] = usage[(group, key)]
    return lib


def _add(table: dict, m: dict, tags: list[str], usage: Counter, group: str, key: str | None = None) -> None:
    key = key or m.get("resource_id") or m.get("effect_id") or m.get("id")
    if not key:
        return
    usage[(group, key)] += 1
    current = table.get(key)
    # giữ bản có file trong cache nếu có, để CapCut không phải tải lại
    if current is None or (not current["cached"] and _cached(m)):
        table[key] = {"name": m.get("name", ""), "tags": tags, "cached": _cached(m), "raw": m}


def save(lib: dict) -> Path:
    LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_PATH.write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    return LIBRARY_PATH


def load() -> dict:
    if not LIBRARY_PATH.exists():
        lib = build_library()
        save(lib)
        return lib
    return json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))


def choose(lib: dict, group: str, tag: str) -> dict | None:
    """Hiệu ứng phù hợp nhất cho một kiểu: đúng nhãn, ưu tiên còn file trong cache, rồi dùng nhiều nhất."""
    candidates = [e for e in lib[group].values() if tag in e["tags"]]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (e["cached"], e.get("uses", 0), len(e["tags"]) == 1))


def choose_blend(lib: dict, blend: str) -> dict | None:
    for name in BLENDS.get(blend, []):
        if name in lib["mix_modes"]:
            return lib["mix_modes"][name]
    return None


if __name__ == "__main__":
    lib = build_library()
    path = save(lib)
    print(f"Đã quét {lib['built_from']} project -> {path}")
    for group in ("video_effects", "transitions", "mix_modes", "animations"):
        items = lib[group].values()
        print(f"\n{group}: {len(lib[group])} mục, {sum(e['cached'] for e in items)} còn file")
        for e in sorted(items, key=lambda e: -e.get("uses", 0))[:40]:
            print(f"   {'✓' if e['cached'] else '·'} {e['name']:28} {','.join(e['tags']) or '-':24} dùng {e.get('uses', 0)}")
    print(f"\nmẫu chữ: {len(lib['text_samples'])}")
    for tag in TAGS:
        pick = choose(lib, "video_effects", tag)
        print(f"   {tag:12} -> {pick['name'] if pick else 'KHÔNG CÓ'}")
    for tag in TRANSITION_TAGS:
        pick = choose(lib, "transitions", tag)
        print(f"   transition {tag:6} -> {pick['name'] if pick else 'KHÔNG CÓ'}")
