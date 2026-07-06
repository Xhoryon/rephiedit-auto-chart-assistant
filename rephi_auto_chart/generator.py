from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean
from typing import Any, Dict

from .accent import AccentFeatures, accent_summary, detect_accent_at
from .analysis import AudioAnalysis
from .config import AssistantConfig, Difficulty
from .layout import LayoutState, compute_layout_report, lane_for_pattern, validate_layout
from .pattern_generator import (
    PatternBlock,
    build_pattern_plan,
    note_type_for_pattern,
    pattern_for_index,
    pattern_summary,
    validate_pattern_plan,
)
from .phrases import Phrase, generate_phrases, phrase_for_index, phrase_summary
from .quality import evaluate_chart_quality
from .timebase import seconds_to_beat_tuple
from .timing import TimingCalibration, build_timing_calibration, correct_timing
from .validator import validate_and_fix_chart


LANES = [-540.0, -405.0, -270.0, -135.0, 0.0, 135.0, 270.0, 405.0, 540.0]
PATTERNS = {
    "simple": [-270.0, 270.0],
    "alternate": [-405.0, 405.0, -270.0, 270.0],
    "stair": [-540.0, -270.0, 0.0, 270.0, 540.0],
    "triple": [-270.0, 0.0, 270.0],
    "four": [-405.0, -135.0, 135.0, 405.0],
    "wide": [-540.0, 540.0, -405.0, 405.0],
    "burst": [-540.0, -270.0, 270.0, 540.0, 0.0, 405.0],
    "drop": [-540.0, -270.0, 0.0, 270.0, 540.0, 270.0, 0.0, -270.0],
}


@dataclass(frozen=True)
class Candidate:
    time: float
    raw_time: float
    score: float
    section: str
    accent: AccentFeatures
    source: str
    attack_delta_ms: float
    snap_delta_ms: float


@dataclass
class TypeDecision:
    selected_type: int
    type_reason: str
    tap_score: float
    hold_score: float
    flick_score: float
    drag_score: float


def generate_chart(analysis: AudioAnalysis, config: AssistantConfig, song_filename: str | None = None) -> Dict[str, Any]:
    first = _generate_chart_once(analysis, config, song_filename)
    first_quality = first.get("META", {}).get("autoChartReport", {}).get("quality_score", {}).get("Overall", 100.0)
    if first_quality >= 80.0:
        return first
    retry_config = replace(config, overall_density=min(1.8, config.overall_density * 1.06), chart_style="Balanced")
    second = _generate_chart_once(analysis, retry_config, song_filename)
    second_quality = second.get("META", {}).get("autoChartReport", {}).get("quality_score", {}).get("Overall", 0.0)
    if second_quality > first_quality:
        second["META"]["autoChartReport"]["quality_retry"] = {"used": True, "first_overall": first_quality, "second_overall": second_quality}
        return second
    first["META"]["autoChartReport"]["quality_retry"] = {"used": False, "first_overall": first_quality, "second_overall": second_quality}
    return first


def _generate_chart_once(analysis: AudioAnalysis, config: AssistantConfig, song_filename: str | None = None) -> Dict[str, Any]:
    preset = config.preset
    calibration = build_timing_calibration(
        analysis,
        auto=config.auto_timing_calibration,
        manual_offset_ms=config.manual_offset_ms + config.offset_ms,
        snap_strength=config.snap_strength,
    )
    candidates = _build_candidates(analysis, config, calibration)
    target = _density_target(analysis, config)
    selected = _select_candidates(candidates, config, target)
    before_fill = len(selected)
    selected = _backfill_candidates(selected, candidates, config, target)
    filler_summary = {"added_notes": len(selected) - before_fill, "strategy": "accent_onset_grid_energy_pattern"}
    selected = sorted(selected, key=lambda item: item.time)
    phrases = generate_phrases(selected, analysis, config)
    pattern_plan = build_pattern_plan(selected, phrases, config)
    notes, decisions = _make_notes(selected, analysis, config, phrases, pattern_plan)
    ratio_fixes = _enforce_type_ratios(notes, decisions, config)
    _ensure_all_types(notes, selected, analysis, config)
    _add_sustain_hold_if_supported(notes, analysis, config)
    ratio_fixes.update(_enforce_hold_playability(notes, decisions, analysis, config))
    _avoid_same_time_same_bucket(notes, analysis, config)
    ratio_fixes.update(_enforce_hold_playability(notes, decisions, analysis, config))
    chart = _base_chart(analysis, config, song_filename or Path(analysis.path).name)
    chart["judgeLineList"][0]["notes"] = notes
    chart["META"]["autoChartReport"] = _quality_report(analysis, config, selected, notes, decisions, phrases, pattern_plan, target, calibration, filler_summary, ratio_fixes)
    fixed, validation_report = validate_and_fix_chart(chart, max_hold_duration_seconds=config.max_hold_duration)
    _refresh_final_note_metrics(fixed["META"]["autoChartReport"], fixed, analysis, validation_report)
    fixed["META"]["autoChartReport"]["quality_score"] = evaluate_chart_quality(fixed["META"]["autoChartReport"])
    return fixed


