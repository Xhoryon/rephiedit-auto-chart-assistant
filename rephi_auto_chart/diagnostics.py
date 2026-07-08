from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from .runtime import bundled_resource_path, ensure_runtime_layout, find_ffmpeg, safe_output_dir, update_checker_status


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
    ffmpeg = find_ffmpeg()
    messages.append(f"ffmpeg: available ({ffmpeg})." if ffmpeg else "ffmpeg: not found. M4A/AAC/ALAC decoding will not be available in this build.")
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
