from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class RePhiInspection:
    root: Path
    version_hint: str | None = None
    has_plugin_system: bool = False
    preferred_strategy: str = "external-tool-rpe-json"
    example_charts: List[Path] = field(default_factory=list)
    chartlist_entries: List[Dict[str, str]] = field(default_factory=list)
    format_summary: Dict[str, Any] = field(default_factory=dict)


def inspect_rephi_install(root: str | Path) -> RePhiInspection:
    base = Path(root).expanduser()
    report = RePhiInspection(root=base)
    report.has_plugin_system = any((base / name).exists() for name in ("Plugins", "plugins"))
    report.chartlist_entries = _parse_chartlist(base / "Chartlist.txt")
    report.example_charts = sorted(base.glob("Resources/*/*.json")) + sorted(base.glob("Data/charts/**/*.json"))
    report.format_summary = _summarize_format(report.example_charts[:1])
    return report


def _parse_chartlist(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    entries: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("#"):
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    if current:
        entries.append(current)
    return entries


def _summarize_format(paths: List[Path]) -> Dict[str, Any]:
    if not paths:
        return {}
    data = json.loads(paths[0].read_text(encoding="utf-8"))
    line = data.get("judgeLineList", [{}])[0]
    notes = line.get("notes", [])
    return {
        "top_level": sorted(data.keys()),
        "line_keys": sorted(line.keys()),
        "note_keys": sorted(notes[0].keys()) if notes else [],
        "note_types": sorted({note.get("type") for note in notes}),
        "rpe_version": data.get("META", {}).get("RPEVersion"),
        "example": str(paths[0]),
    }

