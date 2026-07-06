from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from .timebase import beat_tuple_to_beats, compare_time, seconds_to_beat_tuple


@dataclass
class ValidationReport:
    fixed_count: int = 0
    warnings: List[str] = field(default_factory=list)
    notes_inside_hold_fixed_count: int = 0
    holds_trimmed_count: int = 0
    holds_split_count: int = 0
    longest_hold_duration: float = 0.0
    hold_timeline_coverage: float = 0.0
    hold_count: int = 0
    hold_ratio: float = 0.0


NOTE_TYPES = {1, 2, 3, 4}
RHYTHM_TYPES = {1, 3, 4}
DEFAULT_HOLD_X_TOLERANCE = 96.0
HOLD_EDGE_GAP_SECONDS = 0.08
MIN_REPAIRED_HOLD_SECONDS = 0.18


def validate_and_fix_chart(
    chart: Dict[str, Any],
    max_hold_duration_seconds: float | None = None,
    hold_x_tolerance: float = DEFAULT_HOLD_X_TOLERANCE,
) -> Tuple[Dict[str, Any], ValidationReport]:
    report = ValidationReport()
    chart.setdefault("BPMList", [{"bpm": 120.0, "startTime": [0, 0, 1]}])
    chart.setdefault("META", {})
    chart.setdefault("judgeLineGroup", ["Default"])
    lines = chart.setdefault("judgeLineList", [])
    if not lines:
        lines.append({})
        report.fixed_count += 1
    if len(lines) > 1:
        del lines[1:]
        report.fixed_count += 1
        report.warnings.append("Removed extra judge lines for v1 single-line constraint.")
    for line in lines:
        _ensure_line_defaults(line, report)
        fixed_notes = []
        last_by_x: dict[int, list[int]] = {}
        for note in line.get("notes", []):
            if note.get("type") not in NOTE_TYPES:
                report.fixed_count += 1
                continue
            _fix_note(note, report)
            bucket = round(note["positionX"] / 45)
            last = last_by_x.get(bucket)
            if last and compare_time(note["startTime"], last) == 0:
                note["positionX"] = max(-675.0, min(675.0, note["positionX"] + 90.0))
                report.fixed_count += 1
            last_by_x[bucket] = note["startTime"]
            fixed_notes.append(note)
        line["notes"] = _sort_notes(fixed_notes)
        repair_notes_inside_holds(chart, report, hold_x_tolerance=hold_x_tolerance)
        if max_hold_duration_seconds is not None:
            _limit_hold_durations(chart, report, max_hold_duration_seconds)
        line["notes"] = _sort_notes(line.get("notes", []))
        line["numOfNotes"] = sum(1 for n in line["notes"] if not n.get("isFake"))
    _populate_hold_metrics(chart, report)
    return chart, report


def detect_notes_inside_holds(chart: Dict[str, Any], hold_x_tolerance: float = DEFAULT_HOLD_X_TOLERANCE) -> List[Dict[str, Any]]:
    collisions: List[Dict[str, Any]] = []
    for line_index, line in enumerate(chart.get("judgeLineList", [])):
        notes = line.get("notes", [])
        holds = [note for note in notes if note.get("type") == 2]
        rhythm_notes = [note for note in notes if note.get("type") in RHYTHM_TYPES]
        for hold in holds:
            hold_start = beat_tuple_to_beats(hold.get("startTime", [0, 0, 1]))
            hold_end = beat_tuple_to_beats(hold.get("endTime", hold.get("startTime", [0, 0, 1])))
            if hold_end <= hold_start:
                continue
            hold_x = float(hold.get("positionX", 0.0))
            for note in rhythm_notes:
                note_time = beat_tuple_to_beats(note.get("startTime", [0, 0, 1]))
                if hold_start + 1e-6 < note_time < hold_end - 1e-6 and abs(float(note.get("positionX", 0.0)) - hold_x) <= hold_x_tolerance:
                    collisions.append({
                        "line_index": line_index,
                        "hold": hold,
                        "note": note,
                        "note_type": note.get("type"),
                        "note_time_beats": note_time,
                        "hold_start_beats": hold_start,
                        "hold_end_beats": hold_end,
                        "x_delta": abs(float(note.get("positionX", 0.0)) - hold_x),
                    })
    return collisions


