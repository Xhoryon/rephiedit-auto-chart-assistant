from __future__ import annotations

import json
import shutil
import struct
import zipfile
import zlib
from pathlib import Path
from typing import Any, Dict

from .validator import validate_and_fix_chart


def export_rpe_chart(chart: Dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fixed, report = validate_and_fix_chart(chart)
    if report.warnings:
        fixed.setdefault("META", {})["autoChartWarnings"] = report.warnings
    path.write_text(json.dumps(fixed, indent=3, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_rpe_chart(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


DEFAULT_ILLUSTRATION = "illustration.png"


def export_rephi_package(chart: Dict[str, Any], output_dir: str | Path, audio_path: str | Path, chart_filename: str = "chart.json") -> Path:
    package = Path(output_dir)
    package.mkdir(parents=True, exist_ok=True)
    audio = Path(audio_path)
    target_audio = package / audio.name
    if audio.resolve() != target_audio.resolve():
        shutil.copy2(audio, target_audio)
    illustration = package / DEFAULT_ILLUSTRATION
    if not illustration.exists():
        write_default_illustration(illustration)
    meta = chart.setdefault("META", {})
    meta["song"] = target_audio.name
    meta["background"] = DEFAULT_ILLUSTRATION
    export_rpe_chart(chart, package / chart_filename)
    info = _info_text(chart, package.name, target_audio.name, chart_filename)
    (package / "info.txt").write_text(info, encoding="utf-8")
    return package


def export_pez(chart: Dict[str, Any], output_path: str | Path, audio_path: str | Path, chart_id: str | None = None) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".pez":
        path = path.with_suffix(".pez")
    path.parent.mkdir(parents=True, exist_ok=True)
    chart_id = _safe_id(chart_id or path.stem or chart.get("META", {}).get("id", "auto_chart"))
    audio = Path(audio_path)
    audio_name = f"{chart_id}{audio.suffix.lower()}"
    picture_name = f"{chart_id}.png"
    chart_name = f"{chart_id}.json"
    meta = chart.setdefault("META", {})
    meta["id"] = chart_id
    meta["song"] = audio_name
    meta["background"] = picture_name
    fixed, report = validate_and_fix_chart(chart)
    if report.warnings:
        fixed.setdefault("META", {})["autoChartWarnings"] = report.warnings
    info = _info_text(fixed, chart_id, audio_name, chart_name)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(audio, audio_name)
        zf.writestr(picture_name, _default_illustration_bytes())
        zf.writestr(chart_name, json.dumps(fixed, indent=3, ensure_ascii=False) + "\n")
        zf.writestr("info.txt", info)
    return path


def _safe_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in value.strip())
    return cleaned or "auto_chart"


def write_default_illustration(path: str | Path, width: int = 1024, height: int = 512) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_default_illustration_bytes(width, height))
    return target


def _default_illustration_bytes(width: int = 1024, height: int = 512) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            shade = int(24 + 32 * (x / max(1, width - 1)))
            accent = int(80 + 70 * (y / max(1, height - 1)))
            raw.extend((shade, accent, 118, 255))
    return b"".join(
        [
            b"\x89PNG\r\n\x1a\n",
            _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9)),
            _png_chunk(b"IEND", b""),
        ]
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _info_text(chart_data: Dict[str, Any], folder: str, song: str, chart_filename: str) -> str:
    meta = chart_data.get("META", {})
    return "\n".join(
        [
            "#",
            f"Name: {meta.get('name', 'Auto Generated Reference')}",
            f"Path: {folder}",
            f"Song: {song}",
            f"Picture: {meta.get('background', DEFAULT_ILLUSTRATION)}",
            f"Chart: {chart_filename}",
            f"Level: {meta.get('level', 'HD')}",
            f"Composer: {meta.get('composer', 'Unknown')}",
            f"Charter: {meta.get('charter', 'Auto Chart Assistant')}",
            "",
        ]
    )
