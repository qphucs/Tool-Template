"""Miêu tả bằng lời -> thông số link động (beat chuyển cảnh, độ dài, bỏ hiệu ứng…).

Ví dụ:

    chuyển cảnh ở beat 8, bỏ 2 giây đầu nhạc, dài 20 giây, bỏ hiệu ứng pixelate
    nhịp đôi, lặp trước chuyển cảnh 2 beat, beat sớm 30ms

Có cấu hình AI thì AI đọc miêu tả (hiểu được câu tự do); không có thì dùng bộ quy tắc
offline cho các câu thường gặp. Kết quả luôn là một ``BeatPlan`` để người dùng xem lại
và chỉnh tiếp trên bảng chia beat trước khi tạo mẫu.

Quy ước đánh số: "beat N" tính từ đầu video, beat 1 là beat mở đầu video.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from ..ai.client import AIConfig, AIUnavailable, chat_json
from ..audio.beats import BeatGrid
from .compose import BeatPlan, apply_density

# từ tiếng Việt hay dùng -> từ khóa trong tên hiệu ứng CapCut
SYNONYMS = {
    "rung": ["shake", "shaky"], "lắc": ["shake", "shaky"], "giật": ["shake", "glitch"],
    "nháy": ["flash"], "chớp": ["flash"], "lóe": ["flash"],
    "mờ": ["blur"], "nhòe": ["blur"], "vỡ hình": ["pixelate"], "pixel": ["pixelate"],
    "nhiễu": ["glitch"], "màu": ["color", "rainbow"], "cầu vồng": ["rainbow"],
}
REMOVE_WORDS = r"(?:bỏ|xóa|xoá|tắt|loại|không dùng|không cần|không có|khỏi)"


def _plain(text: str) -> str:
    """Bỏ dấu để khớp cả khi người dùng gõ không dấu."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d")


def effect_names(formula: dict) -> list[str]:
    seen: list[str] = []
    for s in formula.get("segments", []):
        if s.get("track_type") == "effect" and s.get("name") and s["name"] not in seen:
            seen.append(s["name"])
    return seen


def _num(value: str) -> float:
    return float(value.replace(",", "."))


