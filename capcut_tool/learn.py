"""Học công thức từ project CapCut.

    python -m capcut_tool.learn "mẫu" ["mẫu 2" ...]
"""
from __future__ import annotations

import sys

from .capcut.drafts import list_drafts
from .formula.learn import learn, save


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    drafts = {d.name: d for d in list_drafts()}
    code = 0
    for name in argv:
        draft = drafts.get(name)
        if draft is None:
            print(f"Không tìm thấy project {name!r}")
            code = 1
            continue
        formula = learn(draft)
        path = save(formula)
        a = formula["alignment"]
        print(f"{name}: tempo {formula['music']['tempo']} BPM, {len(formula['segments'])} đoạn, "
              f"{a['on_beat_ratio']:.0%} mốc khớp beat (lệch tối đa {a['max_error_ms']} ms) -> {path}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
