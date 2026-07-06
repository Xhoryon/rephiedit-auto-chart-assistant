from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Dict


class Difficulty(str, Enum):
    EZ = "EZ"
    HD = "HD"
    IN = "IN"
    AT = "AT"


DIFFICULTY_PRESETS: Dict[Difficulty, Dict[str, float]] = {
    Difficulty.EZ: {
        "density": 0.46,
        "target_nps": 1.15,
        "min_notes_per_minute": 48.0,
        "max_notes_per_minute": 118.0,
        "section_density_multiplier": 0.88,
        "drop_density_multiplier": 1.20,
        "chorus_density_multiplier": 1.10,
        "hold": 0.15,
        "drag": 0.10,
        "flick": 0.04,
        "min_interval": 0.30,
        "max_notes_per_second": 2.2,
        "difficulty_multiplier": 0.50,
        "subdivision_density": 0.62,
        "max_drag_ratio": 0.05,
    },
    Difficulty.HD: {
        "density": 0.72,
        "target_nps": 2.15,
        "min_notes_per_minute": 104.0,
        "max_notes_per_minute": 206.0,
        "section_density_multiplier": 1.00,
        "drop_density_multiplier": 1.32,
        "chorus_density_multiplier": 1.18,
        "hold": 0.17,
        "drag": 0.16,
        "flick": 0.07,
        "min_interval": 0.18,
        "max_notes_per_second": 3.9,
        "difficulty_multiplier": 0.90,
        "subdivision_density": 0.92,
        "max_drag_ratio": 0.08,
    },
    Difficulty.IN: {
        "density": 1.00,
        "target_nps": 3.65,
        "min_notes_per_minute": 198.0,
        "max_notes_per_minute": 352.0,
        "section_density_multiplier": 1.12,
        "drop_density_multiplier": 1.46,
        "chorus_density_multiplier": 1.28,
        "hold": 0.18,
        "drag": 0.24,
        "flick": 0.11,
        "min_interval": 0.105,
        "max_notes_per_second": 6.4,
        "difficulty_multiplier": 1.30,
        "subdivision_density": 1.30,
        "max_drag_ratio": 0.12,
    },
    Difficulty.AT: {
        "density": 1.34,
        "target_nps": 5.65,
        "min_notes_per_minute": 324.0,
        "max_notes_per_minute": 560.0,
        "section_density_multiplier": 1.22,
        "drop_density_multiplier": 1.66,
        "chorus_density_multiplier": 1.40,
        "hold": 0.16,
        "drag": 0.32,
        "flick": 0.15,
        "min_interval": 0.058,
        "max_notes_per_second": 10.0,
        "difficulty_multiplier": 2.00,
        "subdivision_density": 1.78,
        "max_drag_ratio": 0.16,
    },
}


@dataclass(frozen=True)
class AssistantConfig:
    difficulty: Difficulty = Difficulty.HD
    overall_density: float = 1.0
    tap_weight: float = 1.0
    drag_weight: float = 1.0
    hold_weight: float = 1.0
    flick_weight: float = 1.0
    min_interval: float | None = None
    max_bpm_precision: int = 192
    enable_hold: bool = True
    enable_flick: bool = True
    enable_drag: bool = True
    export_path: str = ""
    random_seed: int | None = 42
    chart_name: str = "Auto Generated Reference"
    composer: str = "Unknown"
    charter: str = "Auto Chart Assistant"
    offset_ms: int = 0
    auto_timing_calibration: bool = True
    manual_offset_ms: int = 0
    snap_strength: float = 0.65
    bpm_aware_density: bool = True
    chart_style: str = "Official-like"
    drag_requires_evidence: bool = True
    drag_evidence_threshold: float = 0.62
    drag_chain_min_length: int = 2
    drag_chain_max_length: int = 4
    max_hold_duration_by_difficulty: Dict[str, float] = field(default_factory=lambda: {"EZ": 4.0, "HD": 3.5, "IN": 3.0, "AT": 2.0})

    @property
    def max_hold_duration(self) -> float:
        return float(self.max_hold_duration_by_difficulty.get(self.difficulty.value, 2.0))

    @property
    def max_hold_ratio(self) -> float:
        return {Difficulty.EZ: 0.18, Difficulty.HD: 0.17, Difficulty.IN: 0.15, Difficulty.AT: 0.12}[self.difficulty]

    @property
    def min_tap_drag_ratio(self) -> float:
        return {Difficulty.EZ: 0.55, Difficulty.HD: 0.58, Difficulty.IN: 0.60, Difficulty.AT: 0.68}[self.difficulty]

    @property
    def preset(self) -> Dict[str, float]:
        return DIFFICULTY_PRESETS[self.difficulty]

    @property
    def effective_min_interval(self) -> float:
        return float(self.min_interval if self.min_interval is not None else self.preset["min_interval"])


def load_config(path: str | Path | None = None) -> AssistantConfig:
    if path is None:
        return AssistantConfig()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "difficulty" in data:
        data["difficulty"] = Difficulty(data["difficulty"])
    valid = {field.name for field in AssistantConfig.__dataclass_fields__.values()}
    return replace(AssistantConfig(), **{k: v for k, v in data.items() if k in valid})


def save_default_config(path: str | Path) -> None:
    cfg = AssistantConfig()
    data: Dict[str, Any] = cfg.__dict__.copy()
    data["difficulty"] = cfg.difficulty.value
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
