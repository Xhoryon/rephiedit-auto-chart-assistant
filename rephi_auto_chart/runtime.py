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
WINDOWS_INVALID_FILENAME_CHARS = '<>:"/\\|?*'
THEME_MODES = {"system", "light", "dark"}
THEMES = {"light", "dark"}


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


def safe_export_filename_stem(name: str | Path) -> str:
    raw = str(name)
    stem = Path(raw).stem if Path(raw).suffix else raw
    safe = "".join("_" if char in WINDOWS_INVALID_FILENAME_CHARS or ord(char) < 32 else char for char in stem)
    safe = re.sub(r"_+", "_", safe).strip(" ._")
    return safe or "generated"


def next_available_export_path(path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.exists():
        return candidate
    suffix = candidate.suffix
    stem = candidate.stem
    parent = candidate.parent
    index = 1
    while True:
        next_candidate = parent / f"{stem}_{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


def audio_default_export_path(audio_path: str | Path, mode: str = "pez", export_root: Path | None = None) -> Path:
    root = export_root or default_export_root()
    stem = safe_export_filename_stem(Path(audio_path).stem)
    normalized = mode.lower()
    if normalized == "json":
        return next_available_export_path(root / f"{stem}.json")
    if normalized == "folder":
        return next_available_export_path(root / stem)
    return next_available_export_path(root / f"{stem}.pez")


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
    return "Update checker: reserved for V3; automatic updates are not enabled in V2.5.2."


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


def find_ffmpeg() -> Path | None:
    for relative in (
        "assets/windows/ffmpeg.exe",
        "ffmpeg.exe",
        "tools/ffmpeg/ffmpeg.exe",
    ):
        bundled = bundled_resource_path(relative)
        if bundled and bundled.exists():
            return bundled.resolve()
    path_value = shutil.which("ffmpeg")
    return Path(path_value).resolve() if path_value else None


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


def detect_windows_theme() -> str | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if int(value) == 1 else "dark"
    except Exception:
        return None


def detect_system_theme() -> str:
    return detect_windows_theme() or "light"


def configured_theme_mode(layout: RuntimeLayout | None = None) -> str:
    active_layout = layout or ensure_runtime_layout()[0]
    data = read_runtime_config(active_layout)
    mode = str(data.get("theme_mode") or "").strip().lower()
    if mode in THEME_MODES:
        return mode

    legacy_theme = str(data.get("theme") or "").strip().lower()
    if legacy_theme in THEMES:
        data["theme_mode"] = legacy_theme
        data.pop("theme", None)
        write_runtime_config(data, active_layout)
        return legacy_theme

    data["theme_mode"] = "system"
    data.pop("theme", None)
    write_runtime_config(data, active_layout)
    return "system"


def save_configured_theme_mode(mode: str, layout: RuntimeLayout | None = None) -> None:
    active_layout = layout or ensure_runtime_layout()[0]
    data = read_runtime_config(active_layout)
    normalized = str(mode).strip().lower()
    data["theme_mode"] = normalized if normalized in THEME_MODES else "system"
    data.pop("theme", None)
    write_runtime_config(data, active_layout)


def effective_theme(mode: str | None = None, layout: RuntimeLayout | None = None) -> str:
    normalized = str(mode or configured_theme_mode(layout)).strip().lower()
    if normalized == "system":
        return detect_system_theme()
    return normalized if normalized in THEMES else "light"


def configured_theme(layout: RuntimeLayout | None = None) -> str:
    return effective_theme(configured_theme_mode(layout), layout)


def save_configured_theme(theme: str, layout: RuntimeLayout | None = None) -> None:
    save_configured_theme_mode(theme, layout)


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
