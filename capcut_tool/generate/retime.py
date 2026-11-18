"""Áp công thức (vị trí beat) lên nhạc mới: tính lại mọi mốc thời gian trong draft_content."""
from __future__ import annotations

import math

from ..audio.beats import BeatGrid
from ..capcut.drafts import US

START_SLACK_S = 0.06
MIN_KEEP_RATIO = 0.6  # nhạc ngắn hơn thì cắt bớt cuối mẫu, nhưng phải giữ được ít nhất 60%


def match_tempo(grid: BeatGrid, target_tempo: float) -> BeatGrid:
    """Chọn chia đôi / giữ nguyên / gộp đôi beat sao cho tempo gần mẫu gốc nhất.

    Ví dụ nhạc 90 BPM áp lên mẫu 140 BPM: cắt theo nửa nhịp (180) sát hơn là giữ 90,
    nhờ vậy độ dài mẫu không bị kéo quá xa bản gốc.
    """
    return min((grid.scaled(f) for f in (0.5, 1, 2)),
               key=lambda g: abs(math.log(g.tempo / target_tempo)))


class NewTimeline:
    """Đổi vị trí beat của công thức sang micro giây trên timeline mới.

    Công thức bắt đầu ở start_beat (có thể lẻ, ví dụ -0.25). Ta dịch công thức đi k beat nguyên
    sao cho mốc đầu rơi vào trong nhạc mới (>= 0 giây), để beat của công thức trùng beat của nhạc.
    Timeline bắt đầu tại thời điểm đó trong nhạc (source_start của đoạn nhạc).
    """

    def __init__(self, formula: dict, grid: BeatGrid, music_duration_s: float, anchor_s: float | None = None):
        """anchor_s: khi dùng lại đúng bài nhạc của khung mẫu, là giây trong bài mà mẫu bắt đầu."""
        self.grid = grid
        self.fps = formula["canvas"]["fps"] or 30.0
        self.start_beat = formula["start_beat"]
        self.end_beat = formula["end_beat"]
        if anchor_s is not None:
            self.shift = round(grid.to_beat(anchor_s) - self.start_beat)
        else:
            # start_beat đã làm tròn nên cho phép mốc đầu sớm hơn 0 giây một chút rồi kẹp về 0
            slack = START_SLACK_S / grid.period
            self.shift = math.ceil(grid.to_beat(0.0) - self.start_beat - slack)
        self.music_start_s = max(grid.to_time(self.start_beat + self.shift), 0.0)
        end_s = grid.to_time(self.end_beat + self.shift)
        needed = end_s - self.music_start_s
        available = music_duration_s - self.music_start_s
        # nhạc đã được cắt sẵn đúng độ dài bạn muốn: nếu ngắn hơn công thức thì cắt bớt cuối mẫu
        self.truncated_s = max(needed - available, 0.0)
        if available < needed * MIN_KEEP_RATIO:
            raise ValueError(
                f"Nhạc mới quá ngắn: công thức cần {needed:.2f}s nhưng nhạc chỉ còn {available:.2f}s, "
                f"cắt bớt sẽ mất quá nửa mẫu")
        self.duration = self._frame(min(needed, available))

    def _frame(self, seconds: float) -> int:
        """Làm tròn về đúng ranh giới khung hình, trả về micro giây."""
        frames = round(seconds * self.fps)
        return round(frames * US / self.fps)

    @property
    def frame_us(self) -> int:
        return round(US / self.fps)

    def at(self, beat: float) -> int:
        if beat <= self.start_beat:
            return 0
        if beat >= self.end_beat:
            return self.duration
        t = self._frame(self.grid.to_time(beat + self.shift) - self.music_start_s)
        return min(max(t, 0), self.duration)


def _index(content: dict) -> dict[str, dict]:
    idx = {}
    for items in content["materials"].values():
        if isinstance(items, list):
            for m in items:
                if isinstance(m, dict) and "id" in m:
                    idx[m["id"]] = m
    return idx


