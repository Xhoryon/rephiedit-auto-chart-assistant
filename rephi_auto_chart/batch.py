from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from .analysis import analyze_audio
from .config import AssistantConfig
from .exporter import export_pez, export_rpe_chart
from .generator import generate_chart


def batch_generate(audio_files: Iterable[str | Path], output_dir: str | Path, config: AssistantConfig, export_format: str = "pez") -> List[Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for audio in audio_files:
        audio_path = Path(audio)
        analysis = analyze_audio(audio_path)
        chart = generate_chart(analysis, config, audio_path.name)
        if export_format.lower() == "json":
            target = out / f"{audio_path.stem}.json"
            outputs.append(export_rpe_chart(chart, target))
        else:
            target = out / f"{audio_path.stem}.pez"
            outputs.append(export_pez(chart, target, audio_path, chart_id=audio_path.stem))
    return outputs

