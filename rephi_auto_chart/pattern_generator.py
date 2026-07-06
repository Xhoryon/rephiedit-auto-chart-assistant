from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Protocol

from .config import AssistantConfig, Difficulty
from .phrases import Phrase, phrase_for_index


class PatternCandidate(Protocol):
    time: float
    section: str
    source: str
    score: float
    accent: object


@dataclass(frozen=True)
class PatternBlock:
    name: str
    start_index: int
    end_index: int
    section: str
    intensity: float
    complexity: float

    @property
    def length(self) -> int:
        return self.end_index - self.start_index + 1


PATTERN_COMPLEXITY: dict[str, float] = {
    "Single": 1.0,
    "Double": 1.25,
    "Triple": 1.45,
    "Quad": 1.65,
    "Alternating": 1.55,
    "Stair": 1.8,
    "Jump": 1.7,
    "Burst": 2.15,
    "Stream": 2.0,
    "Anchor": 1.9,
    "Jack": 1.55,
    "Trill": 1.85,
    "Drag Chain": 2.1,
    "Hold Anchor": 1.2,
}


def pattern_library_names() -> list[str]:
    return sorted(PATTERN_COMPLEXITY)


def build_pattern_plan(candidates: list[PatternCandidate], phrases: list[Phrase], config: AssistantConfig) -> list[PatternBlock]:
    if not candidates:
        return []
    blocks: list[PatternBlock] = []
    index = 0
    previous_name = ""
    same_name_run = 0
    while index < len(candidates):
        phrase = phrase_for_index(phrases, index)
        span = _phrase_span(phrase, index, len(candidates)) if phrase else _natural_span(candidates, index, config)
        name = _choose_pattern(candidates, index, span, phrase, config, previous_name, same_name_run)
        if name == previous_name:
            same_name_run += 1
        else:
            same_name_run = 1
        end = min(len(candidates) - 1, index + span - 1)
        intensity = mean(candidates[pos].accent.accent_score for pos in range(index, end + 1))
        blocks.append(PatternBlock(name, index, end, candidates[index].section, round(float(intensity), 4), PATTERN_COMPLEXITY[name]))
        previous_name = name
        index = end + 1
    return blocks


def pattern_for_index(blocks: list[PatternBlock], index: int) -> PatternBlock | None:
    for block in blocks:
        if block.start_index <= index <= block.end_index:
            return block
    return None


def note_type_for_pattern(block: PatternBlock | None, local_index: int, fallback_type: int, config: AssistantConfig) -> int:
    if block is None:
        return fallback_type
    name = block.name
    if name == "Drag Chain" and config.enable_drag:
        return 3
    if name == "Hold Anchor" and config.enable_hold and local_index == 0:
        return 2
    if name in {"Jump", "Anchor"} and config.enable_flick and local_index == 0:
        return 4
    if name == "Burst" and config.enable_flick and local_index == block.length - 1 and block.intensity >= 0.55:
        return 4
    if name == "Stream" and fallback_type == 3 and config.enable_drag:
        return 3
    if name == "Trill" and fallback_type == 3 and config.enable_drag and local_index % 4 == 3:
        return 3
    return 1 if fallback_type == 2 and name != "Hold Anchor" else fallback_type


def pattern_summary(blocks: list[PatternBlock]) -> dict[str, object]:
    histogram: dict[str, int] = {}
    longest_same = 0
    current = ""
    run = 0
    for block in blocks:
        histogram[block.name] = histogram.get(block.name, 0) + 1
        if block.name == current:
            run += 1
        else:
            current = block.name
            run = 1
        longest_same = max(longest_same, run)
    complexity = mean(block.complexity for block in blocks) if blocks else 0.0
    diversity = _diversity_score(histogram, len(blocks), longest_same)
    return {
        "pattern_count": len(blocks),
        "pattern_histogram": histogram,
        "pattern_diversity_score": round(diversity, 3),
        "pattern_complexity": round(complexity, 3),
        "longest_same_pattern": longest_same,
        "preview": [
            {
                "name": block.name,
                "section": block.section,
                "start_index": block.start_index,
                "end_index": block.end_index,
                "length": block.length,
                "intensity": block.intensity,
            }
            for block in blocks[:32]
        ],
    }


def validate_pattern_plan(blocks: list[PatternBlock]) -> list[str]:
    warnings: list[str] = []
    for block in blocks:
        if block.end_index < block.start_index:
            warnings.append(f"invalid pattern span: {block.name}")
        if block.name not in PATTERN_COMPLEXITY:
            warnings.append(f"unknown pattern: {block.name}")
    longest = pattern_summary(blocks).get("longest_same_pattern", 0)
    if int(longest) > 8:
        warnings.append("too many consecutive identical patterns")
    return warnings