def repair_notes_inside_holds(
    chart: Dict[str, Any],
    report: ValidationReport | None = None,
    hold_x_tolerance: float = DEFAULT_HOLD_X_TOLERANCE,
) -> Tuple[Dict[str, Any], ValidationReport]:
    active_report = report or ValidationReport()
    bpm = _chart_bpm(chart)
    gap_beats = HOLD_EDGE_GAP_SECONDS * bpm / 60.0
    min_hold_beats = MIN_REPAIRED_HOLD_SECONDS * bpm / 60.0
    for line in chart.get("judgeLineList", []):
        notes = line.get("notes", [])
        replacement: list[Dict[str, Any]] = []
        for note in notes:
            if note.get("type") != 2:
                replacement.append(note)
                continue
            start = beat_tuple_to_beats(note.get("startTime", [0, 0, 1]))
            end = beat_tuple_to_beats(note.get("endTime", note.get("startTime", [0, 0, 1])))
            blockers = sorted(
                beat_tuple_to_beats(other.get("startTime", [0, 0, 1]))
                for other in notes
                if other is not note
                and other.get("type") in RHYTHM_TYPES
                and abs(float(other.get("positionX", 0.0)) - float(note.get("positionX", 0.0))) <= hold_x_tolerance
                and start + 1e-6 < beat_tuple_to_beats(other.get("startTime", [0, 0, 1])) < end - 1e-6
            )
            if not blockers:
                replacement.append(note)
                continue
            active_report.notes_inside_hold_fixed_count += len(blockers)
            active_report.fixed_count += len(blockers)
            cursor = start
            made_segment = False
            for blocker in blockers:
                segment_end = blocker - gap_beats
                if segment_end - cursor >= min_hold_beats:
                    segment = _copy_hold(note, cursor, segment_end, bpm)
                    replacement.append(segment)
                    made_segment = True
                cursor = max(cursor, blocker + gap_beats)
            if end - cursor >= min_hold_beats:
                replacement.append(_copy_hold(note, cursor, end, bpm))
                active_report.holds_split_count += 1
                made_segment = True
            if made_segment:
                active_report.holds_trimmed_count += 1
            else:
                active_report.warnings.append("Removed hold fully occupied by rhythm notes.")
        line["notes"] = _sort_notes(replacement)
    return chart, active_report


def _limit_hold_durations(chart: Dict[str, Any], report: ValidationReport, max_seconds: float) -> None:
    bpm = _chart_bpm(chart)
    max_beats = max_seconds * bpm / 60.0
    min_beats = MIN_REPAIRED_HOLD_SECONDS * bpm / 60.0
    for line in chart.get("judgeLineList", []):
        for note in line.get("notes", []):
            if note.get("type") != 2:
                continue
            start = beat_tuple_to_beats(note.get("startTime", [0, 0, 1]))
            end = beat_tuple_to_beats(note.get("endTime", note.get("startTime", [0, 0, 1])))
            if end - start > max_beats:
                note["endTime"] = seconds_to_beat_tuple((start + max(max_beats, min_beats)) * 60.0 / bpm, bpm)
                report.holds_trimmed_count += 1
                report.fixed_count += 1


def _populate_hold_metrics(chart: Dict[str, Any], report: ValidationReport) -> None:
    bpm = _chart_bpm(chart)
    intervals: list[tuple[float, float]] = []
    total_notes = 0
    for line in chart.get("judgeLineList", []):
        total_notes += len(line.get("notes", []))
        for note in line.get("notes", []):
            if note.get("type") == 2:
                start = _beats_to_seconds(beat_tuple_to_beats(note.get("startTime", [0, 0, 1])), bpm)
                end = _beats_to_seconds(beat_tuple_to_beats(note.get("endTime", note.get("startTime", [0, 0, 1]))), bpm)
                if end > start:
                    intervals.append((start, end))
    report.hold_count = len(intervals)
    report.hold_ratio = round(len(intervals) / max(1, total_notes), 4)
    report.longest_hold_duration = round(max((end - start for start, end in intervals), default=0.0), 4)
    last_time = max((end for _, end in intervals), default=0.0)
    for line in chart.get("judgeLineList", []):
        for note in line.get("notes", []):
            last_time = max(last_time, _beats_to_seconds(beat_tuple_to_beats(note.get("startTime", [0, 0, 1])), bpm))
    report.hold_timeline_coverage = round(_union_duration(intervals) / max(0.001, last_time), 4) if intervals else 0.0


