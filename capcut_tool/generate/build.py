"""Ghép các bước: công thức + nhạc + ảnh/clip -> nội dung project mới."""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..audio.beats import detect_beats
from ..caption.writer import Caption, TemplateInfo, effects_summary, write_caption
from ..media import probe
from types import SimpleNamespace

from .compose import BeatPlan, Structure, compose, default_plan, music_grid, write_beat_marks
from .materials import fill_slots, fill_slots_ordered, list_materials, replace_music
from .retime import NewTimeline, match_tempo, retime
from .writer import write_draft

OUTPUTS_DIR = Path(__file__).resolve().parents[2] / "data" / "outputs"

# materials: thư mục (lấy ngẫu nhiên) hoặc danh sách ảnh/clip xếp đúng thứ tự ô thay
Materials = str | Path | list[str | Path] | None


@dataclass
class BuildResult:
    content: dict
    tempo: float
    duration_s: float
    music_start_s: float
    materials: list[Path]
    slots: list[str]          # ô thay còn lại sau khi cắt bớt
    music: Path               # nhạc thực sự đã dùng
    truncated_s: float = 0.0  # số giây cuối mẫu bị cắt vì nhạc ngắn hơn công thức
    summary: str = ""         # mô tả cách ghép các phần (chế độ link động)


def formula_music(formula: dict) -> Path:
    """Nhạc gốc của khung mẫu (file nhạc bạn đã dùng trong project CapCut)."""
    path = Path(formula["music"]["path"])
    if not path.is_file():
        raise ValueError(f"Không còn file nhạc gốc của khung mẫu: {path}")
    return path

def build_content(formula: dict, music_path: str | Path | None, materials: Materials,
                  seed: int | None = None, beat_plan: BeatPlan | None = None,
                  dynamic: bool = False, structure: Structure | None = None) -> BuildResult:
    """Tạo nội dung project mới trong bộ nhớ, chưa ghi gì ra đĩa.

    music_path None: giữ nhạc của khung mẫu, nhịp và độ dài giữ nguyên như bạn đã edit.
    """
    source = Path(formula["source"]["folder"])
    content = json.loads((source / "draft_content.json").read_text(encoding="utf-8"))

    same_music = music_path is None
    music = probe(formula_music(formula) if same_music else music_path)
    if dynamic or beat_plan is not None:
        return _build_dynamic(content, formula, music, same_music, materials, seed, beat_plan, structure)
    grid = match_tempo(detect_beats(music.path), formula["music"]["tempo"])
    # cùng bài nhạc thì neo đúng đoạn nhạc bạn đã dùng, khỏi dời sang beat khác
    anchor = formula["music"]["source_start_s"] if same_music else None
    nt = NewTimeline(formula, grid, music.duration_s, anchor_s=anchor)
    dropped = retime(content, formula, nt)
    replace_music(content, formula["music"]["segment_id"], music, nt)

    slots = [s for s in formula["slots"] if s not in dropped]
    if not slots:
        raise ValueError("Nhạc quá ngắn, cắt bớt cuối mẫu làm mất hết ô thay")
    used: list[Path] = []
    if isinstance(materials, list):
        used = fill_slots_ordered(content, slots, [Path(p) for p in materials])
    elif materials:
        used = fill_slots(content, slots, list_materials(materials), random.Random(seed))
    return BuildResult(content, grid.tempo, nt.duration / 1_000_000, nt.music_start_s, used, slots,
                       music.path, nt.truncated_s)


def _fill(content: dict, slots: list[str], materials: Materials, seed: int | None) -> list[Path]:
    if not slots:
        raise ValueError("Không còn ô thay nào sau khi ghép theo nhạc mới")
    if isinstance(materials, list):
        return fill_slots_ordered(content, slots, [Path(p) for p in materials])
    if materials:
        return fill_slots(content, slots, list_materials(materials), random.Random(seed))
    return []


