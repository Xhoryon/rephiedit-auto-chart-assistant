from __future__ import annotations

import csv
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List

from .timebase import beat_tuple_to_beats


NOTE_NAMES = {1: "tap", 2: "hold", 3: "flick", 4: "drag"}


@dataclass
class ChartAnalysisReport:
    source: str
    bpm: float
    total_notes: int
    tap_count: int
    hold_count: int
    drag_count: int
    flick_count: int
    nps: float
    average_density: float
    max_density: int
    longest_hold_seconds: float
    per_10s: List[Dict[str, Any]]


def load_chart_any(path: str | Path) -> Dict[str, Any]:
    source = Path(path)
    if source.suffix.lower() == ".pez":
        with zipfile.ZipFile(source) as zf:
            chart_name = next(name for name in zf.namelist() if name.lower().endswith(".json"))
            return json.loads(zf.read(chart_name).decode("utf-8"))
    return json.loads(source.read_text(encoding="utf-8"))


def analyze_chart_file(path: str | Path) -> ChartAnalysisReport:
    chart = load_chart_any(path)
    bpm = float(chart.get("BPMList", [{"bpm": 120.0}])[0].get("bpm", 120.0))
    notes = []
    for line in chart.get("judgeLineList", []):
        notes.extend(line.get("notes", []))
    counts = {name: 0 for name in NOTE_NAMES.values()}
    note_seconds = []
    longest_hold = 0.0
    for note in notes:
        note_type = int(note.get("type", 1))
        counts[NOTE_NAMES.get(note_type, "tap")] += 1
        start = _time_to_seconds(note.get("startTime", [0, 0, 1]), bpm)
        end = _time_to_seconds(note.get("endTime", note.get("startTime", [0, 0, 1])), bpm)
        note_seconds.append(start)
        if note_type == 2:
            longest_hold = max(longest_hold, max(0.0, end - start))
    duration = max(note_seconds, default=0.0)
    per_10s = _bucket_counts(note_seconds)
    max_density = max((bucket["total"] for bucket in per_10s), default=0)
    total = len(notes)
    return ChartAnalysisReport(
        source=str(path),
        bpm=bpm,
        total_notes=total,
        tap_count=counts["tap"],
        hold_count=counts["hold"],
        drag_count=counts["drag"],
        flick_count=counts["flick"],
        nps=round(total / duration, 4) if duration > 0 else 0.0,
        average_density=round(total / max(1, len(per_10s)), 4) if per_10s else 0.0,
        max_density=max_density,
        longest_hold_seconds=round(longest_hold, 4),
        per_10s=per_10s,
    )


def write_analysis_reports(report: ChartAnalysisReport, output_dir: str | Path) -> Dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "chart_analysis.json"
    csv_path = out / "chart_analysis.csv"
    html_path = out / "chart_analysis.html"
    json_path.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["start", "end", "total"])
        writer.writeheader()
        writer.writerows(report.per_10s)
    rows = "".join(f"<tr><td>{b['start']}</td><td>{b['end']}</td><td>{b['total']}</td></tr>" for b in report.per_10s)
    html_path.write_text(
        f"<html><body><h1>Chart Analysis</h1><pre>{json.dumps(asdict(report), indent=2, ensure_ascii=False)}</pre>"
        f"<table><tr><th>Start</th><th>End</th><th>Total</th></tr>{rows}</table></body></html>",
        encoding="utf-8",
    )
    return {"json": json_path, "csv": csv_path, "html": html_path}


def _time_to_seconds(value: list[int], bpm: float) -> float:
    return beat_tuple_to_beats(value) * 60.0 / max(1.0, bpm)


def _bucket_counts(times: list[float]) -> List[Dict[str, Any]]:
    if not times:
        return []
    buckets: List[Dict[str, Any]] = []
    count = int(max(times) // 10) + 1
    for index in range(count):
        start = index * 10
        end = start + 10
        buckets.append({"start": start, "end": end, "total": sum(1 for t in times if start <= t < end)})
    return buckets

