from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path

from .runtime import bundled_resource_path, ensure_runtime_layout, safe_output_dir, update_checker_status


@dataclass
class StartupCheckResult:
    ok: bool
    messages: list[str]


def run_startup_checks(output_dir: str | Path) -> StartupCheckResult:
    messages: list[str] = []
    try:
        layout, runtime_messages = ensure_runtime_layout()
        messages.extend(runtime_messages)
        messages.append(update_checker_status())
    except Exception as exc:
        messages.append(f"Runtime folders: could not initialize ({exc}).")
        layout = None
    has_decoder = any(importlib.util.find_spec(name) for name in ("soundfile", "librosa"))
    messages.append("Audio decoder: MP3/FLAC/OGG support is available." if has_decoder else "Audio decoder: WAV works. Install or bundle soundfile/librosa for MP3, FLAC, and OGG.")
    bundled_ffmpeg = bundled_resource_path("tools/ffmpeg/ffmpeg.exe")
    has_ffmpeg = shutil.which("ffmpeg") is not None or bundled_ffmpeg is not None
    messages.append("ffmpeg: available." if has_ffmpeg else "ffmpeg: not found. Built-in soundfile/librosa decoders will be used when available.")
    config = bundled_resource_path("config/default_config.json")
    messages.append("Default config: found." if config else "Default config: missing. Built-in defaults will be used.")
    out = safe_output_dir(output_dir, layout) if layout is not None else Path(output_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        messages.append(f"Output folder: writable ({out}).")
        writable = True
    except Exception:
        messages.append(f"Output folder: not writable ({out}). Choose another folder.")
        writable = False
    return StartupCheckResult(ok=writable, messages=messages)
