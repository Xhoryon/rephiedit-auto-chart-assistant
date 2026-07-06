from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import mean
from typing import Any

from .config import AssistantConfig, Difficulty
from .pattern_generator import PatternBlock
from .timebase import beat_tuple_to_beats

LANES = [-540.0, -405.0, -270.0, -135.0, 0.0, 135.0, 270.0, 405.0, 540.0]
PATTERN_LANES: dict[str, list[float]] = {
    "Single": [-270.0, 270.0, 0.0, -405.0, 405.0],
    "Double": [-270.0, 270.0, -405.0, 405.0],
    "Triple": [-270.0, 0.0, 270.0, -405.0, 0.0, 405.0],
    "Quad": [-405.0, -135.0, 135.0, 405.0],
    "Alternating": [-405.0, 405.0, -270.0, 270.0, -135.0, 135.0],
    "Stair": [-540.0, -270.0, 0.0, 270.0, 540.0],
    "Jump": [-540.0, 540.0, -405.0, 405.0],
    "Burst": [-540.0, -270.0, 270.0, 540.0, 0.0, 405.0],
    "Stream": [-405.0, 405.0, -270.0, 270.0, -135.0, 135.0, -540.0, 540.0],
    "Anchor": [-405.0, 405.0, 0.0, 405.0],
    "Jack": [-270.0, -270.0, 270.0, 270.0],
    "Trill": [-270.0, 270.0, -270.0, 270.0],
    "Drag Chain": [-540.0, -405.0, -270.0, -135.0, 0.0, 135.0, 270.0, 405.0, 540.0],
    "Hold Anchor": [-540.0, 540.0, -405.0, 405.0, 0.0],
}


@dataclass
class LayoutState:
    previous_lane: float | None = None
    same_lane_run: int = 0
    side_run: int = 0
    previous_side: int = 0
    counts: Counter[float] | None = None

    def __post_init__(self) -> None:
        if self.counts is None:
            self.counts = Counter()


def lane_for_pattern(block: PatternBlock | None, local_index: int, note_type: int, state: LayoutState, config: AssistantConfig) -> float:
    pattern = PATTERN_LANES.get(block.name if block else "Single", PATTERN_LANES["Single"])
    phase = (block.start_index if block else 0) % len(pattern)
    raw = pattern[(local_index + phase) % len(pattern)]
    lane = _rebalance_lane(raw, note_type, state, config)
    _remember(lane, state)
    return lane


def compute_layout_report(notes: list[dict[str, Any]]) -> dict[str, Any]:
    lanes = [float(note.get("positionX", 0.0)) for note in sorted(notes, key=lambda n: beat_tuple_to_beats(n.get("startTime", [0, 0, 1])))]
    if not lanes:
        return {
            "layout_diversity_score": 0.0,
            "playability_score": 0.0,
            "average_jump_distance": 0.0,
            "hand_alternation_score": 0.0,
            "lane_distribution": {},
            "longest_same_lane": 0,
            "layout_validator_warnings": [],
        }
    distribution = Counter(_lane_bucket(lane) for lane in lanes)
    longest_same = _longest_same(lanes)
    jumps = [abs(b - a) for a, b in zip(lanes, lanes[1:])]
    avg_jump = mean(jumps) if jumps else 0.0
    sides = [_side(lane) for lane in lanes if _side(lane) != 0]
    alternations = sum(1 for a, b in zip(sides, sides[1:]) if a != b)
    hand_alt = alternations / max(1, len(sides) - 1) * 100.0 if len(sides) > 1 else 60.0
    used_ratio = len(distribution) / max(1, min(9, len(lanes)))
    max_bucket = max(distribution.values()) / max(1, len(lanes))
    layout_diversity = max(0.0, min(100.0, 72.0 * used_ratio + 38.0 * (1.0 - max_bucket) - max(0, longest_same - 4) * 7.0))
    jump_penalty = max(0.0, avg_jump - 520.0) * 0.055
    same_penalty = max(0, longest_same - 4) * 8.0
    side_penalty = max(0.0, 45.0 - hand_alt) * 0.42
    playability = max(0.0, min(100.0, 92.0 - jump_penalty - same_penalty - side_penalty))
    warnings = validate_layout(notes)
    if warnings:
        playability = max(0.0, playability - 10.0 * len(warnings))
    return {
        "layout_diversity_score": round(layout_diversity, 3),
        "playability_score": round(playability, 3),
        "average_jump_distance": round(avg_jump, 3),
        "hand_alternation_score": round(hand_alt, 3),
        "lane_distribution": {str(key): value for key, value in sorted(distribution.items())},
        "longest_same_lane": longest_same,
        "layout_validator_warnings": warnings,
    }