def retime(content: dict, formula: dict, nt: NewTimeline) -> set[str]:
    """Sửa trực tiếp content (dict của draft_content.json) theo timeline mới.

    Trả về id các đoạn bị bỏ vì nằm trong phần cuối bị cắt khi nhạc ngắn hơn công thức.
    """
    materials = _index(content)
    segments = {s["id"]: s for t in content["tracks"] for s in t["segments"]}
    missing = [f["id"] for f in formula["segments"] if f["id"] not in segments]
    if missing:
        raise ValueError(f"Project mẫu đã bị sửa sau khi học, thiếu {len(missing)} đoạn. Hãy học lại công thức.")

    dropped: set[str] = set()
    for f in formula["segments"]:
        seg = segments[f["id"]]
        start = nt.at(f["start_beat"])
        if start >= nt.duration:
            dropped.add(f["id"])  # nằm hoàn toàn trong phần cuối bị cắt bớt
            continue
        duration = max(nt.at(f["end_beat"]) - start, nt.frame_us)
        seg["target_timerange"] = {"start": start, "duration": duration}
        _retime_source(seg, materials.get(seg["material_id"], {}), duration)

        for kf, fk in zip(seg.get("common_keyframes", []), f.get("keyframes", [])):
            for item, beat in zip(kf.get("keyframe_list", []), fk["beats"]):
                item["time_offset"] = min(max(nt.at(beat) - start, 0), duration)
            # keyframe sau điểm cắt bị dồn về cuối đoạn; giữ một cái cho mỗi thời điểm
            seen: set[int] = set()
            kf["keyframe_list"] = [k for k in kf.get("keyframe_list", [])
                                   if not (k["time_offset"] in seen or seen.add(k["time_offset"]))]

        for fa in f.get("animations", []):
            anim_mat = materials.get(fa["ref_id"], {})
            for a in anim_mat.get("animations", []):
                if a.get("id") == fa["anim_id"]:
                    a_start = min(max(nt.at(fa["start_beat"]) - start, 0), duration)
                    a["start"] = a_start
                    a["duration"] = max(min(nt.at(fa["end_beat"]) - start, duration) - a_start, 0)

        if "transition" in f:
            tr = materials.get(f["transition"]["ref_id"])
            if tr is not None:
                tr["duration"] = min(round(f["transition"]["beats"] * nt.grid.period * US), duration)

    for track in content["tracks"]:
        track["segments"] = [s for s in track["segments"] if s["id"] not in dropped]
    _fix_overlaps(content, nt.frame_us)
    content["duration"] = nt.duration
    return dropped


def _retime_source(seg: dict, material: dict, duration: int) -> None:
    src = seg.get("source_timerange")
    if not src:
        return
    need = round(duration * (seg.get("speed") or 1.0))
    if material.get("type") == "video":
        # giữ điểm bắt đầu trong clip, lùi lại nếu clip không đủ dài
        available = material.get("duration") or need
        src["start"] = max(0, min(src["start"], available - need))
    elif material.get("type") == "photo":
        src["start"] = 0
    src["duration"] = need


def _fix_overlaps(content: dict, frame_us: int) -> None:
    """Sau khi làm tròn, đảm bảo các đoạn trên cùng một track không chồng lên nhau."""
    for track in content["tracks"]:
        prev_end = 0
        for seg in sorted(track["segments"], key=lambda s: s["target_timerange"]["start"]):
            tr = seg["target_timerange"]
            if tr["start"] < prev_end:
                end = tr["start"] + tr["duration"]
                tr["start"] = prev_end
                tr["duration"] = max(end - prev_end, frame_us)
                if seg.get("source_timerange"):
                    seg["source_timerange"]["duration"] = round(tr["duration"] * (seg.get("speed") or 1.0))
            prev_end = tr["start"] + tr["duration"]
        track["segments"].sort(key=lambda s: s["target_timerange"]["start"])
