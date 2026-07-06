from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import save_default_config


APP_DIR_NAME = "RePhiEditAutoChart"
EXPORT_DIR_NAME = "RePhiEdit Charts"


@dataclass(frozen=True)
class RuntimeLayout:
    root: Path
    config: Path
    cache: Path
    logs: Path
    outputs: Path
    temp: Path
    config_file: Path
    export_root: Path


def user_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME
    return Path.home() / ".rephi_auto_chart"


def user_documents_root() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile) / "Documents"
    return Path.home() / "Documents"


def default_export_root() -> Path:
    return user_documents_root() / EXPORT_DIR_NAME


def default_export_path(mode: str = "pez") -> Path:
    export_root = default_export_root()
    normalized = mode.lower()
    if normalized == "json":
        return export_root / "generated_chart.json"
    if normalized == "folder":
        return export_root / "generated_rephi_folder"
    return export_root / "generated.pez"


def ensure_runtime_layout() -> tuple[RuntimeLayout, list[str]]:
    root = user_data_root()
    layout = RuntimeLayout(
        root=root,
        config=root / "config",
        cache=root / "cache",
        logs=root / "logs",
        outputs=root / "outputs",
        temp=root / "temp",
        config_file=root / "config" / "default_config.json",
        export_root=default_export_root(),
    )
    messages: list[str] = []
    for folder in (layout.root, layout.config, layout.cache, layout.logs, layout.outputs, layout.temp, layout.export_root):
        folder.mkdir(parents=True, exist_ok=True)
    messages.append(f"Runtime folders: ready ({layout.root}).")
    messages.append(f"Default export folder: ready ({layout.export_root}).")
    if not layout.config_file.exists():
        _copy_or_create_default_config(layout.config_file)
        messages.append("Runtime config: created.")
    elif not _is_valid_json(layout.config_file):
        backup = layout.config_file.with_suffix(".json.bak")
        shutil.copy2(layout.config_file, backup)
        _copy_or_create_default_config(layout.config_file)
        messages.append(f"Runtime config: repaired invalid JSON; backup saved to {backup.name}.")
    else:
        messages.append("Runtime config: valid.")
    return layout, messages


def update_checker_status() -> str:
    return "Update checker: reserved for V3; automatic updates are not enabled in V2.3."


def bundled_resource_path(relative_path: str | Path) -> Path | None:
    relative = Path(relative_path)
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / relative)
    if getattr(sys, "frozen", False):
        executable_dir = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                executable_dir / relative,
                executable_dir / "_internal" / relative,
            ]
        )
    candidates.extend(
        [
            Path.cwd() / relative,
            Path(__file__).resolve().parents[1] / relative,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_runtime_config(layout: RuntimeLayout | None = None) -> dict[str, Any]:
    active_layout = layout or ensure_runtime_layout()[0]
    try:
        data = json.loads(active_layout.config_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_runtime_config(data: dict[str, Any], layout: RuntimeLayout | None = None) -> None:
    active_layout = layout or ensure_runtime_layout()[0]
    active_layout.config.mkdir(parents=True, exist_ok=True)
    active_layout.config_file.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def configured_export_path(mode: str = "pez", layout: RuntimeLayout | None = None) -> Path:
    active_layout = layout or ensure_runtime_layout()[0]
    data = read_runtime_config(active_layout)
    export_path = str(data.get("export_path") or "").strip()
    if export_path and _is_user_export_path(export_path):
        return Path(export_path)
    return default_export_path(mode)


def save_configured_export_path(path: str | Path, layout: RuntimeLayout | None = None) -> None:
    active_layout = layout or ensure_runtime_layout()[0]
    data = read_runtime_config(active_layout)
    data["export_path"] = str(Path(path))
    write_runtime_config(data, active_layout)


def safe_output_dir(path: str | Path, layout: RuntimeLayout | None = None) -> Path:
    active_layout = layout or ensure_runtime_layout()[0]
    candidate = Path(path)
    if _is_absolute_path_text(str(path)):
        return candidate
    return active_layout.export_root


def _copy_or_create_default_config(target: Path) -> None:
    bundled = bundled_resource_path("config/default_config.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if bundled:
        shutil.copy2(bundled, target)
    else:
        save_default_config(target)


def _is_valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def _is_user_export_path(path_text: str) -> bool:
    if not _is_absolute_path_text(path_text):
        return False
    normalized = path_text.replace("\\", "/").lower()
    return "/program files/" not in normalized and not normalized.endswith("/outputs")


def _is_absolute_path_text(path_text: str) -> bool:
    if not path_text:
        return False
    if Path(path_text).is_absolute():
        return True
    return re.match(r"^[A-Za-z]:[\\/]", path_text) is not None or path_text.startswith("\\\\")
