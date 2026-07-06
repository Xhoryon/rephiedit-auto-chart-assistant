from __future__ import annotations

from statistics import mean
from typing import Any


def evaluate_chart_quality(report: dict[str, Any]) -> dict[str, float]:
    target = report.get("density_target", {})
    ratios = report.get("type_ratios", {})
    phrase = report.get("phrase_summary", {})
    timing = report.get("timing_correction_summary", {})
    actual = float(report.get("note_count", 0))
    desired = float(target.get("target_notes_final", actual or 1))
    density = _score_ratio(actual, desired)
    timing_score = max(0.0, 100.0 - abs(float(timing.get("average_snap_delta_ms", 0.0))) * 1.5)
    patterns_used = len(phrase.get("patterns_used", []))
    pattern_diversity = min(100.0, 45.0 + patterns_used * 11.0)
    phrase_count = int(phrase.get("phrase_count", 0))
    drag_chains = int(phrase.get("drag_chain_count", 0))
    phrase_quality = min(100.0, 55.0 + min(phrase_count, 18) * 1.4 + drag_chains * 4.0)
    tap_ratio = float(ratios.get("tap", 1.0))
    drag_ratio = float(ratios.get("drag", 0.0))
    flick_ratio = float(ratios.get("flick", 0.0))
    hold_ratio = float(ratios.get("hold", 0.0))
    type_balance = max(0.0, 100.0 - max(0.0, drag_ratio - 0.18) * 280.0 - max(0.0, flick_ratio - 0.16) * 220.0)
    if tap_ratio < 0.55:
        type_balance -= 20.0
    readability = max(0.0, 100.0 - drag_ratio * 70.0 - flick_ratio * 45.0 + min(8.0, hold_ratio * 20.0))
    flow = min(100.0, 58.0 + phrase_count * 1.2 + pattern_diversity * 0.18)
    values = [density, timing_score, pattern_diversity, phrase_quality, type_balance, readability, flow]
    overall = mean(values)
    return {
        "Density": round(density, 2),
        "Timing": round(timing_score, 2),
        "Pattern Diversity": round(pattern_diversity, 2),
        "Phrase Quality": round(phrase_quality, 2),
        "Type Balance": round(type_balance, 2),
        "Readability": round(readability, 2),
        "Flow": round(flow, 2),
        "Overall": round(overall, 2),
    }


def _score_ratio(actual: float, desired: float) -> float:
    if desired <= 0:
        return 100.0
    ratio = actual / desired
    return max(0.0, min(100.0, 100.0 - abs(1.0 - ratio) * 120.0))
