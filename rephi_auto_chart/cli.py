from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import analyze_audio
from .batch import batch_generate
from .chart_analyzer import analyze_chart_file, write_analysis_reports
from .compare import compare_charts, write_comparison_reports
from .config import AssistantConfig, Difficulty, load_config, save_default_config
from .exporter import export_pez, export_rephi_package, export_rpe_chart
from .generator import generate_chart
from .parser import inspect_rephi_install
from .runtime import default_export_path, ensure_runtime_layout
from .validator import validate_and_fix_chart


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rephi-auto-chart", description="Generate reference RPE charts for Re:PhiEdit.")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Analyze audio and export a chart.")
    gen.add_argument("audio", type=Path)
    gen.add_argument("-c", "--config", type=Path)
    gen.add_argument("-d", "--difficulty", choices=[d.value for d in Difficulty])
    gen.add_argument("-o", "--output", type=Path)
    gen.add_argument("--package-dir", type=Path, help="Export an unpacked debug folder with chart, audio, info.txt, and illustration.")
    gen.add_argument("--pez", action="store_true", help="Export a Re:PhiEdit .pez import package.")

    init = sub.add_parser("init-config", help="Write a default JSON config.")
    init.add_argument("path", type=Path, nargs="?", default=Path("config/default_config.json"))

    inspect = sub.add_parser("inspect", help="Inspect a Re:PhiEdit installation.")
    inspect.add_argument("root", type=Path, nargs="?", default=Path("~/Downloads/phigrosfanmadecharteditor").expanduser())

    analyzer = sub.add_parser("analyze-chart", help="Analyze chart.json or .pez and write JSON/CSV/HTML reports.")
    analyzer.add_argument("chart", type=Path)
    analyzer.add_argument("-o", "--output-dir", type=Path)

    compare = sub.add_parser("compare", help="Compare official and generated chart.json/.pez files.")
    compare.add_argument("official", type=Path)
    compare.add_argument("generated", type=Path)
    compare.add_argument("-o", "--output-dir", type=Path)

    batch = sub.add_parser("batch", help="Batch-generate charts from multiple audio files.")
    batch.add_argument("audio", type=Path, nargs="+")
    batch.add_argument("-d", "--difficulty", choices=[d.value for d in Difficulty], default=Difficulty.HD.value)
    batch.add_argument("-o", "--output-dir", type=Path)
    batch.add_argument("--format", choices=["pez", "json"], default="pez")

    args = parser.parse_args(argv)
    if args.command == "init-config":
        save_default_config(args.path)
        print(f"Wrote {args.path}")
        return 0
    if args.command == "inspect":
        report = inspect_rephi_install(args.root)
        print(f"root={report.root}")
        print(f"plugin_system={report.has_plugin_system}")
        print(f"preferred_strategy={report.preferred_strategy}")
        print(f"example_charts={len(report.example_charts)}")
        print(f"format_summary={report.format_summary}")
        return 0
    if args.command == "analyze-chart":
        layout, _ = ensure_runtime_layout()
        output_dir = args.output_dir or (layout.outputs / "analysis_report")
        report = analyze_chart_file(args.chart)
        paths = write_analysis_reports(report, output_dir)
        print(f"Analyzed {args.chart}: notes={report.total_notes} bpm={report.bpm:.3f}")
        print(paths)
        return 0
    if args.command == "compare":
        layout, _ = ensure_runtime_layout()
        output_dir = args.output_dir or (layout.outputs / "comparison_report")
        report = compare_charts(args.official, args.generated)
        paths = write_comparison_reports(report, output_dir)
        print(f"Compared charts. Deltas={report.deltas}")
        print(paths)
        return 0
    if args.command == "batch":
        layout, _ = ensure_runtime_layout()
        output_dir = args.output_dir or (layout.outputs / "batch")
        cfg = AssistantConfig(difficulty=Difficulty(args.difficulty))
        outputs = batch_generate(args.audio, output_dir, cfg, export_format=args.format)
        print(f"Generated {len(outputs)} charts")
        for output in outputs:
            print(output)
        return 0
    if args.command == "generate":
        config = load_config(args.config) if args.config else AssistantConfig()
        if args.difficulty:
            config = AssistantConfig(**{**config.__dict__, "difficulty": Difficulty(args.difficulty)})
        if args.output:
            config = AssistantConfig(**{**config.__dict__, "export_path": str(args.output)})
        print(f"Analyzing {args.audio}...")
        analysis = analyze_audio(args.audio)
        print(f"BPM={analysis.bpm:.3f} duration={analysis.duration:.2f}s onsets={len(analysis.onsets)} beats={len(analysis.beats)}")
        chart = generate_chart(analysis, config, args.audio.name)
        chart, report = validate_and_fix_chart(chart)
        if args.pez:
            target = args.output or default_export_path("pez")
            output = export_pez(chart, target, args.audio)
            print(f"Exported PEZ to {output}")
        elif args.package_dir:
            package = export_rephi_package(chart, args.package_dir, args.audio)
            print(f"Exported package to {package}")
        else:
            output = export_rpe_chart(chart, args.output or default_export_path("json"))
            print(f"Exported chart to {output}")
        print(f"Validation fixes={report.fixed_count} warnings={len(report.warnings)}")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