def validate_layout(notes: list[dict[str, Any]]) -> list[str]:
    report = _basic_metrics(notes)
    warnings: list[str] = []
    if report["longest_same_lane"] > 8:
        warnings.append("long same-lane run")
    if report["used_lanes"] < min(4, report["note_count"]):
        warnings.append("too few lanes used")
    if report["max_lane_ratio"] > 0.45 and report["note_count"] >= 12:
        warnings.append("lane distribution too concentrated")
    return warnings


def _rebalance_lane(raw: float, note_type: int, state: LayoutState, config: AssistantConfig) -> float:
    lane = raw
    counts = state.counts or Counter()
    total = sum(counts.values())
    if note_type == 2 and abs(lane) < 360:
        lane = -540.0 if counts[-540.0] <= counts[540.0] else 540.0
    if total >= 8 and counts[lane] / max(1, total) > 0.25:
        lane = _least_used_lane(counts, prefer_side=-_side(lane))
    if state.previous_lane is not None and abs(lane - state.previous_lane) < 1e-6 and state.same_lane_run >= 2:
        lane = _least_used_lane(counts, prefer_side=-state.previous_side if state.previous_side else 1)
    side = _side(lane)
    if side != 0 and state.previous_side == side and state.side_run >= 5:
        lane = _least_used_lane(counts, prefer_side=-side)
    if state.previous_lane is not None and abs(lane - state.previous_lane) > _jump_limit(config):
        lane = _closer_lane(state.previous_lane, lane, counts)
    return lane


def _remember(lane: float, state: LayoutState) -> None:
    if state.previous_lane is not None and abs(lane - state.previous_lane) < 1e-6:
        state.same_lane_run += 1
    else:
        state.same_lane_run = 1
    side = _side(lane)
    if side != 0 and side == state.previous_side:
        state.side_run += 1
    elif side != 0:
        state.side_run = 1
    state.previous_side = side or state.previous_side
    state.previous_lane = lane
    assert state.counts is not None
    state.counts[lane] += 1


def _least_used_lane(counts: Counter[float], prefer_side: int = 0) -> float:
    candidates = LANES if prefer_side == 0 else [lane for lane in LANES if _side(lane) == prefer_side] or LANES
    return min(candidates, key=lambda lane: (counts[lane], abs(abs(lane) - 405.0), abs(lane)))


def _closer_lane(previous: float, desired: float, counts: Counter[float]) -> float:
    direction = 1 if desired > previous else -1
    candidates = [lane for lane in LANES if lane * direction >= previous * direction]
    if not candidates:
        candidates = LANES
    return min(candidates, key=lambda lane: (abs(lane - previous), counts[lane]))


def _jump_limit(config: AssistantConfig) -> float:
    return {Difficulty.EZ: 720.0, Difficulty.HD: 760.0, Difficulty.IN: 900.0, Difficulty.AT: 1080.0}[config.difficulty]


def _side(lane: float) -> int:
    if lane < -1e-6:
        return -1
    if lane > 1e-6:
        return 1
    return 0


def _lane_bucket(lane: float) -> int:
    return int(round(lane / 135.0))


def _longest_same(lanes: list[float]) -> int:
    longest = 0
    run = 0
    previous: float | None = None
    for lane in lanes:
        if previous is not None and abs(lane - previous) < 1e-6:
            run += 1
        else:
            run = 1
            previous = lane
        longest = max(longest, run)
    return longest


def _basic_metrics(notes: list[dict[str, Any]]) -> dict[str, float]:
    lanes = [float(note.get("positionX", 0.0)) for note in notes]
    distribution = Counter(_lane_bucket(lane) for lane in lanes)
    return {
        "note_count": len(notes),
        "used_lanes": len(distribution),
        "max_lane_ratio": max(distribution.values(), default=0) / max(1, len(notes)),
        "longest_same_lane": _longest_same(lanes),
    }
