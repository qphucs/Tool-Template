"""Xem nhanh project CapCut từ dòng lệnh.

    python -m capcut_tool.inspect_draft            # liệt kê project
    python -m capcut_tool.inspect_draft "mẫu"      # xem timeline của một project
"""
from __future__ import annotations

import sys

from .capcut.drafts import US, list_drafts
from .capcut.timeline import load_timeline


def _s(us: int) -> str:
    return f"{us / US:.3f}"


def main(argv: list[str]) -> int:
    drafts = list_drafts()
    if not argv:
        for d in drafts:
            print(f"{d.modified:%Y-%m-%d %H:%M}  {d.duration_s:8.1f}s  {d.name}")
        print(f"\n{len(drafts)} project")
        return 0

    match = [d for d in drafts if d.name == argv[0]]
    if not match:
        print(f"Không tìm thấy project {argv[0]!r}")
        return 1
    tl = load_timeline(match[0].folder)
    print(f"{match[0].name}: {tl.duration_s:.2f}s, {tl.width}x{tl.height}, {tl.fps:g} fps")
    for t in tl.tracks:
        print(f"\n[track {t.index}] {t.type} ({len(t.segments)} đoạn)")
        for s in t.segments:
            refs = ", ".join(f"{r.category}:{r.name}" for r in s.refs)
            kf = ", ".join(f"{k.property}x{len(k.offsets)}" for k in s.keyframes)
            slot = " [Ô THAY]" if s.is_slot else ""
            print(f"  {_s(s.start):>7} +{_s(s.duration):<6} {s.material_type}:{s.material_name[:30]}{slot}"
                  + (f" | {refs}" if refs else "") + (f" | kf {kf}" if kf else ""))
    music = tl.music
    print(f"\nNhạc nền: {music.material_name if music else 'không có'}")
    print(f"Ô thay đoán được: {len(tl.slots)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
