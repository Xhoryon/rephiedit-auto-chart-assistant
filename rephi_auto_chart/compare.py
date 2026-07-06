from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

from .chart_analyzer import ChartAnalysisReport, analyze_chart_file


@dataclass
class ComparisonReport:
    official: ChartAnalysisReport
    generated: ChartAnalysisReport
    deltas: Dict[str, Any]


def compare_charts(official_chart: str | Path, generated_chart: str | Path) -> ComparisonReport:
    official = analyze_chart_file(official_chart)
    generated = analyze_chart_file(generated_chart)
    fields = ["total_notes", "tap_count", "hold_count", "drag_count", "flick_count", "nps", "average_density", "max_density"]
    deltas = {field: round(getattr(generated, field) - getattr(official, field), 4) for field in fields}
    return ComparisonReport(official=official, generated=generated, deltas=deltas)


def write_comparison_reports(report: ComparisonReport, output_dir: str | Path) -> Dict[str, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "comparison_report.json"
    html_path = out / "comparison_report.html"
    payload = asdict(report)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    html_path.write_text(
        f"<html><body><h1>Comparison Report</h1><pre>{json.dumps(payload, indent=2, ensure_ascii=False)}</pre></body></html>",
        encoding="utf-8",
    )
    return {"json": json_path, "html": html_path}