def _build_dynamic(content: dict, formula: dict, music, same_music: bool, materials: Materials,
                   seed: int | None, plan: BeatPlan | None, structure: Structure | None) -> BuildResult:
    """Link động: chia phần công thức, cắt/lặp theo beat thật của nhạc mới."""
    grid = music_grid(music.path)
    plan = plan or default_plan(formula, grid, same_music, structure=structure)
    result = compose(content, formula, grid, music.duration_s, plan, structure)
    nt = SimpleNamespace(music_start_s=result.music_start_s, duration=result.duration)
    replace_music(content, formula["music"]["segment_id"], music, nt)
    write_beat_marks(content, formula["music"]["segment_id"],
                     [b - round(result.music_start_s * 1_000_000) for b in result.beats_us])
    used = _fill(content, result.kept_slots, materials, seed)
    parts: dict[str, float] = {}
    for p in result.pieces:
        parts[p.part] = parts.get(p.part, 0.0) + (p.out_b - p.out_a)
    summary = " · ".join(f"{k} {round(v, 2):g} beat" for k, v in parts.items())
    if result.removed:
        summary += f" · bỏ hiệu ứng: {', '.join(result.removed)}"
    return BuildResult(content, result.tempo, result.duration / 1_000_000, result.music_start_s,
                       used, result.kept_slots, music.path, 0.0, summary)


def template_info(formula: dict, result: BuildResult, style_hint: str = "") -> TemplateInfo:
    return TemplateInfo(
        formula=formula["name"],
        music_name=result.music.stem,
        tempo=result.tempo,
        duration_s=result.duration_s,
        slot_count=len(result.slots),
        effects=effects_summary(result.content),
        style_hint=style_hint,
    )


def make_caption(formula: dict, result: BuildResult, style_hint: str = "") -> Caption:
    return write_caption(template_info(formula, result, style_hint))


def generate(formula: dict, music_path: str | Path | None, materials: Materials,
             name: str, seed: int | None = None, style_hint: str = "",
             beat_plan: BeatPlan | None = None, dynamic: bool = False,
             structure: Structure | None = None) -> tuple[Path, BuildResult, Caption]:
    """Tạo project trong CapCut và lưu hồ sơ đăng (tiêu đề, hashtag…) vào data/outputs."""
    result = build_content(formula, music_path, materials, seed, beat_plan, dynamic, structure)
    folder = write_draft(Path(formula["source"]["folder"]), name, result.content)
    info = template_info(formula, result, style_hint)
    caption = write_caption(info)
    save_record(formula, folder, result, info, caption)
    return folder, result, caption


def generate_with_caption(formula: dict, music_path: str | Path | None, materials: Materials,
                          name: str, caption_factory: Callable[[TemplateInfo], Caption],
                          seed: int | None = None,
                          style_hint: str = "", beat_plan: BeatPlan | None = None,
                          dynamic: bool = False,
                          structure: Structure | None = None) -> tuple[Path, BuildResult, Caption]:
    """Như ``generate`` nhưng tự tạo caption từ thông tin mẫu.

    Dùng cho batch: kế hoạch biến thể đã có tiêu đề/hashtag riêng, không cần
    gọi lại AI cho từng project.
    """
    result = build_content(formula, music_path, materials, seed, beat_plan, dynamic, structure)
    folder = write_draft(Path(formula["source"]["folder"]), name, result.content)
    info = template_info(formula, result, style_hint)
    caption = caption_factory(info)
    save_record(formula, folder, result, info, caption)
    return folder, result, caption


def save_record(formula: dict, folder: Path, result: BuildResult,
                info: TemplateInfo, caption: Caption) -> Path:
    """Lưu hồ sơ đăng của một project mới vào data/outputs."""
    record = {
        "draft_name": folder.name,
        "draft_folder": str(folder),
        "created": datetime.now().isoformat(timespec="seconds"),
        "formula": formula["name"],
        "music": str(result.music),
        "materials": [str(p) for p in result.materials],
        "duration_s": round(result.duration_s, 3),
        "template_info": asdict(info),
        "caption": caption.to_dict(),
        "status": "chờ đăng",
    }
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUTS_DIR / f"{folder.name}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
