"""Dựng nội dung draft_content.json mới từ file phân tích video mẫu.

Không viết JSON CapCut từ con số không: lấy một project có sẵn của bạn làm khung (giữ nguyên cấu hình),
xoá hết track, rồi dựng lại từng đoạn bằng cách nhân bản đoạn mẫu cùng loại trong khung đó và đổi các giá trị.
Nhờ vậy mọi trường CapCut cần đều có mặt, đúng định dạng của phiên bản CapCut trên máy bạn.

Đơn vị của CapCut: thời gian micro giây; vị trí -1..1 (1 = mép khung, trục y hướng lên);
độ phóng 1.0 = vừa khung; góc xoay theo độ.
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..capcut.drafts import US, DraftInfo, list_drafts
from ..library.effects import choose, choose_blend
from ..media import probe

PHOTO_DURATION = 10_800_000_000
KF_PROPERTY = {"scale": "KFTypeScaleX", "rotation": "KFTypeRotation", "x": "KFTypePositionX", "y": "KFTypePositionY"}
# phụ liệu cơ bản của một đoạn ảnh/nhạc; các phụ liệu khác (transition, animation, hòa trộn…) được dựng lại riêng
BASIC_REFS = {"speeds", "canvases", "placeholder_infos", "sound_channel_mappings", "material_colors",
              "vocal_separations", "loudnesses", "beats"}
DEFAULT_TRANSITION_S = 0.4


def new_id() -> str:
    return str(uuid.uuid4()).upper()


def us(seconds: float) -> int:
    return int(round(seconds * US))


@dataclass
class BuildReport:
    """Những gì đã dựng và những gì phải bỏ qua, để báo cho bạn."""
    effects: dict[str, str] = field(default_factory=dict)       # kiểu -> tên hiệu ứng CapCut đã dùng
    skipped: dict[str, int] = field(default_factory=dict)       # kiểu không có hiệu ứng tương ứng -> số lần
    transitions: list[str] = field(default_factory=list)
    uncached: set[str] = field(default_factory=set)             # hiệu ứng không còn file trong máy
    texts: int = 0
    overlays: int = 0
    missing_overlays: list[dict] = field(default_factory=list)


# ---------- khung project ----------

def _has_tracks(content: dict) -> bool:
    kinds = {t["type"] for t in content["tracks"]}
    photo = any(s for t in content["tracks"] if t["type"] == "video" for s in t["segments"])
    return photo and {"effect", "audio"} <= kinds


def find_skeleton() -> tuple[DraftInfo, dict]:
    """Project ngắn của bạn có đủ track ảnh, hiệu ứng và nhạc để làm khung; ưu tiên project có lớp phủ."""
    best = None
    for d in list_drafts():
        if d.duration_s > 120:
            continue
        try:
            c = json.loads(d.content_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _has_tracks(c):
            score = (any(m.get("type") == "mix_mode" for m in c["materials"].get("effects", [])),
                     -d.duration_s)
            if best is None or score > best[0]:
                best = (score, d, c)
    if best is None:
        raise ValueError("Không tìm thấy project nào có đủ track ảnh, hiệu ứng và nhạc để làm khung")
    return best[1], best[2]


class Draft:
    """Nội dung project đang dựng, cùng các đoạn mẫu lấy từ khung."""

    def __init__(self, skeleton: dict):
        self.src = skeleton
        self.src_index = {m["id"]: (cat, m) for cat, items in skeleton["materials"].items()
                          if isinstance(items, list) for m in items if isinstance(m, dict) and "id" in m}
        self.content = copy.deepcopy(skeleton)
        self.content["tracks"] = []
        for key, items in self.content["materials"].items():
            if isinstance(items, list):
                self.content["materials"][key] = []
        self.content["id"] = self.content.get("id") or new_id()
        self.tpl_photo = self._template("video", lambda s, m: m.get("type") == "photo")
        self.tpl_overlay = self._template("video", lambda s, m: any(
            self.src_index.get(r, ("", {}))[1].get("type") == "mix_mode" for r in s.get("extra_material_refs", [])))
        self.tpl_effect = self._template("effect", lambda s, m: True)
        self.tpl_audio = self._template("audio", lambda s, m: True)
        self.tpl_track = {t["type"]: t for t in skeleton["tracks"]}

    def _template(self, track_type: str, test) -> dict | None:
        for t in self.src["tracks"]:
            if t["type"] != track_type:
                continue
            for s in t["segments"]:
                if test(s, self.src_index.get(s["material_id"], ("", {}))[1]):
                    return s
        return None

    def add_material(self, category: str, material: dict) -> dict:
        m = copy.deepcopy(material)
        m["id"] = new_id()
        self.content["materials"].setdefault(category, []).append(m)
        return m

    def clone_segment(self, template: dict, keep_refs: set[str], index: dict | None = None) -> tuple[dict, dict]:
        """Nhân bản đoạn mẫu: id mới, nhân bản vật liệu chính và phụ liệu thuộc keep_refs."""
        index = index or self.src_index
        seg = copy.deepcopy(template)
        seg["id"] = new_id()
        cat, mat = index[template["material_id"]]
        main = self.add_material(cat, mat)
        seg["material_id"] = main["id"]
        refs = []
        for r in template.get("extra_material_refs", []):
            rc, rm = index.get(r, ("", None))
            if rm is not None and rc in keep_refs:
                refs.append(self.add_material(rc, rm)["id"])
        seg["extra_material_refs"] = refs
        seg["common_keyframes"] = []
        seg["keyframe_refs"] = []
        return seg, main

    def add_track(self, track_type: str, segments: list[dict], flag: int | None = None) -> dict:
        tpl = self.tpl_track.get(track_type, {"attribute": 0, "flag": 0, "is_default_name": True, "name": ""})
        track = {**copy.deepcopy({k: v for k, v in tpl.items() if k != "segments"}),
                 "id": new_id(), "type": track_type, "segments": segments}
        if flag is not None:
            track["flag"] = flag
        position = len(self.content["tracks"])
        for s in segments:
            s["track_render_index"] = position
        self.content["tracks"].append(track)
        return track


def _place(tracks: list[list[tuple[int, int]]], start: int, end: int) -> int:
    """Chọn track đầu tiên không bị chồng thời gian (mỗi track CapCut không cho đoạn chồng nhau)."""
    for i, spans in enumerate(tracks):
        if all(end <= a or start >= b for a, b in spans):
            spans.append((start, end))
            return i
    tracks.append([(start, end)])
    return len(tracks) - 1


# ---------- dựng ----------

def _cover_scale(photo_w: int, photo_h: int, canvas_w: int, canvas_h: int) -> float:
    """CapCut đặt ảnh vừa khít trong khung; nhân hệ số này để ảnh phủ kín khung như video mẫu."""
    fit = min(canvas_w / photo_w, canvas_h / photo_h)
    fill = max(canvas_w / photo_w, canvas_h / photo_h)
    return fill / fit


def _keyframe(template: dict | None, offset: int, value: float) -> dict:
    base = copy.deepcopy(template) if template else {
        "curveType": "Line", "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0},
        "string_value": "", "graphID": ""}
    base.update({"id": new_id(), "time_offset": offset, "values": [value]})
    return base


def _kf_template(skeleton: dict) -> dict | None:
    for t in skeleton["tracks"]:
        for s in t["segments"]:
            for k in s.get("common_keyframes", []):
                if k.get("keyframe_list"):
                    return k["keyframe_list"][0]
    return None


def build(analysis: dict, photos: list[str | Path], lib: dict, overlay_files: dict[int, str] | None = None,
          skeleton: tuple[DraftInfo, dict] | None = None) -> tuple[dict, DraftInfo, BuildReport]:
    shots = analysis["shots"]
    if len(photos) != len(shots):
        raise ValueError(f"Video mẫu có {len(shots)} cảnh nên cần đúng {len(shots)} ảnh, bạn đưa {len(photos)} ảnh")
    info, skel = skeleton or find_skeleton()
    d = Draft(skel)
    if d.tpl_photo is None:
        raise ValueError(f"Project khung {info.name!r} không có đoạn ảnh để làm mẫu")
    report = BuildReport()
    vid = analysis["video"]
    canvas_w, canvas_h = (1080, 1920) if vid["height"] >= vid["width"] else (1920, 1080)
    d.content["canvas_config"].update({"width": canvas_w, "height": canvas_h, "ratio": "original"})
    d.content["fps"] = 30.0
    total = us(vid["duration_s"])
    kf_tpl = _kf_template(skel)

    # 1. track ảnh chính, mỗi cảnh một ảnh, chuyển động bằng keyframe
    main = []
    for shot, photo in zip(shots, photos):
        media = probe(photo)
        seg, mat = d.clone_segment(d.tpl_photo, BASIC_REFS)
        mat.update({"type": media.kind, "path": Path(photo).as_posix(), "material_name": Path(photo).name,
                    "width": media.width, "height": media.height, "unique_id": "", "has_audio": media.has_audio,
                    "duration": PHOTO_DURATION if media.kind == "photo" else us(media.duration_s)})
        start, end = us(shot["start_s"]), us(shot["end_s"])
        seg["target_timerange"] = {"start": start, "duration": end - start}
        seg["source_timerange"] = {"start": 0, "duration": end - start}
        cover = _cover_scale(media.width, media.height, canvas_w, canvas_h)
        seg["clip"] = {**seg.get("clip", {}), "scale": {"x": cover, "y": cover}, "rotation": 0.0,
                       "transform": {"x": 0.0, "y": 0.0}}
        seg["uniform_scale"] = {"on": True, "value": 1.0}
        convert = {"scale": lambda v: v * cover, "rotation": lambda v: v,
                   "x": lambda v: v * 2, "y": lambda v: -v * 2}  # ảnh: y hướng xuống; CapCut: y hướng lên
        for prop, points in shot["keyframes"].items():
            seg["common_keyframes"].append({
                "id": new_id(), "material_id": "", "property_type": KF_PROPERTY[prop],
                "keyframe_list": [_keyframe(kf_tpl, min(max(us(p["t_s"]) - start, 0), end - start), convert[prop](p["value"]))
                                  for p in points]})
        main.append(seg)

    # 2. transition gắn vào đoạn trước điểm cắt
    for tr in analysis["transitions"]:
        if tr["type"] == "cut":
            continue
        pick = choose(lib, "transitions", tr["type"])
        if pick is None:
            report.skipped[f"transition {tr['type']}"] = report.skipped.get(f"transition {tr['type']}", 0) + 1
            continue
        before = main[tr["after_shot"]]
        length = us(max(tr["end_s"] - tr["start_s"], DEFAULT_TRANSITION_S))
        limit = min(before["target_timerange"]["duration"], main[tr["after_shot"] + 1]["target_timerange"]["duration"]) // 2
        m = d.add_material("transitions", pick["raw"])
        m["duration"] = min(length, limit)
        before["extra_material_refs"].append(m["id"])
        report.transitions.append(pick["name"])
        if not pick["cached"]:
            report.uncached.add(pick["name"])
    d.add_track("video", main)

    # 3. lớp phủ bạn cung cấp, hòa trộn theo kiểu đã nhận ra
    overlay_files = overlay_files or {}
    overlay_segments = []
    for i, need in enumerate(analysis["needs"]["overlays"]):
        path = overlay_files.get(i)
        if not path:
            report.missing_overlays.append(need)
            continue
        template = d.tpl_overlay or d.tpl_photo
        media = probe(path)
        seg, mat = d.clone_segment(template, BASIC_REFS)
        mat.update({"type": media.kind, "path": Path(path).as_posix(), "material_name": Path(path).name,
                    "width": media.width, "height": media.height, "unique_id": "",
                    "duration": PHOTO_DURATION if media.kind == "photo" else us(media.duration_s)})
        start, end = us(need["start_s"]), us(need["end_s"])
        seg["target_timerange"] = {"start": start, "duration": end - start}
        seg["source_timerange"] = {"start": 0, "duration": min(end - start, mat["duration"])}
        blend = choose_blend(lib, need["blend"])
        if blend:
            seg["extra_material_refs"].append(d.add_material("effects", blend["raw"])["id"])
        overlay_segments.append(seg)
        report.overlays += 1
    lanes: list[list[tuple[int, int]]] = []
    by_lane: dict[int, list[dict]] = {}
    for seg in overlay_segments:
        r = seg["target_timerange"]
        by_lane.setdefault(_place(lanes, r["start"], r["start"] + r["duration"]), []).append(seg)
    for lane in sorted(by_lane):
        d.add_track("video", by_lane[lane], flag=2)

    # 4. hiệu ứng theo thời gian, xếp vào nhiều track để không chồng nhau
    if d.tpl_effect is not None:
        lanes, by_lane = [], {}
        for ev in analysis["events"]:
            pick = choose(lib, "video_effects", ev["type"])
            if pick is None:
                report.skipped[ev["type"]] = report.skipped.get(ev["type"], 0) + 1
                continue
            start = us(ev["start_s"])
            duration = max(us(ev["end_s"]) - start, us(1 / 30))
            seg = copy.deepcopy(d.tpl_effect)
            seg["id"] = new_id()
            seg["material_id"] = d.add_material("video_effects", pick["raw"])["id"]
            seg["extra_material_refs"], seg["common_keyframes"], seg["keyframe_refs"] = [], [], []
            seg["target_timerange"] = {"start": start, "duration": duration}
            report.effects[ev["type"]] = pick["name"]
            if not pick["cached"]:
                report.uncached.add(pick["name"])
            by_lane.setdefault(_place(lanes, start, start + duration), []).append(seg)
        for lane in sorted(by_lane):
            d.add_track("effect", sorted(by_lane[lane], key=lambda s: s["target_timerange"]["start"]))

    # 5. chữ chép từ video mẫu
    if analysis["texts"] and lib.get("text_samples"):
        sample = lib["text_samples"][0]
        index = {sample["segment"]["material_id"]: ("texts", sample["material"]),
                 **{r["material"]["id"]: (r["category"], r["material"]) for r in sample["refs"]}}
        texts = []
        for t in analysis["texts"]:
            seg, mat = d.clone_segment(sample["segment"], {r["category"] for r in sample["refs"]}, index)
            _set_text(mat, t["text"], t["color"])
            x, y, w, h = t["box"]
            start = us(t["start_s"])
            seg["target_timerange"] = {"start": start, "duration": max(us(t["end_s"]) - start, us(0.2))}
            seg["clip"] = {**(seg.get("clip") or {}), "rotation": 0.0,
                           "scale": {"x": 1.0, "y": 1.0},
                           "transform": {"x": (x + w / 2 - 0.5) * 2, "y": -(y + h / 2 - 0.5) * 2}}
            texts.append(seg)
            report.texts += 1
        lanes, by_lane = [], {}
        for seg in texts:
            r = seg["target_timerange"]
            by_lane.setdefault(_place(lanes, r["start"], r["start"] + r["duration"]), []).append(seg)
        for lane in sorted(by_lane):
            d.add_track("text", by_lane[lane])

    # 6. nhạc tách từ video mẫu
    music = analysis["music"]["path"]
    if music and d.tpl_audio is not None:
        media = probe(music)
        seg, mat = d.clone_segment(d.tpl_audio, BASIC_REFS)
        mat.update({"path": Path(music).as_posix(), "name": Path(music).name,
                    "duration": us(media.duration_s), "music_id": str(uuid.uuid4())})
        length = min(total, us(media.duration_s))
        seg["target_timerange"] = {"start": 0, "duration": length}
        seg["source_timerange"] = {"start": 0, "duration": length}
        seg["speed"] = 1.0
        for b in d.content["materials"].get("beats", []):
            b["user_beats"] = []
            b.get("ai_beats", {}).update({"beats_path": "", "beats_url": "", "melody_path": "", "melody_url": ""})
        d.add_track("audio", [seg])

    d.content["duration"] = total
    return d.content, info, report


def _set_text(material: dict, text: str, rgb) -> None:
    """Đổi nội dung và màu chữ, giữ kiểu chữ của mẫu; bỏ font riêng để CapCut dùng font mặc định nếu thiếu file."""
    content = json.loads(material["content"])
    content["text"] = text
    style = copy.deepcopy(content["styles"][0]) if content.get("styles") else {}
    style["range"] = [0, len(text)]
    style.setdefault("fill", {"content": {"render_type": "solid", "solid": {}}})
    style["fill"]["content"]["solid"] = {"color": [c / 255 for c in rgb]}
    font = style.get("font", {})
    if font.get("path") and not Path(font["path"]).exists():
        style.pop("font", None)
    content["styles"] = [style]
    material["content"] = json.dumps(content, ensure_ascii=False)