def _ensure_line_defaults(line: Dict[str, Any], report: ValidationReport) -> None:
    defaults = {
        "Group": 0,
        "Name": "Auto Line",
        "Texture": "line.png",
        "bpmfactor": 1.0,
        "father": -1,
        "isCover": 1,
        "zOrder": 0,
        "notes": [],
        "alphaControl": [{"alpha": 1.0, "easing": 1, "x": 0.0}, {"alpha": 1.0, "easing": 1, "x": 9999999.0}],
        "posControl": [{"easing": 1, "pos": 1.0, "x": 0.0}, {"easing": 1, "pos": 1.0, "x": 9999999.0}],
        "sizeControl": [{"easing": 1, "size": 1.0, "x": 0.0}, {"easing": 1, "size": 1.0, "x": 9999999.0}],
        "skewControl": [{"easing": 1, "skew": 0.0, "x": 0.0}, {"easing": 1, "skew": 0.0, "x": 9999999.0}],
        "yControl": [{"easing": 1, "x": 0.0, "y": 1.0}, {"easing": 1, "x": 9999999.0, "y": 1.0}],
        "extended": {"inclineEvents": [_event(0.0, 0.0, [0, 0, 1], [1, 0, 1])]},
        "eventLayers": [{"alphaEvents": [_event(255, 255)], "moveXEvents": [_event(0.0, 0.0)], "moveYEvents": [_event(-450.0, -450.0)], "rotateEvents": [_event(0.0, 0.0)], "speedEvents": []}],
    }
    for key, value in defaults.items():
        if key not in line:
            line[key] = value
            report.fixed_count += 1
    if line["eventLayers"]:
        layer = line["eventLayers"][0]
        for key in ("alphaEvents", "moveXEvents", "moveYEvents", "rotateEvents", "speedEvents"):
            layer.setdefault(key, [] if key == "speedEvents" else [_event(0.0, 0.0)])
        layer["speedEvents"] = []


def _event(start: float, end: float, start_time: list[int] | None = None, end_time: list[int] | None = None) -> Dict[str, Any]:
    return {
        "easingLeft": 0.0,
        "easingRight": 1.0,
        "easingType": 1,
        "end": end,
        "endTime": end_time or [999999, 0, 1],
        "linkgroup": 0,
        "start": start,
        "startTime": start_time or [0, 0, 1],
    }


def _fix_note(note: Dict[str, Any], report: ValidationReport) -> None:
    for key in ("startTime", "endTime"):
        value = note.get(key, [0, 0, 1])
        if len(value) != 3 or value[2] == 0:
            note[key] = [max(0, int(value[0] if value else 0)), 0, 1]
            report.fixed_count += 1
        if note[key][0] < 0:
            note[key] = [0, 0, 1]
            report.fixed_count += 1
    if note["type"] == 2 and compare_time(note["endTime"], note["startTime"]) <= 0:
        note["endTime"] = [note["startTime"][0], note["startTime"][1] + 1, max(4, note["startTime"][2])]
        report.fixed_count += 1
    if note["type"] != 2:
        note["endTime"] = list(note["startTime"])
    note["positionX"] = max(-675.0, min(675.0, float(note.get("positionX", 0.0))))
    note.setdefault("above", 1)
    note.setdefault("isFake", 0)
    note.setdefault("alpha", 255)
    note.setdefault("size", 1.0)
    note.setdefault("speed", 1.0)
    note.setdefault("visibleTime", 999999.0)
    note.setdefault("yOffset", 0.0)


def _chart_bpm(chart: Dict[str, Any]) -> float:
    try:
        return float(chart.get("BPMList", [{}])[0].get("bpm", 120.0)) or 120.0
    except Exception:
        return 120.0


def _beats_to_seconds(beats: float, bpm: float) -> float:
    return beats * 60.0 / max(1.0, bpm)


def _copy_hold(note: Dict[str, Any], start_beats: float, end_beats: float, bpm: float) -> Dict[str, Any]:
    copied = dict(note)
    copied["startTime"] = seconds_to_beat_tuple(_beats_to_seconds(start_beats, bpm), bpm)
    copied["endTime"] = seconds_to_beat_tuple(_beats_to_seconds(end_beats, bpm), bpm)
    return copied


def _sort_notes(notes: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    return sorted(notes, key=lambda n: (beat_tuple_to_beats(n.get("startTime", [0, 0, 1])), float(n.get("positionX", 0.0))))


def _union_duration(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    merged: list[tuple[float, float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start for start, end in merged)