def parse_offline(text: str, formula: dict, grid: BeatGrid, plan: BeatPlan) -> tuple[BeatPlan, list[str]]:
    """Hiểu các câu thường gặp. Trả về (kế hoạch mới, các ý đã hiểu)."""
    raw = text or ""
    t = _plain(raw)
    notes: list[str] = []
    g = apply_density(grid, plan.density)
    p = replace(plan, remove_effects=list(plan.remove_effects))
    N = r"(\d+(?:[.,]\d+)?)"

    # mật độ beat trước, vì các chỉ số beat phía sau phụ thuộc vào nó
    if re.search(r"nhip doi|chia doi beat|gap doi|\bx2\b|\b2x\b|beat day|nua nhip", t):
        p = _rescale(p, 2.0)
        notes.append("chia đôi beat (nhịp dày gấp đôi)")
    elif re.search(r"gop (doi )?beat|beat thua|nhip thua|\b1/2\b", t):
        p = _rescale(p, 0.5)
        notes.append("gộp đôi beat (nhịp thưa)")
    g = apply_density(grid, p.density)

    m = re.search(rf"bat dau\D{{0,12}}?beat\s*(?:thu\s*)?{N}", t)
    if m:
        p = _shift_start(p, max(int(_num(m.group(1))) - 1, 0))
        notes.append(f"video bắt đầu ở beat {int(_num(m.group(1)))} của nhạc")
    else:
        m = (re.search(rf"bo\s*{N}\s*(?:s|giay)\s*dau", t)
             or re.search(rf"bat dau\D{{0,12}}?(?:giay\s*(?:thu\s*)?{N}|{N}\s*(?:s|giay))", t))
        if m:
            sec = _num(next(x for x in m.groups() if x))
            p = _shift_start(p, max(int(round(g.to_beat(sec))), 0))
            notes.append(f"video bắt đầu ở giây {sec:g} của nhạc")

    m = (re.search(rf"chuyen canh\D{{0,20}}?(?:beat|nhip|phach)\s*(?:thu\s*)?{N}", t)
         or re.search(rf"(?:beat|nhip|phach)\s*(?:thu\s*)?{N}\D{{0,12}}chuyen canh", t))
    if m:
        n = int(_num(m.group(1)))
        p.transition_index = p.start_index + max(n - 1, 1)
        notes.append(f"chuyển cảnh ở beat {n}")
    else:
        m = re.search(rf"chuyen canh\D{{0,12}}?sau\s*{N}\s*(?:beat|nhip|phach)", t)
        if m:
            n = int(_num(m.group(1)))
            p.transition_index = p.start_index + max(n, 1)
            notes.append(f"chuyển cảnh sau {n} beat")
        else:
            m = re.search(rf"chuyen canh\D{{0,15}}?(?:giay\s*(?:thu\s*)?{N}|{N}\s*(?:s|giay))", t)
            if m:
                sec = _num(next(x for x in m.groups() if x))
                start_s = g.to_time(p.start_index)
                p.transition_index = max(int(round(g.to_beat(start_s + sec))), p.start_index + 1)
                notes.append(f"chuyển cảnh ở giây {sec:g} của video")

    if re.search(r"het nhac|toan bo nhac|ca bai|full nhac", t):
        p.end_index = None
        notes.append("dài tới hết nhạc")
    else:
        m = re.search(rf"(?:dai|thoi luong|do dai)\D{{0,8}}?{N}\s*(?:s|giay)", t)
        if m:
            sec = _num(m.group(1))
            start_s = max(g.to_time(p.start_index), 0.0)
            p.end_index = round(float(g.to_beat(start_s + sec)), 4)
            notes.append(f"video dài {sec:g} giây")

    m = re.search(rf"lap\D{{0,15}}?truoc chuyen canh\D{{0,6}}?{N}\s*(?:beat|nhip)", t) \
        or re.search(rf"lap\s*{N}\s*(?:beat|nhip)\D{{0,10}}truoc chuyen canh", t)
    if m:
        p.intro_unit = _num(m.group(1))
        notes.append(f"chuyển cảnh muộn thì lặp {p.intro_unit:g} beat trước chuyển cảnh")
    m = re.search(rf"(?:lap|chu ky)\D{{0,10}}?(?:moi|sau)?\s*{N}\s*(?:beat|nhip)(?!\D{{0,10}}truoc)", t)
    if m and not re.search(r"truoc chuyen canh", t[m.start():m.end() + 25]):
        p.loop_period = _num(m.group(1))
        notes.append(f"đoạn lặp dài {p.loop_period:g} beat")

    m = re.search(rf"(?:beat|nhip)\D{{0,6}}(som|muon|lech)\D{{0,4}}{N}\s*ms", t)
    if m:
        ms = _num(m.group(2))
        p.offset_ms = -ms if m.group(1) == "som" else ms
        notes.append(f"dời beat {'sớm' if p.offset_ms < 0 else 'muộn'} {abs(p.offset_ms):g} ms")

    removed = _removed_effects(raw, effect_names(formula))
    for name in removed:
        if name not in p.remove_effects:
            p.remove_effects.append(name)
    if removed:
        notes.append("bỏ hiệu ứng: " + ", ".join(removed))
    if re.search(r"giu (lai )?(tat ca|het) hieu ung|khong bo hieu ung", t):
        p.remove_effects = []
        notes.append("giữ tất cả hiệu ứng")
    return p, notes


def _removed_effects(text: str, names: list[str]) -> list[str]:
    out: list[str] = []
    clauses = re.split(r"[.,;\n]|\bvà\b|\bva\b", text.lower())
    for clause in clauses:
        if not re.search(REMOVE_WORDS, clause) and not re.search(r"\b(bo|xoa|tat|khong dung)\b", _plain(clause)):
            continue
        plain = _plain(clause)
        for name in names:
            low = name.lower()
            hit = low in clause or _plain(low) in plain
            if not hit:
                for word, keys in SYNONYMS.items():
                    if (word in clause or _plain(word) in plain) and any(k in low for k in keys):
                        hit = True
                        break
            if hit and name not in out:
                out.append(name)
    return out


def _rescale(p: BeatPlan, density: float) -> BeatPlan:
    if density == p.density:
        return p
    f = density / p.density
    return replace(p, density=density, start_index=int(round(p.start_index * f)),
                   transition_index=int(round(p.transition_index * f)),
                   end_index=None if p.end_index is None else float(p.end_index) * f)


def _shift_start(p: BeatPlan, new_start: int) -> BeatPlan:
    """Đổi beat bắt đầu nhưng giữ khoảng cách tới chuyển cảnh và độ dài."""
    d = new_start - p.start_index
    return replace(p, start_index=new_start, transition_index=p.transition_index + d,
                   end_index=None if p.end_index is None else float(p.end_index) + d)


