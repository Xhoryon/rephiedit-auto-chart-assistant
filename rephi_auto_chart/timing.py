from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .analysis import AudioAnalysis


@dataclass(frozen=True)
class TimingCorrection:
    original_time: float
    refined_time: float
    snapped_time: float
    final_time: float
    attack_delta_ms: float
    snap_delta_ms: float


@dataclass(frozen=True)
class TimingCalibration:
    recommended_offset_ms: float
    manual_offset_ms: float
    final_offset_ms: float
    snap_strength: float


def build_timing_calibration(analysis: AudioAnalysis, auto: bool, manual_offset_ms: float, snap_strength: float) -> TimingCalibration:
    recommended = estimate_recommended_offset_ms(analysis) if auto else 0.0
    final = recommended + manual_offset_ms
    return TimingCalibration(round(recommended, 3), float(manual_offset_ms), round(final, 3), max(0.0, min(1.0, snap_strength)))


def estimate_recommended_offset_ms(analysis: AudioAnalysis) -> float:
    if not analysis.onsets or len(analysis.beats) < 2:
        return 0.0
    grid = _subdivision_grid(analysis, subdivisions=4)
    if not grid:
        return 0.0
    deltas: list[float] = []
    for onset in analysis.onsets[:240]:
        nearest = min(grid, key=lambda value: abs(value - onset))
        delta = nearest - onset
        if abs(delta) <= 0.14:
            deltas.append(delta)
    if len(deltas) < 3:
        return 0.0
    value = median(deltas) * 1000.0
    return max(-150.0, min(150.0, value))


def correct_timing(time_seconds: float, analysis: AudioAnalysis, calibration: TimingCalibration) -> TimingCorrection:
    refined = refine_to_attack_peak(time_seconds, analysis)
    snapped = snap_to_beat_grid(refined, analysis, calibration.snap_strength)
    final = max(0.0, min(analysis.duration, snapped + calibration.final_offset_ms / 1000.0))
    return TimingCorrection(
        original_time=time_seconds,
        refined_time=refined,
        snapped_time=snapped,
        final_time=final,
        attack_delta_ms=(refined - time_seconds) * 1000.0,
        snap_delta_ms=(snapped - refined) * 1000.0,
    )


def refine_to_attack_peak(time_seconds: float, analysis: AudioAnalysis, window: float = 0.055) -> float:
    values = analysis.attack_curve or analysis.energy_curve
    if not values or analysis.hop_seconds <= 0:
        return time_seconds
    center = max(0, min(len(values) - 1, round(time_seconds / analysis.hop_seconds)))
    radius = max(1, int(window / analysis.hop_seconds))
    start = max(0, center - radius)
    end = min(len(values) - 1, center + radius)
    if start > end:
        return time_seconds
    best = max(range(start, end + 1), key=lambda index: values[index])
    best_time = best * analysis.hop_seconds
    if abs(best_time - time_seconds) <= window and values[best] >= 0.08:
        return best_time
    return time_seconds


def snap_to_beat_grid(time_seconds: float, analysis: AudioAnalysis, snap_strength: float) -> float:
    if snap_strength <= 0 or len(analysis.beats) < 2:
        return time_seconds
    grid = _subdivision_grid(analysis, subdivisions=4)
    if not grid:
        return time_seconds
    nearest = min(grid, key=lambda value: abs(value - time_seconds))
    interval = 60.0 / max(1.0, analysis.bpm) / 4.0
    tolerance = min(0.045, interval * 0.38)
    distance = nearest - time_seconds
    if abs(distance) > tolerance:
        return time_seconds
    return time_seconds + distance * max(0.0, min(1.0, snap_strength))


def _subdivision_grid(analysis: AudioAnalysis, subdivisions: int) -> list[float]:
    if len(analysis.beats) < 2:
        return []
    beat_interval = 60.0 / max(1.0, analysis.bpm)
    start = analysis.beats[0]
    step = beat_interval / max(1, subdivisions)
    grid: list[float] = []
    t = start
    while t <= analysis.duration + step:
        grid.append(round(t, 6))
        t += step
    return grid