def _build_candidates(analysis: AudioAnalysis, config: AssistantConfig, calibration: TimingCalibration) -> list[Candidate]:
    raw: list[tuple[float, str]] = [(time, "onset") for time in analysis.onsets]
    beat_interval = 60.0 / max(1.0, analysis.bpm)
    subdivisions = {
        Difficulty.EZ: (1, 2),
        Difficulty.HD: (1, 2, 4),
        Difficulty.IN: (1, 2, 4, 8),
        Difficulty.AT: (1, 2, 3, 4, 8, 12, 16),
    }[config.difficulty]
    beat_start = analysis.beats[0] if analysis.beats else 0.0
    for division in subdivisions:
        step = beat_interval / division
        t = beat_start
        while t <= analysis.duration + 0.001:
            raw.append((t, f"grid_1/{division}"))
            t += step
    merged: dict[float, tuple[float, str]] = {}
    for time_seconds, source in raw:
        if not 0 <= time_seconds <= analysis.duration:
            continue
        key = round(time_seconds, 3)
        previous = merged.get(key)
        if previous is None or source == "onset":
            merged[key] = (time_seconds, source)

    candidates: list[Candidate] = []
    for raw_time, source in merged.values():
        correction = correct_timing(raw_time, analysis, calibration)
        time_seconds = correction.final_time
        scored_time = max(0.0, min(analysis.duration, correction.snapped_time))
        section = _section_at(analysis.sections, scored_time)
        accent = detect_accent_at(analysis, scored_time)
        score = _candidate_score(analysis, scored_time, source, section, accent, config)
        candidates.append(
            Candidate(
                time=round(time_seconds, 6),
                raw_time=raw_time,
                score=score,
                section=section,
                accent=accent,
                source=source,
                attack_delta_ms=correction.attack_delta_ms,
                snap_delta_ms=correction.snap_delta_ms,
            )
        )
    unique: dict[float, Candidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        unique.setdefault(round(candidate.time, 3), candidate)
    return sorted(unique.values(), key=lambda item: item.time)


def _candidate_score(
    analysis: AudioAnalysis,
    time_seconds: float,
    source: str,
    section: str,
    accent: AccentFeatures,
    config: AssistantConfig,
) -> float:
    preset = config.preset
    source_bonus = 0.24 if source == "onset" else 0.12 if source in {"grid_1/1", "grid_1/2"} else 0.04
    section_bonus = _section_density(section, preset) - 1.0
    nearby = min((abs(time_seconds - onset) for onset in analysis.onsets), default=9.0)
    onset_bonus = max(0.0, 0.16 - nearby) if nearby < 0.16 else 0.0
    return (
        0.42 * accent.accent_score
        + 0.20 * accent.kick_score
        + 0.14 * accent.snare_score
        + 0.10 * accent.hat_score
        + source_bonus
        + 0.18 * section_bonus
        + onset_bonus
    )


def _density_target(analysis: AudioAnalysis, config: AssistantConfig) -> dict[str, float]:
    preset = config.preset
    duration = max(analysis.duration, 0.001)
    total_beats = duration * analysis.bpm / 60.0
    avg_energy = mean(analysis.energy_curve) if analysis.energy_curve else 0.0
    section_multiplier = _average_section_multiplier(analysis, preset)
    rhythmic_complexity = min(2.4, max(0.35, len(analysis.onsets) / max(1.0, total_beats)))
    style_multiplier = _style_density_multiplier(config.chart_style)
    bpm_factor = 1.18 if analysis.bpm < 115 else 0.92 if analysis.bpm > 185 else 1.0
    subdivision_density = float(preset["subdivision_density"]) * bpm_factor
    difficulty_multiplier = float(preset["difficulty_multiplier"])
    target_notes_from_bpm = total_beats * subdivision_density * difficulty_multiplier * section_multiplier
    onset_multiplier = {Difficulty.EZ: 0.46, Difficulty.HD: 0.88, Difficulty.IN: 1.30, Difficulty.AT: 1.95}[config.difficulty]
    target_notes_from_onsets = len(analysis.onsets) * onset_multiplier * (0.80 + 0.20 * rhythmic_complexity)
    target_notes_from_energy = total_beats * difficulty_multiplier * (0.42 + avg_energy * 0.95) * section_multiplier
    target_count = int(
        round(
            (
                target_notes_from_bpm * 0.46
                + target_notes_from_onsets * 0.36
                + target_notes_from_energy * 0.18
            )
            * config.overall_density
            * style_multiplier
        )
    )
    minimum = int(max(1.0, target_notes_from_bpm * 0.58 * config.overall_density * style_multiplier))
    target_count = max(minimum, target_count)
    playable_cap = int(duration / max(0.001, config.effective_min_interval) * 0.86)
    preset_cap = int(float(preset["max_notes_per_second"]) * duration)
    target_count = min(target_count, max(1, playable_cap), max(1, preset_cap))
    return {
        "target_nps": round(target_count / duration, 3),
        "song_length": round(duration, 3),
        "bpm": round(analysis.bpm, 3),
        "total_beats": round(total_beats, 3),
        "onset_count": float(len(analysis.onsets)),
        "section_intensity": round(section_multiplier, 3),
        "music_energy": round(avg_energy, 3),
        "rhythmic_complexity": round(rhythmic_complexity, 3),
        "target_notes_from_bpm": round(target_notes_from_bpm, 3),
        "target_notes_from_onsets": round(target_notes_from_onsets, 3),
        "target_notes_from_energy": round(target_notes_from_energy, 3),
        "target_notes_final": float(max(1, target_count)),
        "target_count": float(max(1, target_count)),
        "actual_notes": 0.0,
    }


def _select_candidates(candidates: list[Candidate], config: AssistantConfig, target: dict[str, float]) -> list[Candidate]:
    if not candidates:
        return []
    target_count = int(target["target_count"])
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    selected: list[Candidate] = []
    for candidate in ranked:
        if len(selected) >= target_count:
            break
        if _can_place(candidate, selected, config.effective_min_interval):
            selected.append(candidate)
    return selected


def _backfill_candidates(
    selected: list[Candidate],
    candidates: list[Candidate],
    config: AssistantConfig,
    target: dict[str, float],
) -> list[Candidate]:
    target_count = int(target["target_count"])
    floor = min(target_count, int(target_count * 0.92))
    if len(selected) >= floor:
        return selected
    used = {round(candidate.time, 3) for candidate in selected}
    backfill_interval = max(0.045, config.effective_min_interval * 0.72)
    for candidate in sorted(candidates, key=lambda item: (item.section != "Drop", -item.score, item.time)):
        if len(selected) >= target_count:
            break
        if round(candidate.time, 3) in used:
            continue
        if _can_place(candidate, selected, backfill_interval):
            selected.append(candidate)
            used.add(round(candidate.time, 3))
    return selected


def _average_section_multiplier(analysis: AudioAnalysis, preset: dict[str, float]) -> float:
    if not analysis.sections or analysis.duration <= 0:
        return 1.0
    weighted = 0.0
    for start, end, label in analysis.sections:
        weighted += max(0.0, end - start) * _section_density(label, preset)
    return max(0.55, min(1.85, weighted / max(analysis.duration, 0.001)))


def _style_density_multiplier(style: str) -> float:
    return {
        "Official-like": 0.94,
        "Balanced": 1.0,
        "Dense": 1.14,
        "Experimental": 1.24,
    }.get(style, 0.94)


def _can_place(candidate: Candidate, selected: list[Candidate], interval: float) -> bool:
    return all(abs(candidate.time - other.time) >= interval for other in selected)


def _make_notes(
    selected: list[Candidate],
    analysis: AudioAnalysis,
    config: AssistantConfig,
    phrases: list[Phrase],
    pattern_plan: list[PatternBlock],
) -> tuple[list[Dict[str, Any]], list[TypeDecision]]:
    notes: list[Dict[str, Any]] = []
    decisions: list[TypeDecision] = []
    layout_state = LayoutState()
    last_flick_time = -999.0
    consecutive_flicks = 0
    for index, candidate in enumerate(selected):
        previous_time = selected[index - 1].time if index > 0 else None
        next_time = selected[index + 1].time if index + 1 < len(selected) else None
        phrase = phrase_for_index(phrases, index)
        block = pattern_for_index(pattern_plan, index)
        decision = _classify_note_type(candidate, previous_time, next_time, analysis, config, index, last_flick_time, consecutive_flicks, phrase)
        local_index = index - block.start_index if block else 0
        note_type = note_type_for_pattern(block, local_index, decision.selected_type, config)
        if note_type != decision.selected_type:
            decision.selected_type = note_type
            decision.type_reason = f"pattern {block.name if block else 'Single'} selected {note_type}"
        if note_type == 4:
            consecutive_flicks += 1
            last_flick_time = candidate.time
        else:
            consecutive_flicks = 0
        lane = lane_for_pattern(block, local_index, note_type, layout_state, config)
        notes.append(_make_note(note_type, candidate.time, lane, analysis, config))
        decisions.append(decision)
    return notes, decisions


def _classify_note_type(
    candidate: Candidate,
    previous_time: float | None,
    next_time: float | None,
    analysis: AudioAnalysis,
    config: AssistantConfig,
    combo_index: int,
    last_flick_time: float,
    consecutive_flicks: int,
    phrase: Phrase | None,
) -> TypeDecision:
    accent = candidate.accent
    near_prev = previous_time is not None and candidate.time - previous_time <= 0.23
    near_next = next_time is not None and next_time - candidate.time <= 0.23
    continuous = near_prev or near_next
    in_long = _long_region_at(candidate.time, analysis)
    min_hold = 0.48 if config.difficulty in {Difficulty.EZ, Difficulty.HD} else 0.36
    tap_score = _clamp(0.58 + 0.22 * accent.kick_score + 0.14 * accent.onset_score + 0.06 * _beat_score(candidate, analysis))
    hold_score = 0.0
    flick_score = 0.0
    drag_score = 0.0

    if phrase and phrase.label == "Drag Chain":
        return TypeDecision(3, f"phrase drag chain: {phrase.pattern}", tap_score, 0.0, 0.0, max(config.drag_evidence_threshold, 0.82))
    if phrase and phrase.label == "Hold Phrase" and config.enable_hold:
        hold_score = _hold_evidence(candidate, previous_time, next_time, analysis, config, combo_index)
        threshold = 0.84 if config.difficulty == Difficulty.AT else 0.78
        if hold_score >= threshold:
            return TypeDecision(2, "phrase hold: strong sustain evidence with low transient density", tap_score, hold_score, 0.0, 0.0)
    if phrase and phrase.label == "Accent Phrase" and config.enable_flick and candidate.time - last_flick_time >= 0.34:
        return TypeDecision(4, "phrase accent: section accent/crash/snare emphasis", tap_score, 0.0, 0.86, 0.0)

    if config.enable_hold and in_long and in_long[1] - candidate.time >= min_hold and not continuous and _is_hold_anchor(candidate, analysis, combo_index):
        hold_score = _hold_evidence(candidate, previous_time, next_time, analysis, config, combo_index)
    flick_threshold = {Difficulty.EZ: 0.90, Difficulty.HD: 0.84, Difficulty.IN: 0.78, Difficulty.AT: 0.73}[config.difficulty]
    flick_gap = {Difficulty.EZ: 1.10, Difficulty.HD: 0.72, Difficulty.IN: 0.46, Difficulty.AT: 0.34}[config.difficulty]
    if config.enable_flick and candidate.time - last_flick_time >= flick_gap and consecutive_flicks < 2:
        strong_drop = candidate.section == "Drop" and config.difficulty in {Difficulty.IN, Difficulty.AT} and accent.accent_score >= flick_threshold - 0.10
        flick_score = _clamp(0.48 * accent.accent_score + 0.28 * accent.snare_score + 0.16 * accent.high_energy + (0.18 if strong_drop else 0.0))
    drag_score = _drag_evidence(candidate, previous_time, next_time, config)
    style = config.chart_style
    if style == "Experimental":
        drag_score += 0.08
        flick_score += 0.04
    elif style == "Dense":
        drag_score += 0.04
    elif style == "Official-like":
        drag_score -= 0.06
        flick_score -= 0.03

    hold_threshold = 0.84 if config.difficulty == Difficulty.AT else 0.76
    if hold_score >= hold_threshold and hold_score > tap_score + 0.08:
        return TypeDecision(2, "sustained energy region with low transient density", tap_score, hold_score, flick_score, max(0.0, drag_score))
    if flick_score >= flick_threshold and flick_score > tap_score + 0.10:
        return TypeDecision(4, "strong accent/drop/snare/crash evidence", tap_score, hold_score, flick_score, max(0.0, drag_score))
    if config.enable_drag and _drag_allowed(drag_score, candidate, previous_time, next_time, config):
        return TypeDecision(3, "hat roll or decorative drag-chain evidence", tap_score, hold_score, flick_score, max(0.0, drag_score))
    reason = "default tap: kick/main beat/onset rhythm"
    if continuous:
        reason = "default tap stream: continuous ordinary rhythm"
    return TypeDecision(1, reason, tap_score, hold_score, flick_score, max(0.0, drag_score))


def _drag_evidence(candidate: Candidate, previous_time: float | None, next_time: float | None, config: AssistantConfig) -> float:
    accent = candidate.accent
    prev_gap = candidate.time - previous_time if previous_time is not None else 999.0
    next_gap = next_time - candidate.time if next_time is not None else 999.0
    tight_chain = min(prev_gap, next_gap) <= 0.13 and max(prev_gap if prev_gap < 999 else 0.0, next_gap if next_gap < 999 else 0.0) <= 0.24
    hat_roll = accent.hat_score >= 0.68 and accent.high_energy >= 0.42 and tight_chain
    decorative = config.difficulty in {Difficulty.IN, Difficulty.AT} and candidate.section == "Drop" and accent.hat_score >= 0.72
    score = 0.34 * accent.hat_score + 0.24 * accent.high_energy + 0.18 * accent.onset_score
    if tight_chain:
        score += 0.12
    if hat_roll:
        score += 0.18
    if decorative:
        score += 0.08
    score *= max(0.1, config.drag_weight)
    return _clamp(score)


def _drag_allowed(score: float, candidate: Candidate, previous_time: float | None, next_time: float | None, config: AssistantConfig) -> bool:
    if config.drag_requires_evidence and score < config.drag_evidence_threshold:
        return False
    has_neighbor = (previous_time is not None and candidate.time - previous_time <= 0.18) or (next_time is not None and next_time - candidate.time <= 0.18)
    return has_neighbor and score >= max(0.50, config.drag_evidence_threshold)


def _beat_score(candidate: Candidate, analysis: AudioAnalysis) -> float:
    if not analysis.beats:
        return 0.0
    nearest = min(abs(candidate.time - beat) for beat in analysis.beats)
    return 1.0 if nearest <= 0.055 else 0.0


def _is_hold_anchor(candidate: Candidate, analysis: AudioAnalysis, combo_index: int) -> bool:
    beat = 60.0 / max(1.0, analysis.bpm)
    if beat <= 0:
        return combo_index % 6 == 0
    beat_index = round((candidate.time - (analysis.beats[0] if analysis.beats else 0.0)) / beat)
    return beat_index % 4 == 0 and combo_index % 3 == 0


def _hold_evidence(
    candidate: Candidate,
    previous_time: float | None,
    next_time: float | None,
    analysis: AudioAnalysis,
    config: AssistantConfig,
    combo_index: int,
) -> float:
    region = _long_region_at(candidate.time, analysis)
    if region is None:
        return 0.0
    remaining = max(0.0, region[1] - candidate.time)
    if remaining < (0.58 if config.difficulty == Difficulty.AT else 0.45):
        return 0.0
    prev_gap = candidate.time - previous_time if previous_time is not None else 999.0
    next_gap = next_time - candidate.time if next_time is not None else 999.0
    transient_density_penalty = 0.0
    if min(prev_gap, next_gap) <= (0.38 if config.difficulty == Difficulty.AT else 0.28):
        transient_density_penalty += 0.22
    accent = candidate.accent
    transient_score = max(accent.onset_score, accent.hat_score * 0.85, accent.kick_score * 0.70, accent.snare_score * 0.65)
    sustain_strength = min(1.0, remaining / max(0.75, config.max_hold_duration))
    score = 0.38 + 0.20 * accent.energy_score + 0.25 * (1.0 - accent.onset_score) + 0.18 * sustain_strength
    score -= 0.34 * transient_score + transient_density_penalty
    if candidate.section == "Drop" and config.difficulty in {Difficulty.IN, Difficulty.AT}:
        score -= 0.08
    if config.difficulty == Difficulty.AT and not _is_hold_anchor(candidate, analysis, combo_index):
        score -= 0.10
    score *= max(0.1, config.hold_weight)
    return _clamp(score)


def _enforce_type_ratios(notes: list[Dict[str, Any]], decisions: list[TypeDecision], config: AssistantConfig) -> dict[str, float]:
    if not notes:
        return {"drag_to_tap": 0.0, "isolated_drag_to_tap": 0.0, "hold_to_tap": 0.0}
    max_drag_ratio = float(config.preset["max_drag_ratio"])
    converted = 0
    isolated = 0
    hold_converted = 0
    for index, note in enumerate(notes):
        if note["type"] != 3:
            continue
        prev_drag = index > 0 and notes[index - 1]["type"] == 3
        next_drag = index + 1 < len(notes) and notes[index + 1]["type"] == 3
        is_phrase_drag = index < len(decisions) and decisions[index].type_reason.startswith("phrase drag chain")
        if not prev_drag and not next_drag and not is_phrase_drag:
            note["type"] = 1
            if index < len(decisions):
                decisions[index].selected_type = 1
                decisions[index].type_reason = "drag downgraded to tap: isolated drag"
            isolated += 1
    allowed = max(0, int(len(notes) * max_drag_ratio))
    drag_indexes = [index for index, note in enumerate(notes) if note["type"] == 3]
    if len(drag_indexes) > allowed:
        ranked = sorted(drag_indexes, key=lambda index: decisions[index].drag_score if index < len(decisions) else 0.0)
        for index in ranked[: len(drag_indexes) - allowed]:
            notes[index]["type"] = 1
            if index < len(decisions):
                decisions[index].selected_type = 1
                decisions[index].type_reason = "drag downgraded to tap: difficulty drag ratio cap"
            converted += 1
    allowed_holds = max(0, int(len(notes) * config.max_hold_ratio))
    hold_indexes = [index for index, note in enumerate(notes) if note["type"] == 2]
    if len(hold_indexes) > allowed_holds:
        ranked_holds = sorted(hold_indexes, key=lambda index: decisions[index].hold_score if index < len(decisions) else 0.0)
        for index in ranked_holds[: len(hold_indexes) - allowed_holds]:
            notes[index]["type"] = 1
            notes[index]["endTime"] = list(notes[index]["startTime"])
            if index < len(decisions):
                decisions[index].selected_type = 1
                decisions[index].type_reason = "hold downgraded to tap: difficulty hold ratio cap"
            hold_converted += 1
    return {"drag_to_tap": float(converted), "isolated_drag_to_tap": float(isolated), "max_drag_ratio": max_drag_ratio, "hold_to_tap": float(hold_converted), "max_hold_ratio": config.max_hold_ratio}


def _make_note(note_type: int, t: float, x: float, analysis: AudioAnalysis, config: AssistantConfig) -> Dict[str, Any]:
    start = seconds_to_beat_tuple(t, analysis.bpm, config.max_bpm_precision)
    end = list(start)
    if note_type == 2:
        length = _hold_length(t, analysis, config)
        end = seconds_to_beat_tuple(min(analysis.duration, t + length), analysis.bpm, config.max_bpm_precision)
    return {
        "above": 1,
        "alpha": 255,
        "endTime": end,
        "isFake": 0,
        "positionX": x,
        "size": 1.0,
        "speed": 1.0,
        "startTime": start,
        "type": note_type,
        "visibleTime": 999999.0,
        "yOffset": 0.0,
    }


def _hold_length(t: float, analysis: AudioAnalysis, config: AssistantConfig) -> float:
    max_length = config.max_hold_duration
    min_length = 0.28 if config.difficulty == Difficulty.AT else 0.36
    for start, end in analysis.long_regions:
        if start <= t <= end:
            return max(min_length, min(max_length, end - t))
    beat = 60.0 / max(1.0, analysis.bpm)
    natural = beat * (1.0 if config.difficulty in {Difficulty.IN, Difficulty.AT} else 0.85)
    return max(min_length, min(max_length, natural))


def _ensure_all_types(notes: list[Dict[str, Any]], selected: list[Candidate], analysis: AudioAnalysis, config: AssistantConfig) -> None:
    if config.difficulty != Difficulty.AT:
        return
    present = {note["type"] for note in notes}
    anchors = selected or [
        Candidate(t, t, 0.0, _section_at(analysis.sections, t), detect_accent_at(analysis, t), "fallback", 0.0, 0.0)
        for t in (analysis.beats or [0.0, 0.5, 1.0, 1.5])[:4]
    ]
    required = [1]
    if config.enable_drag:
        required.append(3)
    if config.enable_flick:
        required.append(4)
    for note_type in required:
        if note_type not in present and anchors:
            anchor = anchors[min(len(anchors) - 1, note_type - 1)]
            notes.append(_make_note(note_type, anchor.time, LANES[min(len(LANES) - 1, note_type + 2)], analysis, config))


def _add_sustain_hold_if_supported(notes: list[Dict[str, Any]], analysis: AudioAnalysis, config: AssistantConfig) -> None:
    if not config.enable_hold or any(note.get("type") == 2 for note in notes):
        return
    if not analysis.long_regions:
        return
    candidate_regions = sorted(analysis.long_regions, key=lambda region: region[1] - region[0], reverse=True)
    max_count = max(1, int(len(notes) * config.max_hold_ratio))
    if max_count <= 0:
        return
    for start, end in candidate_regions:
        if end - start < (1.25 if config.difficulty == Difficulty.AT else 0.9):
            continue
        length = min(config.max_hold_duration, end - start, 1.25 if config.difficulty == Difficulty.AT else config.max_hold_duration)
        if length < 0.42:
            continue
        anchor_times = [start + 0.15, start + (end - start) * 0.25, max(start, end - length - 0.15)]
        for t in anchor_times:
            t = max(start, min(end - length, t))
            if t < 0 or t + length > analysis.duration + 0.001:
                continue
            for lane in (-540.0, 540.0, -405.0, 405.0, 0.0):
                if _hold_lane_is_clear(notes, lane, t, t + length, analysis):
                    notes.append(_make_note(2, t, lane, analysis, config))
                    return


def _hold_lane_is_clear(notes: list[Dict[str, Any]], lane: float, start: float, end: float, analysis: AudioAnalysis) -> bool:
    for note in notes:
        if note.get("type") not in {1, 3, 4}:
            continue
        note_time = _beats_to_seconds(note.get("startTime", [0, 0, 1]), analysis.bpm)
        if start < note_time < end and abs(float(note.get("positionX", 0.0)) - lane) <= 96.0:
            return False
    return True


def _enforce_hold_playability(notes: list[Dict[str, Any]], decisions: list[TypeDecision], analysis: AudioAnalysis, config: AssistantConfig) -> dict[str, float]:
    if not notes:
        return {"hold_playability_to_tap": 0.0, "hold_coverage_cap": _hold_coverage_cap(config)}
    converted = 0
    max_ratio = config.max_hold_ratio
    max_count = max(0, int(len(notes) * max_ratio))
    hold_indexes = [index for index, note in enumerate(notes) if note.get("type") == 2]

    def convert(index: int, reason: str) -> None:
        nonlocal converted
        note = notes[index]
        if note.get("type") != 2:
            return
        note["type"] = 1
        note["endTime"] = list(note.get("startTime", [0, 0, 1]))
        if index < len(decisions):
            decisions[index].selected_type = 1
            decisions[index].type_reason = reason
        converted += 1

    while True:
        hold_indexes = [index for index, note in enumerate(notes) if note.get("type") == 2]
        conflict_indexes = [index for index in hold_indexes if _hold_contains_rhythm_note(notes, index, analysis)]
        if not conflict_indexes:
            break
        index = min(conflict_indexes, key=lambda idx: _hold_priority(notes, decisions, idx, analysis))
        convert(index, "hold downgraded to tap: would cover rhythm note")

    hold_indexes = [index for index, note in enumerate(notes) if note.get("type") == 2]
    if len(hold_indexes) > max_count:
        ranked = sorted(hold_indexes, key=lambda index: _hold_priority(notes, decisions, index, analysis))
        for index in ranked[: len(hold_indexes) - max_count]:
            convert(index, "hold downgraded to tap: post-sustain hold ratio cap")

    coverage_cap = _hold_coverage_cap(config)
    while _hold_timeline_coverage_seconds(notes, analysis) / max(analysis.duration, 0.001) > coverage_cap:
        hold_indexes = [index for index, note in enumerate(notes) if note.get("type") == 2]
        if not hold_indexes:
            break
        index = min(hold_indexes, key=lambda idx: _hold_priority(notes, decisions, idx, analysis))
        convert(index, "hold downgraded to tap: timeline coverage cap")

    return {"hold_playability_to_tap": float(converted), "hold_coverage_cap": coverage_cap}


def _hold_contains_rhythm_note(notes: list[Dict[str, Any]], hold_index: int, analysis: AudioAnalysis) -> bool:
    hold = notes[hold_index]
    start = _beats_to_seconds(hold.get("startTime", [0, 0, 1]), analysis.bpm)
    end = _beats_to_seconds(hold.get("endTime", hold.get("startTime", [0, 0, 1])), analysis.bpm)
    x = float(hold.get("positionX", 0.0))
    for index, note in enumerate(notes):
        if index == hold_index or note.get("type") == 2:
            continue
        t = _beats_to_seconds(note.get("startTime", [0, 0, 1]), analysis.bpm)
        if start < t < end and abs(float(note.get("positionX", 0.0)) - x) <= 96.0:
            return True
    return False


def _hold_priority(notes: list[Dict[str, Any]], decisions: list[TypeDecision], index: int, analysis: AudioAnalysis) -> tuple[float, float]:
    note = notes[index]
    if index < len(decisions):
        evidence = decisions[index].hold_score
    else:
        evidence = 0.0
    start = _beats_to_seconds(note.get("startTime", [0, 0, 1]), analysis.bpm)
    end = _beats_to_seconds(note.get("endTime", note.get("startTime", [0, 0, 1])), analysis.bpm)
    return (evidence, -(end - start))


def _hold_coverage_cap(config: AssistantConfig) -> float:
    return {Difficulty.EZ: 0.38, Difficulty.HD: 0.32, Difficulty.IN: 0.28, Difficulty.AT: 0.22}[config.difficulty]


def _hold_timeline_coverage_seconds(notes: list[Dict[str, Any]], analysis: AudioAnalysis) -> float:
    intervals: list[tuple[float, float]] = []
    for note in notes:
        if note.get("type") != 2:
            continue
        start = _beats_to_seconds(note.get("startTime", [0, 0, 1]), analysis.bpm)
        end = _beats_to_seconds(note.get("endTime", note.get("startTime", [0, 0, 1])), analysis.bpm)
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return 0.0
    intervals.sort()
    total = 0.0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return total


def _avoid_same_time_same_bucket(notes: list[Dict[str, Any]], analysis: AudioAnalysis, config: AssistantConfig) -> None:
    occupied: dict[tuple[tuple[int, int, int], int], int] = {}
    for index, note in enumerate(sorted(notes, key=lambda n: (n.get("startTime", [0, 0, 1]), float(n.get("positionX", 0.0))))):
        start_key = tuple(int(v) for v in note.get("startTime", [0, 0, 1]))
        bucket = round(float(note.get("positionX", 0.0)) / 45.0)
        key = (start_key, bucket)
        if key not in occupied:
            occupied[key] = index
            continue
        note_time = _beats_to_seconds(note.get("startTime", [0, 0, 1]), analysis.bpm)
        for lane in _collision_safe_lanes(note, config):
            candidate_bucket = round(lane / 45.0)
            candidate_key = (start_key, candidate_bucket)
            if candidate_key in occupied:
                continue
            if note.get("type") in {1, 3, 4} and _lane_inside_existing_hold(notes, lane, note_time, analysis):
                continue
            note["positionX"] = lane
            occupied[candidate_key] = index
            break


def _collision_safe_lanes(note: Dict[str, Any], config: AssistantConfig) -> list[float]:
    current = float(note.get("positionX", 0.0))
    if config.difficulty == Difficulty.AT:
        preferred = [-540.0, 540.0, -405.0, 405.0, -270.0, 270.0, -135.0, 135.0, 0.0]
    else:
        preferred = [-405.0, 405.0, -270.0, 270.0, 0.0, -540.0, 540.0, -135.0, 135.0]
    return sorted(preferred, key=lambda lane: (abs(lane - current), abs(lane)))


def _lane_inside_existing_hold(notes: list[Dict[str, Any]], lane: float, time_seconds: float, analysis: AudioAnalysis) -> bool:
    for hold in notes:
        if hold.get("type") != 2:
            continue
        start = _beats_to_seconds(hold.get("startTime", [0, 0, 1]), analysis.bpm)
        end = _beats_to_seconds(hold.get("endTime", hold.get("startTime", [0, 0, 1])), analysis.bpm)
        if start < time_seconds < end and abs(float(hold.get("positionX", 0.0)) - lane) <= 96.0:
            return True
    return False


def _quality_report(
    analysis: AudioAnalysis,
    config: AssistantConfig,
    selected: list[Candidate],
    notes: list[Dict[str, Any]],
    decisions: list[TypeDecision],
    phrases: list[Phrase],
    pattern_plan: list[PatternBlock],
    target: dict[str, float],
    calibration: TimingCalibration,
    filler_summary: dict[str, float | str],
    ratio_fixes: dict[str, float],
) -> dict[str, Any]:
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for note in notes:
        counts[note["type"]] = counts.get(note["type"], 0) + 1
    duration = max(analysis.duration, 0.001)
    density_by_section: dict[str, int] = {}
    for candidate in selected:
        density_by_section[candidate.section] = density_by_section.get(candidate.section, 0) + 1
    attack_deltas = [candidate.attack_delta_ms for candidate in selected]
    snap_deltas = [candidate.snap_delta_ms for candidate in selected]
    target = dict(target)
    target["actual_notes"] = float(len(notes))
    type_ratios = {
        "tap": round(counts.get(1, 0) / max(1, len(notes)), 4),
        "hold": round(counts.get(2, 0) / max(1, len(notes)), 4),
        "drag": round(counts.get(3, 0) / max(1, len(notes)), 4),
        "flick": round(counts.get(4, 0) / max(1, len(notes)), 4),
    }
    return {
        "bpm": analysis.bpm,
        "song_length": round(analysis.duration, 3),
        "total_beats": target["total_beats"],
        "onset_count": int(target["onset_count"]),
        "difficulty": config.difficulty.value,
        "chart_style": config.chart_style,
        "recommended_offset_ms": calibration.recommended_offset_ms,
        "manual_offset_ms": calibration.manual_offset_ms,
        "final_offset_ms": calibration.final_offset_ms,
        "snap_strength": calibration.snap_strength,
        "note_count": len(notes),
        "tap_count": counts.get(1, 0),
        "hold_count": counts.get(2, 0),
        "drag_count": counts.get(3, 0),
        "flick_count": counts.get(4, 0),
        "average_nps": round(len(notes) / duration, 3),
        "max_10s_nps": round(_max_10s_nps(notes, analysis), 3),
        "density_target": target,
        "density_actual": {
            "note_count": len(notes),
            "average_nps": round(len(notes) / duration, 3),
            "notes_per_minute": round(len(notes) * 60.0 / duration, 3),
        },
        "type_ratios": type_ratios,
        "density_by_section": density_by_section,
        "phrase_summary": phrase_summary(phrases),
        "accent_detection_summary": accent_summary([candidate.accent for candidate in selected]),
        **pattern_summary(pattern_plan),
        "pattern_validator_warnings": validate_pattern_plan(pattern_plan),
        "density_filler_summary": filler_summary,
        "type_ratio_fixes": ratio_fixes,
        "note_type_debug": _note_type_debug(selected, decisions),
        "timing_correction_summary": {
            "average_attack_delta_ms": round(mean(attack_deltas), 3) if attack_deltas else 0.0,
            "average_snap_delta_ms": round(mean(snap_deltas), 3) if snap_deltas else 0.0,
            "max_abs_attack_delta_ms": round(max((abs(value) for value in attack_deltas), default=0.0), 3),
            "max_abs_snap_delta_ms": round(max((abs(value) for value in snap_deltas), default=0.0), 3),
        },
    }


def _refresh_final_note_metrics(report: dict[str, Any], chart: Dict[str, Any], analysis: AudioAnalysis, validation_report: Any) -> None:
    notes = chart["judgeLineList"][0].get("notes", [])
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for note in notes:
        counts[note.get("type", 0)] = counts.get(note.get("type", 0), 0) + 1
    duration = max(analysis.duration, 0.001)
    report["note_count"] = len(notes)
    report["tap_count"] = counts.get(1, 0)
    report["hold_count"] = counts.get(2, 0)
    report["drag_count"] = counts.get(3, 0)
    report["flick_count"] = counts.get(4, 0)
    report["average_nps"] = round(len(notes) / duration, 3)
    report["max_10s_nps"] = round(_max_10s_nps(notes, analysis), 3)
    report["hold_ratio"] = round(counts.get(2, 0) / max(1, len(notes)), 4)
    report["type_ratios"] = {
        "tap": round(counts.get(1, 0) / max(1, len(notes)), 4),
        "hold": report["hold_ratio"],
        "drag": round(counts.get(3, 0) / max(1, len(notes)), 4),
        "flick": round(counts.get(4, 0) / max(1, len(notes)), 4),
    }
    report["density_actual"] = {
        "note_count": len(notes),
        "average_nps": round(len(notes) / duration, 3),
        "notes_per_minute": round(len(notes) * 60.0 / duration, 3),
    }
    if "density_target" in report:
        report["density_target"]["actual_notes"] = float(len(notes))
    report["longest_hold_duration"] = validation_report.longest_hold_duration
    report["hold_timeline_coverage"] = validation_report.hold_timeline_coverage
    report["notes_inside_hold_fixed_count"] = validation_report.notes_inside_hold_fixed_count
    report["holds_trimmed_count"] = validation_report.holds_trimmed_count
    report["holds_split_count"] = validation_report.holds_split_count
    layout_report = compute_layout_report(notes)
    report.update(layout_report)
    report["layout_validator_warnings"] = validate_layout(notes)


def _note_type_debug(selected: list[Candidate], decisions: list[TypeDecision], limit: int = 24) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    type_names = {1: "Tap", 2: "Hold", 3: "Drag", 4: "Flick"}
    for candidate, decision in list(zip(selected, decisions))[:limit]:
        rows.append(
            {
                "time": round(candidate.time, 3),
                "source": candidate.source,
                "section": candidate.section,
                "selected_type": type_names.get(decision.selected_type, str(decision.selected_type)),
                "type_reason": decision.type_reason,
                "tap_score": round(decision.tap_score, 4),
                "hold_score": round(decision.hold_score, 4),
                "flick_score": round(decision.flick_score, 4),
                "drag_score": round(decision.drag_score, 4),
                "kick_score": round(candidate.accent.kick_score, 4),
                "snare_score": round(candidate.accent.snare_score, 4),
                "hat_score": round(candidate.accent.hat_score, 4),
                "bass_energy": round(candidate.accent.bass_energy, 4),
                "mid_energy": round(candidate.accent.mid_energy, 4),
                "high_energy": round(candidate.accent.high_energy, 4),
            }
        )
    return rows


def _max_10s_nps(notes: list[Dict[str, Any]], analysis: AudioAnalysis) -> float:
    if not notes:
        return 0.0
    times = [_beats_to_seconds(note["startTime"], analysis.bpm) for note in notes]
    max_count = 0
    bucket = 0.0
    while bucket <= analysis.duration:
        count = sum(1 for value in times if bucket <= value < bucket + 10.0)
        max_count = max(max_count, count)
        bucket += 10.0
    return max_count / 10.0


def _section_at(sections: list[tuple[float, float, str]], t: float) -> str:
    for start, end, label in sections:
        if start <= t < end:
            return label
    return "Verse"


def _section_density(section: str, preset: dict[str, float]) -> float:
    base = float(preset["section_density_multiplier"])
    if section == "Drop":
        return float(preset["drop_density_multiplier"])
    if section == "Verse":
        return float(preset["chorus_density_multiplier"])
    if section == "Intro":
        return base * 0.62
    if section == "Bridge":
        return base * 0.78
    if section == "Outro":
        return base * 0.58
    return base


def _long_region_at(t: float, analysis: AudioAnalysis) -> tuple[float, float] | None:
    for region in analysis.long_regions:
        if region[0] <= t <= region[1]:
            return region
    return None


def _beats_to_seconds(value: list[int], bpm: float) -> float:
    return (value[0] + value[1] / max(1, value[2])) * 60.0 / bpm


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _base_chart(analysis: AudioAnalysis, config: AssistantConfig, song_filename: str) -> Dict[str, Any]:
    return {
        "BPMList": [{"bpm": float(analysis.bpm), "startTime": [0, 0, 1]}],
        "META": {
            "RPEVersion": 113,
            "background": "",
            "charter": config.charter,
            "composer": config.composer,
            "id": "auto_chart_assistant",
            "level": config.difficulty.value,
            "name": config.chart_name,
            "offset": config.offset_ms + config.manual_offset_ms,
            "song": song_filename,
        },
        "judgeLineGroup": ["Default"],
        "judgeLineList": [
            {
                "Group": 0,
                "Name": "Auto Line",
                "Texture": "line.png",
                "alphaControl": [{"alpha": 1.0, "easing": 1, "x": 0.0}, {"alpha": 1.0, "easing": 1, "x": 9999999.0}],
                "bpmfactor": 1.0,
                "eventLayers": [
                    {
                        "alphaEvents": [_event(255, 255)],
                        "moveXEvents": [_event(0.0, 0.0)],
                        "moveYEvents": [_event(-450.0, -450.0)],
                        "rotateEvents": [_event(0.0, 0.0)],
                        "speedEvents": [],
                    }
                ],
                "extended": {"inclineEvents": [_event(0.0, 0.0, [0, 0, 1], [1, 0, 1])]},
                "father": -1,
                "isCover": 1,
                "notes": [],
                "numOfNotes": 0,
                "posControl": [{"easing": 1, "pos": 1.0, "x": 0.0}, {"easing": 1, "pos": 1.0, "x": 9999999.0}],
                "sizeControl": [{"easing": 1, "size": 1.0, "x": 0.0}, {"easing": 1, "size": 1.0, "x": 9999999.0}],
                "skewControl": [{"easing": 1, "skew": 0.0, "x": 0.0}, {"easing": 1, "skew": 0.0, "x": 9999999.0}],
                "yControl": [{"easing": 1, "x": 0.0, "y": 1.0}, {"easing": 1, "x": 9999999.0, "y": 1.0}],
                "zOrder": 0,
            }
        ],
    }


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