AI_SYSTEM = """Bạn là trợ lý dựng video CapCut. Người dùng miêu tả bằng tiếng Việt cách muốn
ghép một khung mẫu (phần đầu -> chuyển cảnh -> đoạn bùng -> đoạn lặp theo beat -> kết) lên nhạc mới.
Hãy chuyển miêu tả thành thông số. Chỉ điền các khóa người dùng thật sự nhắc tới, còn lại để null.
Quy ước: "beat N" đếm từ đầu video, beat 1 là beat mở đầu video.
Trả về đúng JSON:
{"transition_beat": int|null, "start_seconds": number|null, "start_music_beat": int|null,
 "duration_seconds": number|null, "to_music_end": bool|null, "density": 0.5|1|2|null,
 "remove_effects": [tên hiệu ứng lấy đúng trong danh sách] , "keep_all_effects": bool|null,
 "intro_unit_beats": number|null, "loop_period_beats": number|null, "offset_ms": number|null,
 "note": "tóm tắt ngắn những gì đã hiểu"}"""


def parse_description(text: str, formula: dict, grid: BeatGrid, plan: BeatPlan,
                      config: AIConfig | None = None) -> tuple[BeatPlan, list[str], str]:
    """Trả về (kế hoạch mới, các ý đã hiểu, nguồn: "AI" / "offline")."""
    if not (text or "").strip():
        return plan, [], "offline"
    offline, notes = parse_offline(text, formula, grid, plan)
    resolved = config.resolve() if config else None
    if resolved is None:
        return offline, notes, "offline"
    g = apply_density(grid, plan.density)
    prompt = "\n".join([
        f"Miêu tả: {text}",
        f"Hiệu ứng có trong khung mẫu: {', '.join(effect_names(formula)) or 'không có'}",
        f"Nhạc mới: tempo {g.tempo:.0f} BPM, {len(g.times)} beat, dài {g.times[-1]:.1f}s.",
        f"Hiện tại: chuyển cảnh ở beat {plan.transition_index - plan.start_index + 1}, "
        f"mật độ {plan.density:g}, bỏ hiệu ứng {plan.remove_effects or 'không'}.",
    ])
    try:
        data = chat_json(AI_SYSTEM, prompt, config=resolved)
    except AIUnavailable as exc:
        return offline, notes + [f"(AI lỗi: {exc} — dùng bộ hiểu câu offline)"], "offline"
    except Exception as exc:  # AI trả dữ liệu lạ: vẫn dùng kết quả offline
        return offline, notes + [f"(AI trả dữ liệu lạ: {exc} — dùng bộ hiểu câu offline)"], "offline"
    try:
        return _apply_ai(data, formula, grid, plan), [str(data.get("note") or "AI đã đọc miêu tả")], "AI"
    except Exception as exc:
        return offline, notes + [f"(Không áp được kết quả AI: {exc})"], "offline"


def _apply_ai(data: dict, formula: dict, grid: BeatGrid, plan: BeatPlan) -> BeatPlan:
    p = replace(plan, remove_effects=list(plan.remove_effects))
    dens = data.get("density")
    if dens in (0.5, 1, 2, 1.0, 2.0):
        p = _rescale(p, float(dens))
    g = apply_density(grid, p.density)
    if data.get("start_music_beat"):
        p = _shift_start(p, max(int(data["start_music_beat"]) - 1, 0))
    elif data.get("start_seconds") is not None:
        p = _shift_start(p, max(int(round(g.to_beat(float(data["start_seconds"])))), 0))
    if data.get("transition_beat"):
        p.transition_index = p.start_index + max(int(data["transition_beat"]) - 1, 1)
    if data.get("to_music_end"):
        p.end_index = None
    elif data.get("duration_seconds"):
        start_s = max(g.to_time(p.start_index), 0.0)
        p.end_index = round(float(g.to_beat(start_s + float(data["duration_seconds"]))), 4)
    names = effect_names(formula)
    if data.get("keep_all_effects"):
        p.remove_effects = []
    for name in data.get("remove_effects") or []:
        match = next((n for n in names if n.lower() == str(name).lower()), None) or \
            next((n for n in names if str(name).lower() in n.lower()), None)
        if match and match not in p.remove_effects:
            p.remove_effects.append(match)
    if data.get("intro_unit_beats"):
        p.intro_unit = float(data["intro_unit_beats"])
    if data.get("loop_period_beats"):
        p.loop_period = float(data["loop_period_beats"])
    if data.get("offset_ms") is not None:
        p.offset_ms = float(data["offset_ms"])
    return p
