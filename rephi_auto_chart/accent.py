from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from .analysis import AudioAnalysis


@dataclass(frozen=True)
class AccentFeatures:
    time: float
    accent_score: float
    kick_score: float
    snare_score: float
    hat_score: float
    energy_score: float
    onset_score: float
    section_intensity: float
    bass_energy: float
    mid_energy: float
    high_energy: float


def detect_accent_at(analysis: AudioAnalysis, time_seconds: float) -> AccentFeatures:
    energy = _curve_value(analysis.energy_curve, analysis.hop_seconds, time_seconds)
    onset = _curve_value(analysis.attack_curve or analysis.energy_curve, analysis.hop_seconds, time_seconds)
    local_prominence = _local_prominence(analysis, time_seconds)
    bass_energy = _curve_value(analysis.bass_energy_curve or analysis.energy_curve, analysis.hop_seconds, time_seconds)
    mid_energy = _curve_value(analysis.mid_energy_curve or analysis.energy_curve, analysis.hop_seconds, time_seconds)
    high_energy = _curve_value(analysis.high_energy_curve or analysis.energy_curve, analysis.hop_seconds, time_seconds)
    beat_strength = 1.0 if _near_strong_beat(analysis, time_seconds) else 0.45 if _near_beat(analysis, time_seconds) else 0.0
    section_intensity = _section_intensity(analysis, time_seconds)
    close_count = _nearby_onset_count(analysis, time_seconds, 0.34)

    kick = _clamp(0.34 * bass_energy + 0.24 * energy + 0.22 * onset + 0.20 * beat_strength)
    snare = _clamp(0.30 * mid_energy + 0.30 * onset + 0.24 * local_prominence + 0.10 * energy + 0.06 * beat_strength)
    hat = _clamp(0.36 * high_energy + 0.25 * onset + 0.24 * min(1.0, close_count / 4.0) + 0.15 * (1.0 - min(0.82, bass_energy)))
    accent = _clamp(0.26 * onset + 0.22 * local_prominence + 0.18 * energy + 0.14 * max(bass_energy, mid_energy, high_energy) + 0.12 * beat_strength + 0.08 * section_intensity)
    return AccentFeatures(
        time=time_seconds,
        accent_score=accent,
        kick_score=kick,
        snare_score=snare,
        hat_score=hat,
        energy_score=energy,
        onset_score=onset,
        section_intensity=section_intensity,
        bass_energy=bass_energy,
        mid_energy=mid_energy,
        high_energy=high_energy,
    )


def accent_summary(features: list[AccentFeatures]) -> dict[str, float]:
    if not features:
        return {
            "strong_accents": 0.0,
            "average_accent": 0.0,
            "average_kick": 0.0,
            "average_hat": 0.0,
            "average_bass_energy": 0.0,
            "average_mid_energy": 0.0,
            "average_high_energy": 0.0,
        }
    return {
        "strong_accents": float(sum(1 for item in features if item.accent_score >= 0.72)),
        "average_accent": round(mean(item.accent_score for item in features), 4),
        "average_kick": round(mean(item.kick_score for item in features), 4),
        "average_hat": round(mean(item.hat_score for item in features), 4),
        "average_bass_energy": round(mean(item.bass_energy for item in features), 4),
        "average_mid_energy": round(mean(item.mid_energy for item in features), 4),
        "average_high_energy": round(mean(item.high_energy for item in features), 4),
    }


def _curve_value(values: list[float], hop_seconds: float, time_seconds: float) -> float:
    if not values:
        return 0.0
    if hop_seconds <= 0:
        return _clamp(values[0])
    index = round(time_seconds / hop_seconds)
    index = max(0, min(len(values) - 1, index))
    return _clamp(values[index])


def _local_prominence(analysis: AudioAnalysis, time_seconds: float) -> float:
    values = analysis.attack_curve or analysis.energy_curve
    if not values or analysis.hop_seconds <= 0:
        return 0.0
    index = max(0, min(len(values) - 1, round(time_seconds / analysis.hop_seconds)))
    radius = max(1, int(0.18 / analysis.hop_seconds))
    start = max(0, index - radius)
    end = min(len(values), index + radius + 1)
    local = values[start:end]
    baseline = mean(local) if local else 0.0
    return _clamp(values[index] - baseline + 0.5 * values[index])


def _nearby_onset_count(analysis: AudioAnalysis, time_seconds: float, window: float) -> int:
    return sum(1 for onset in analysis.onsets if abs(onset - time_seconds) <= window)


def _near_beat(analysis: AudioAnalysis, time_seconds: float) -> bool:
    return any(abs(beat - time_seconds) <= 0.055 for beat in analysis.beats)


def _near_strong_beat(analysis: AudioAnalysis, time_seconds: float) -> bool:
    if not analysis.beats:
        return False
    index = min(range(len(analysis.beats)), key=lambda i: abs(analysis.beats[i] - time_seconds))
    return abs(analysis.beats[index] - time_seconds) <= 0.065 and index % 4 == 0


def _section_intensity(analysis: AudioAnalysis, time_seconds: float) -> float:
    for start, end, label in analysis.sections:
        if start <= time_seconds < end:
            return {"Intro": 0.35, "Verse": 0.58, "Bridge": 0.46, "Drop": 1.0, "Outro": 0.32}.get(label, 0.55)
    return 0.55


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
