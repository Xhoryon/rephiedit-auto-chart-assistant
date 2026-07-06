from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Protocol

from .analysis import AudioAnalysis
from .config import AssistantConfig, Difficulty


class PhraseCandidate(Protocol):
    time: float
    section: str
    source: str
    score: float
    accent: object


@dataclass(frozen=True)
class Phrase:
    label: str
    pattern: str
    start_index: int
    end_index: int
    start_time: float
    end_time: float
    intensity: float

    @property
    def length(self) -> int:
        return self.end_index - self.start_index + 1


def generate_phrases(candidates: list[PhraseCandidate], analysis: AudioAnalysis, config: AssistantConfig) -> list[Phrase]:
    phrases: list[Phrase] = []
    index = 0
    while index < len(candidates):
        candidate = candidates[index]
        available = _continuous_span(candidates, index, max_gap=0.18)
        section = candidate.section
        if _should_drag_chain(candidates, index, available, config):
            length = min(max(config.drag_chain_min_length, min(6, available)), min(12, config.drag_chain_max_length))
            pattern = _drag_pattern_for(section, len(phrases))
            phrases.append(_phrase("Drag Chain", pattern, candidates, index, index + length - 1))
            index += length
            continue
        if _is_hold_phrase(candidate, analysis, config):
            phrases.append(_phrase("Hold Phrase", "Center Close", candidates, index, index))
            index += 1
            continue
        if section == "Drop" and available >= 3:
            length = min(5, available)
            phrases.append(_phrase("Burst", "Drop Pattern", candidates, index, index + length - 1))
            index += length
            continue
        if _is_build_area(candidates, index) and available >= 3 and config.difficulty in {Difficulty.IN, Difficulty.AT}:
            length = min(4, available)
            phrases.append(_phrase("Build", "Build Pattern", candidates, index, index + length - 1))
            index += length
            continue
        if candidate.accent.accent_score >= 0.74:
            phrases.append(_phrase("Accent Phrase", "Jump", candidates, index, index))
            index += 1
            continue
        if section == "Intro":
            length = min(4, max(1, available))
            phrases.append(_phrase("Tap Stream", "Alternating", candidates, index, index + length - 1))
            index += length
            continue
        if section == "Bridge":
            phrases.append(_phrase("Tap Stream", "Center Close", candidates, index, index))
            index += 1
            continue
        if section == "Outro":
            length = min(3, max(1, available))
            phrases.append(_phrase("Outro", "Outro Pattern", candidates, index, index + length - 1))
            index += length
            continue
        length = min(4, max(1, available))
        phrases.append(_phrase("Tap Stream", "Tap Stream", candidates, index, index + length - 1))
        index += length
    return phrases


def phrase_for_index(phrases: list[Phrase], index: int) -> Phrase | None:
    for phrase in phrases:
        if phrase.start_index <= index <= phrase.end_index:
            return phrase
    return None


def phrase_summary(phrases: list[Phrase]) -> dict[str, object]:
    counts: dict[str, int] = {}
    for phrase in phrases:
        counts[phrase.label] = counts.get(phrase.label, 0) + 1
    drag_chains = [phrase.length for phrase in phrases if phrase.label == "Drag Chain"]
    return {
        "phrase_count": len(phrases),
        "counts": counts,
        "drag_chain_count": len(drag_chains),
        "longest_drag_chain": max(drag_chains, default=0),
        "patterns_used": sorted({phrase.pattern for phrase in phrases}),
        "preview": [
            {
                "label": phrase.label,
                "pattern": phrase.pattern,
                "start": round(phrase.start_time, 3),
                "end": round(phrase.end_time, 3),
                "length": phrase.length,
            }
            for phrase in phrases[:24]
        ],
    }


def _phrase(label: str, pattern: str, candidates: list[PhraseCandidate], start: int, end: int) -> Phrase:
    end = min(end, len(candidates) - 1)
    values = [candidates[i].accent.accent_score for i in range(start, end + 1)]
    return Phrase(label, pattern, start, end, candidates[start].time, candidates[end].time, mean(values) if values else 0.0)


def _continuous_span(candidates: list[PhraseCandidate], index: int, max_gap: float) -> int:
    count = 1
    while index + count < len(candidates) and candidates[index + count].time - candidates[index + count - 1].time <= max_gap:
        count += 1
    return count


def _should_drag_chain(candidates: list[PhraseCandidate], index: int, available: int, config: AssistantConfig) -> bool:
    if not config.enable_drag or available < config.drag_chain_min_length:
        return False
    if config.difficulty not in {Difficulty.IN, Difficulty.AT} and config.chart_style == "Official-like":
        return False
    window = candidates[index : index + min(available, 8)]
    avg_hat = mean(item.accent.hat_score for item in window)
    avg_high = mean(item.accent.high_energy for item in window)
    avg_onset = mean(item.accent.onset_score for item in window)
    section = candidates[index].section
    threshold = 0.38 if config.chart_style in {"Dense", "Experimental", "Balanced"} else 0.42
    if section == "Intro" and config.chart_style == "Official-like":
        return False
    return (
        (avg_hat >= threshold and avg_high >= 0.05 and available >= 3)
        or (section == "Drop" and avg_hat >= threshold - 0.06 and avg_onset >= 0.14)
        or (section == "Verse" and config.difficulty == Difficulty.AT and avg_hat >= threshold and available >= 4)
    )


def _drag_pattern_for(section: str, phrase_index: int) -> str:
    if section == "Drop":
        return "Wave" if phrase_index % 2 else "Zigzag"
    return ["Left->Right", "Right->Left", "Stair", "Center"][phrase_index % 4]


def _is_hold_phrase(candidate: PhraseCandidate, analysis: AudioAnalysis, config: AssistantConfig) -> bool:
    if candidate.accent.onset_score > 0.55:
        return False
    if config.difficulty == Difficulty.AT and candidate.accent.accent_score > 0.48:
        return False
    nearby_onsets = sum(1 for onset in analysis.onsets if abs(onset - candidate.time) <= 0.32)
    if nearby_onsets >= (2 if config.difficulty == Difficulty.AT else 3):
        return False
    return any(start <= candidate.time <= end and end - candidate.time >= 0.55 for start, end in analysis.long_regions)


def _is_build_area(candidates: list[PhraseCandidate], index: int) -> bool:
    if index + 3 >= len(candidates):
        return False
    values = [candidates[index + offset].accent.energy_score for offset in range(4)]
    return values[-1] > values[0] + 0.12
