"""Tạo mẫu mới từ công thức.

    python -m capcut_tool.generate_cli <công thức> <file nhạc> <thư mục nguyên liệu> <tên project> [--dry-run]

--dry-run: chỉ tính toán và in kết quả, không ghi gì vào CapCut.
"""
from __future__ import annotations

import sys

from .formula.learn import formula_path, load
from .generate.build import build_content, generate, make_caption
from .generate.writer import CapCutRunningError


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv if a != "--dry-run"]
    if len(args) != 4:
        print(__doc__)
        return 1
    formula_name, music, materials, name = args
    formula = load(formula_path(formula_name))
    try:
        if dry:
            result = build_content(formula, music, materials)
            folder, caption = None, make_caption(formula, result)
        else:
            folder, result, caption = generate(formula, music, materials, name)
    except (ValueError, CapCutRunningError) as e:
        print(f"Lỗi: {e}")
        return 1
    print(f"Nhạc mới: {result.tempo:.1f} BPM, dùng từ giây {result.music_start_s:.2f}, mẫu dài {result.duration_s:.2f}s")
    for p in result.materials:
        print(f"  ô thay <- {p.name}")
    print(f"Tiêu đề ({caption.source}{': ' + caption.note if caption.note else ''}): {caption.title}")
    print(f"Mô tả: {caption.description}")
    print(f"Hashtag: {' '.join(caption.hashtags)}")
    print(f"Đã tạo project: {folder}" if folder else "Chạy thử, chưa ghi gì vào CapCut.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
