from __future__ import annotations

import audioop
import math
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import List

from .runtime import ensure_runtime_layout, find_ffmpeg


SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".alac"}
FFMPEG_FIRST_EXTENSIONS = {".m4a", ".aac", ".alac"}


@dataclass(frozen=True)
class AudioAnalysis:
    path: Path
    sample_rate: int
    duration: float
    bpm: float
    beats: List[float]
    onsets: List[float]
    energy_curve: List[float]
    sections: List[tuple[float, float, str]]
    long_regions: List[tuple[float, float]]
    waveform: List[float] | None = None
    hop_seconds: float = 0.0
    attack_curve: List[float] | None = None
    bass_energy_curve: List[float] | None = None
    mid_energy_curve: List[float] | None = None
    high_energy_curve: List[float] | None = None


def analyze_audio(path: str | Path) -> AudioAnalysis:
    audio_path = Path(path)
    if audio_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported audio extension: {audio_path.suffix}")
    samples, sample_rate = _read_audio_mono(audio_path)
    duration = len(samples) / sample_rate if sample_rate else 0.0
    frame_size = max(512, int(sample_rate * 0.046))
    hop_size = max(256, frame_size // 2)
    hop_seconds = hop_size / sample_rate
    energy = _frame_energy(samples, frame_size, hop_size)
    bass_energy, mid_energy, high_energy = _frame_band_energy(samples, sample_rate, frame_size, hop_size)
    attack_curve = _attack_curve(energy)
    onsets = _detect_onsets(energy, hop_seconds)
    bpm = _estimate_bpm(onsets)
    beats = _build_beats(onsets, bpm, duration)
    sections = _segment_sections(energy, hop_seconds, duration)
    long_regions = _detect_long_regions(energy, hop_seconds)
    waveform = _downsample_waveform(samples)
    return AudioAnalysis(
        audio_path,
        sample_rate,
        duration,
        bpm,
        beats,
        onsets,
        energy,
        sections,
        long_regions,
        waveform,
        hop_seconds,
        attack_curve,
        bass_energy,
        mid_energy,
        high_energy,
    )


def _read_audio_mono(path: Path) -> tuple[list[float], int]:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return _read_wav(path)
    if suffix in FFMPEG_FIRST_EXTENSIONS:
        return _read_ffmpeg_first(path)
    converted = _try_decode_with_ffmpeg(path)
    if converted is not None:
        try:
            return _read_wav(converted)
        finally:
            converted.unlink(missing_ok=True)
    return _try_optional_readers(path)


def _read_ffmpeg_first(path: Path) -> tuple[list[float], int]:
    converted = _try_decode_with_ffmpeg(path)
    if converted is not None:
        try:
            return _read_wav(converted)
        finally:
            converted.unlink(missing_ok=True)
    try:
        return _try_optional_readers(path)
    except Exception as exc:
        raise RuntimeError("M4A decoding failed. Please check whether the audio file is valid.") from exc


def _read_wav(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if channels > 1:
        frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
    if sample_width != 2:
        frames = audioop.lin2lin(frames, sample_width, 2)
        sample_width = 2
    count = len(frames) // sample_width
    samples = [int.from_bytes(frames[i * 2 : i * 2 + 2], "little", signed=True) / 32768.0 for i in range(count)]
    return samples, sample_rate


def _try_decode_with_ffmpeg(path: Path) -> Path | None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return None
    runtime_temp = ensure_runtime_layout()[0].temp
    runtime_temp.mkdir(parents=True, exist_ok=True)
    fd, out_name = tempfile.mkstemp(suffix=".wav", dir=runtime_temp)
    os.close(fd)
    out = Path(out_name)
    cmd = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "44100", str(out)]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        out.unlink(missing_ok=True)
        return None
    return out


def _try_optional_readers(path: Path) -> tuple[list[float], int]:
    try:
        import soundfile as sf  # type: ignore

        data, sample_rate = sf.read(str(path), always_2d=True)
        mono = data.mean(axis=1)
        return [float(x) for x in mono], int(sample_rate)
    except Exception:
        pass
    try:
        import librosa  # type: ignore

        data, sample_rate = librosa.load(str(path), sr=None, mono=True)
        return [float(x) for x in data], int(sample_rate)
    except Exception as exc:
        if path.suffix.lower() in FFMPEG_FIRST_EXTENSIONS:
            raise RuntimeError("M4A decoding failed. Please check whether the audio file is valid.") from exc
        raise RuntimeError(
            f"Cannot decode {path.suffix}. The audio file may be damaged or unsupported by the bundled decoders."
        ) from exc


def _frame_energy(samples: list[float], frame_size: int, hop_size: int) -> list[float]:
    values: list[float] = []
    for start in range(0, max(1, len(samples) - frame_size + 1), hop_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        values.append(sum(abs(x) for x in frame) / len(frame))
    if not values:
        return [0.0]
    peak = max(values) or 1.0
    return [v / peak for v in values]


def _detect_onsets(energy: list[float], hop_seconds: float) -> list[float]:
    if len(energy) < 3:
        return []
    diffs = [max(0.0, energy[i] - energy[i - 1]) for i in range(1, len(energy))]
    threshold = max(0.08, median(diffs) * 3.0)
    onsets: list[float] = []
    last = -999.0
    for i, value in enumerate(diffs, start=1):
        if value >= threshold and energy[i] > 0.12:
            t = i * hop_seconds
            if t - last >= 0.08:
                onsets.append(t)
                last = t
    if not onsets and max(energy) > 0.05:
        onsets = [i * hop_seconds for i, e in enumerate(energy) if e > 0.5]
    return onsets


def _attack_curve(energy: list[float]) -> list[float]:
    if not energy:
        return [0.0]
    values = [0.0]
    values.extend(max(0.0, energy[i] - energy[i - 1]) for i in range(1, len(energy)))
    peak = max(values) or 1.0
    return [v / peak for v in values]


def _frame_band_energy(samples: list[float], sample_rate: int, frame_size: int, hop_size: int) -> tuple[list[float], list[float], list[float]]:
    bass: list[float] = []
    mid: list[float] = []
    high: list[float] = []
    for start in range(0, max(1, len(samples) - frame_size + 1), hop_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        bass.append(_goertzel_band(frame, sample_rate, (60.0, 120.0)))
        mid.append(_goertzel_band(frame, sample_rate, (700.0, 1800.0, 3200.0)))
        high.append(_goertzel_band(frame, sample_rate, (6000.0, 9000.0)))
    return _normalize(bass), _normalize(mid), _normalize(high)


def _goertzel_band(frame: list[float], sample_rate: int, frequencies: tuple[float, ...]) -> float:
    if sample_rate <= 0 or not frame:
        return 0.0
    total = 0.0
    n = len(frame)
    for frequency in frequencies:
        coeff = 2.0 * math.cos(2.0 * math.pi * frequency / sample_rate)
        q0 = q1 = q2 = 0.0
        for sample in frame[::2]:
            q0 = coeff * q1 - q2 + sample
            q2 = q1
            q1 = q0
        power = q1 * q1 + q2 * q2 - coeff * q1 * q2
        total += max(0.0, power) / max(1, n)
    return total / max(1, len(frequencies))


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return [0.0]
    peak = max(values) or 1.0
    return [v / peak for v in values]


def _estimate_bpm(onsets: list[float]) -> float:
    intervals = [b - a for a, b in zip(onsets, onsets[1:]) if 0.18 <= b - a <= 2.0]
    if not intervals:
        return 120.0
    beat = median(intervals)
    bpm = 60.0 / beat
    while bpm < 80:
        bpm *= 2
    while bpm > 220:
        bpm /= 2
    return round(bpm, 3)


def _build_beats(onsets: list[float], bpm: float, duration: float) -> list[float]:
    interval = 60.0 / max(1.0, bpm)
    if onsets:
        start = onsets[0]
    else:
        start = 0.0
    beats: list[float] = []
    t = start
    while t <= duration + 0.001:
        beats.append(round(t, 6))
        t += interval
    return beats


def _segment_sections(energy: list[float], hop_seconds: float, duration: float) -> list[tuple[float, float, str]]:
    if duration <= 0:
        return []
    window = max(1, int(8.0 / hop_seconds))
    overall = sum(energy) / max(1, len(energy))
    sections = []
    for start in range(0, len(energy), window):
        chunk = energy[start : start + window]
        avg = sum(chunk) / max(1, len(chunk))
        section_start = start * hop_seconds
        section_end = min(duration, (start + len(chunk)) * hop_seconds)
        progress = section_start / max(duration, 0.001)
        if progress < 0.12:
            label = "Intro"
        elif progress > 0.88:
            label = "Outro"
        elif avg >= max(0.34, overall * 1.35):
            label = "Drop"
        elif avg <= max(0.08, overall * 0.55):
            label = "Bridge"
        else:
            label = "Verse"
        sections.append((section_start, section_end, label))
    return sections


def _detect_long_regions(energy: list[float], hop_seconds: float) -> list[tuple[float, float]]:
    regions: list[tuple[float, float]] = []
    start: float | None = None
    for i, e in enumerate(energy):
        t = i * hop_seconds
        if e > 0.18 and start is None:
            start = t
        elif e <= 0.12 and start is not None:
            if t - start >= 0.55:
                regions.append((start, t))
            start = None
    if start is not None and len(energy) * hop_seconds - start >= 0.55:
        regions.append((start, len(energy) * hop_seconds))
    return regions


def _downsample_waveform(samples: list[float], points: int = 512) -> list[float]:
    if not samples:
        return []
    step = max(1, len(samples) // points)
    values = []
    for i in range(0, len(samples), step):
        chunk = samples[i : i + step]
        values.append(max(abs(x) for x in chunk) if chunk else 0.0)
    peak = max(values) or 1.0
    return [v / peak for v in values[:points]]