def _phrase_span(phrase: Phrase, index: int, total: int) -> int:
    return max(1, min(phrase.end_index, total - 1) - index + 1)


def _natural_span(candidates: list[PatternCandidate], index: int, config: AssistantConfig) -> int:
    max_gap = {Difficulty.EZ: 0.42, Difficulty.HD: 0.30, Difficulty.IN: 0.22, Difficulty.AT: 0.18}[config.difficulty]
    limit = {Difficulty.EZ: 2, Difficulty.HD: 3, Difficulty.IN: 5, Difficulty.AT: 7}[config.difficulty]
    count = 1
    while index + count < len(candidates) and count < limit:
        if candidates[index + count].time - candidates[index + count - 1].time > max_gap:
            break
        count += 1
    return count


def _choose_pattern(
    candidates: list[PatternCandidate],
    index: int,
    span: int,
    phrase: Phrase | None,
    config: AssistantConfig,
    previous_name: str,
    same_name_run: int,
) -> str:
    window = candidates[index : index + span]
    section = candidates[index].section
    avg_accent = mean(item.accent.accent_score for item in window)
    avg_hat = mean(item.accent.hat_score for item in window)
    avg_onset = mean(item.accent.onset_score for item in window)
    if phrase:
        label = phrase.label
        if label == "Drag Chain":
            name = "Drag Chain"
        elif label == "Hold Phrase":
            if avg_onset <= 0.22 and avg_hat <= 0.34 and avg_accent <= (0.46 if config.difficulty == Difficulty.AT else 0.55):
                name = "Hold Anchor"
            else:
                name = "Single" if span <= 1 else "Alternating"
        elif label == "Accent Phrase":
            name = "Jump"
        elif label == "Burst":
            name = "Burst"
        elif label == "Build":
            name = "Stair" if config.difficulty in {Difficulty.IN, Difficulty.AT} else "Alternating"
        elif label == "Outro":
            name = "Alternating"
        else:
            name = _stream_pattern(span, config, avg_hat, avg_onset)
    elif span <= 1:
        name = "Single" if avg_accent < 0.72 else "Jump"
    else:
        name = _stream_pattern(span, config, avg_hat, avg_onset)
    if config.difficulty == Difficulty.AT:
        if section == "Drop" and span >= 4 and name in {"Single", "Double", "Alternating"}:
            name = "Burst"
        elif avg_hat >= 0.58 and span >= 3 and config.enable_drag:
            name = "Drag Chain"
        elif span >= 5 and name == "Alternating":
            name = "Stream"
    if same_name_run >= 4 and name == previous_name:
        name = _alternate_pattern(name, span, config)
    return name


def _stream_pattern(span: int, config: AssistantConfig, avg_hat: float, avg_onset: float) -> str:
    if span >= 6 and config.difficulty == Difficulty.AT:
        return "Stream" if avg_hat < 0.62 else "Drag Chain"
    if span >= 5:
        return "Burst" if avg_onset >= 0.45 else "Stair"
    if span == 4:
        return "Quad" if config.difficulty in {Difficulty.IN, Difficulty.AT} else "Alternating"
    if span == 3:
        return "Triple"
    if span == 2:
        return "Double" if config.difficulty in {Difficulty.EZ, Difficulty.HD} else "Trill"
    return "Single"


def _alternate_pattern(name: str, span: int, config: AssistantConfig) -> str:
    alternatives = {
        "Single": "Alternating",
        "Double": "Trill",
        "Triple": "Stair",
        "Quad": "Alternating",
        "Alternating": "Stair" if config.difficulty in {Difficulty.IN, Difficulty.AT} else "Double",
        "Stair": "Stream" if span >= 5 else "Alternating",
        "Burst": "Stair",
        "Stream": "Burst",
        "Drag Chain": "Stream",
        "Jump": "Anchor",
    }
    return alternatives.get(name, "Alternating")


def _diversity_score(histogram: dict[str, int], total: int, longest_same: int) -> float:
    if total <= 0:
        return 0.0
    variety = len(histogram) / max(1, min(total, 10))
    balance = 1.0 - max(histogram.values(), default=0) / max(1, total)
    penalty = max(0.0, longest_same - 4) * 0.055
    return max(0.0, min(100.0, (0.58 * variety + 0.42 * balance - penalty) * 100.0))
