"""Dựng project CapCut từ video mẫu đã phân tích và ảnh của bạn.

    python -m capcut_tool.rebuild.run <thư mục phân tích hoặc video mẫu> <ảnh 1> <ảnh 2> ... [--name TÊN] [--dry-run]

Ảnh xếp theo thứ tự cảnh. Thư mục phân tích nằm trong data/analysis/; nếu đưa video thì tool phân tích trước.
--dry-run: dựng và kiểm tra trong bộ nhớ, không ghi vào CapCut.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..generate.writer import CapCutRunningError, write_draft
from ..library import effects as library
from .builder import build


def validate(content: dict) -> list[str]:
    """Kiểm tra cấu trúc trước khi ghi: tham chiếu tồn tại, thời gian hợp lệ, track không chồng đoạn."""
    ids = {m["id"] for items in content["materials"].values() if isinstance(items, list)
           for m in items if isinstance(m, dict) and "id" in m}
    problems = []
    for t in content["tracks"]:
        prev_end = -1
        for s in sorted(t["segments"], key=lambda s: s["target_timerange"]["start"]):
            r = s["target_timerange"]
            if s["material_id"] not in ids:
                problems.append(f"track {t['type']}: đoạn {s['id'][:8]} thiếu vật liệu chính")
            missing = [x for x in s.get("extra_material_refs", []) if x not in ids]
            if missing:
                problems.append(f"track {t['type']}: đoạn {s['id'][:8]} thiếu {len(missing)} phụ liệu")
            if r["duration"] <= 0:
                problems.append(f"track {t['type']}: đoạn {s['id'][:8]} dài {r['duration']}")
            if r["start"] < prev_end:
                problems.append(f"track {t['type']}: đoạn {s['id'][:8]} chồng lên đoạn trước")
            if r["start"] + r["duration"] > content["duration"] + 1000:
                problems.append(f"track {t['type']}: đoạn {s['id'][:8]} vượt quá cuối project")
            prev_end = r["start"] + r["duration"]
            for kf in s.get("common_keyframes", []):
                offsets = [k["time_offset"] for k in kf["keyframe_list"]]
                if offsets != sorted(offsets) or any(o < 0 or o > r["duration"] for o in offsets):
                    problems.append(f"track {t['type']}: keyframe {kf['property_type']} sai thời điểm")
    return problems


def load_analysis(target: str) -> dict:
    path = Path(target)
    if path.is_dir():
        return json.loads((path / "analysis.json").read_text(encoding="utf-8"))
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    from ..analyze.run import analyze_video  # video: phân tích trước
    return analyze_video(path)[0]


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    name = None
    if "--name" in argv:
        i = argv.index("--name")
        name = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 2:
        print(__doc__)
        return 1
    analysis = load_analysis(args[0])
    photos = args[1:]
    lib = library.load()
    try:
        content, skeleton, report = build(analysis, photos, lib)
    except ValueError as e:
        print(f"Lỗi: {e}")
        return 1

    problems = validate(content)
    print(f"Khung: project {skeleton.name!r} · {len(content['tracks'])} track · dài {content['duration'] / 1e6:.2f}s")
    print(f"Hiệu ứng: " + ", ".join(f"{k} → {v}" for k, v in report.effects.items()))
    if report.transitions:
        print(f"Transition: {', '.join(report.transitions)}")
    if report.skipped:
        print("Không có hiệu ứng tương ứng nên bỏ qua: " + ", ".join(f"{k} ({n} lần)" for k, n in report.skipped.items()))
    if report.uncached:
        print("Không còn file trong máy, CapCut có thể phải tải lại: " + ", ".join(sorted(report.uncached)))
    if report.missing_overlays:
        print(f"Thiếu {len(report.missing_overlays)} lớp phủ, cần bạn đưa file:")
        for o in report.missing_overlays:
            print(f"   {o['kind']} ({o['blend']}) {o['start_s']:.1f}-{o['end_s']:.1f}s, ảnh minh hoạ: {o['sample']}")
    print(f"Chữ: {report.texts}")
    if problems:
        print("Cấu trúc có lỗi, không ghi:\n   " + "\n   ".join(problems))
        return 1
    if dry:
        print("Cấu trúc hợp lệ. Chạy thử, chưa ghi vào CapCut.")
        return 0
    try:
        folder = write_draft(skeleton.folder, name or f"Dựng từ {Path(analysis['video']['path']).stem[:30]}", content)
    except CapCutRunningError as e:
        print(f"Lỗi: {e}")
        return 1
    print(f"Đã tạo project: {folder.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
