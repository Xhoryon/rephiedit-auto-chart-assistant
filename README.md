# Re:PhiEdit Auto Chart Assistant

A rule-based desktop tool that turns audio files into editable draft charts for Re:PhiEdit.

## GUI Screenshot

> Screenshot placeholder. Replace this section with a GUI image before publishing if desired.

## Project Overview

Re:PhiEdit Auto Chart Assistant helps chart creators quickly build a starting point for Re:PhiEdit projects. It analyzes an audio file, creates a single-line reference chart, validates the result, and exports a Re:PhiEdit-compatible `.pez` package.

The generated result is an editable draft chart, not a finished chart. Manual refinement in Re:PhiEdit is still recommended for timing, musical expression, difficulty balance, and final polish.

```text
Audio
  -> Analysis
  -> Pattern Generation
  -> Layout
  -> Validation
  -> PEZ Export
  -> Open in Re:PhiEdit
  -> Manual Refinement
```

V2.5.2 is an M4A decoding hotfix release for Windows installer and portable builds. It does not train on reference charts and should not be described as AI charting.

## Features

- GUI workflow for selecting audio, difficulty, style, timing offset, and export target.
- Audio input support for WAV, MP3, FLAC, OGG, M4A, AAC, and ALAC when the bundled or optional audio dependencies are available.
- Difficulty presets: EZ, HD, IN, and AT.
- Rule-based BPM, beat, onset, energy, accent, phrase, pattern, and layout analysis.
- Pattern-based generation with Tap, Drag, Hold, and Flick notes.
- Timing calibration with automatic recommendation, manual offset, and snap strength controls.
- PEZ export for Re:PhiEdit Import.
- Folder package export for inspection/debugging.
- Raw `chart.json` export.
- Chart Analyzer for chart statistics and JSON/CSV/HTML reports.
- Compare Mode for comparing two charts.
- Batch Mode for generating multiple PEZ files.
- Startup diagnostics for audio decoding, default config, and output folder checks.
- Windows installer and portable build pipeline.
- System, Light, and Dark GUI themes with runtime switching.

## Installation

### Windows Installer

For ordinary Windows users, use the installer from the GitHub Release page:

```text
Setup.exe
```

Install it, then launch the app from the desktop shortcut or Start Menu.

The installed app does not require users to install Python, pip, venv, librosa, soundfile, or other Python packages manually. Runtime data is stored under:

```text
%LOCALAPPDATA%\RePhiEditAutoChart
```

Generated charts default to:

```text
%USERPROFILE%\Documents\RePhiEdit Charts
```

### FFmpeg License Note

Windows installer and portable release builds bundle `ffmpeg.exe` so M4A/AAC/ALAC audio can be decoded without user setup. FFmpeg is a separate open-source project distributed under its own licenses. See [ffmpeg.org](https://ffmpeg.org/) and [FFmpeg legal information](https://ffmpeg.org/legal.html).

Windows release builds bundle ffmpeg for M4A/AAC/ALAC decoding. Users do not need to install ffmpeg manually.

### Portable

The portable release is intended for users who do not want to install the app. Extract the portable archive and run:

```text
RePhiEditAutoChartAssistant.exe
```

Keep the full portable folder together. Do not move only the `.exe` file out of the folder.

### Source Build

For development or source-based use, Python 3.12 is recommended.

Windows:

```text
run_windows.bat
```

macOS/Linux:

```sh
python3 -m pip install -e ".[audio]"
python3 -m rephi_auto_chart.gui
```

Build the Windows release on Windows 10 or Windows 11 with Python 3.12 and Inno Setup 6 installed:

```text
build_release.bat
```

Choose `1 Normal incremental build` for the usual release build. The expected output is:

```text
Release\Setup.exe
Release\Portable\RePhiEditAutoChartAssistant.exe
```

## Quick Start

1. Open Re:PhiEdit Auto Chart Assistant.
2. Click **Select Audio** and choose an MP3, WAV, FLAC, OGG, M4A, AAC, or ALAC file.
3. Select a difficulty: EZ, HD, IN, or AT.
4. Adjust density, style, timing offset, or note-type options if needed.
5. Choose **PEZ Import Package** as the output mode.
6. Click **Generate**.
7. Open Re:PhiEdit and use **Import** to load the generated `.pez` file.
8. Continue editing the chart manually in Re:PhiEdit.

## Workflow

The generator follows a deterministic rule-based pipeline:

1. Decode and analyze audio.
2. Estimate BPM, beats, onsets, energy, and sections.
3. Build rhythm candidates from onsets and beat subdivisions.
4. Group candidates into phrases and patterns.
5. Assign note types and X positions through the layout generator.
6. Validate timing, Hold legality, density, and structure.
7. Export as PEZ, folder package, or `chart.json`.

## Supported Output

- `.pez`: recommended output for Re:PhiEdit Import.
- Folder package: contains chart data, info file, audio, and default illustration for inspection.
- `chart.json`: raw chart export for advanced users and debugging.
- Analyzer reports: JSON, CSV, and HTML.
- Comparison reports: generated when comparing two charts.

## GUI Overview

The GUI includes:

- Audio selection.
- Batch selection.
- Difficulty selector.
- Density slider.
- Hold, Drag, and Flick toggles.
- Auto Timing Calibration toggle.
- Manual Offset ms control.
- Snap Strength control.
- BPM-aware Density toggle.
- Chart Style selector: Official-like, Balanced, Dense, Experimental.
- Output mode selector: PEZ, folder package, or `chart.json`.
- Waveform display.
- Density chart.
- Pattern Density preview.
- Layout Heatmap.
- Phrase Preview.
- 2D Note Preview.
- Generation statistics and logs.

## Command Line Usage

The GUI is the recommended interface, but a CLI is available for development and automation.

Generate a PEZ file:

```sh
rephi-auto-chart generate song.mp3 --pez -d HD -o output.pez
```

Generate raw `chart.json`:

```sh
rephi-auto-chart generate song.wav -d IN -o chart.json
```

Export an unpacked folder package:

```sh
rephi-auto-chart generate song.wav --package-dir exported_package
```

Analyze a chart or PEZ:

```sh
rephi-auto-chart analyze-chart chart.json -o analysis_report
```

Compare two charts:

```sh
rephi-auto-chart compare official.pez generated.pez -o comparison_report
```

Batch-generate PEZ files:

```sh
rephi-auto-chart batch song1.mp3 song2.mp3 -d HD -o batch_output --format pez
```

Create a default config file:

```sh
rephi-auto-chart init-config config/default_config.json
```

## Configuration

The default config is stored in:

```text
config/default_config.json
```

Important options include:

- `difficulty`: EZ, HD, IN, or AT.
- `overall_density`: global density multiplier.
- `tap_weight`, `drag_weight`, `hold_weight`, `flick_weight`: note-type weighting.
- `min_interval`: optional minimum note interval override.
- `max_bpm_precision`: beat-time precision for exported chart data.
- `enable_hold`, `enable_drag`, `enable_flick`: note-type toggles.
- `auto_timing_calibration`: enable automatic timing offset recommendation.
- `manual_offset_ms`: manual timing correction in milliseconds.
- `snap_strength`: beat-grid snap strength.
- `bpm_aware_density`: enable BPM-aware density targeting.
- `chart_style`: Official-like, Balanced, Dense, or Experimental.
- `max_hold_duration_by_difficulty`: Hold duration caps by difficulty.

For installed and portable Windows builds, user config and runtime data are created under `%LOCALAPPDATA%\RePhiEditAutoChart`.

## Project Structure

```text
rephi_auto_chart/        Core Python package
config/                  Default configuration
assets/                  Application icons
installer/               Inno Setup installer script
packaging/windows/       PyInstaller spec, entry point, and version metadata
scripts/                 Developer and release helper scripts
docs/                    Format, algorithm, testing, release, and roadmap docs
tests/                   Regression tests
README.md                Project documentation
CHANGELOG.md             Release history
LICENSE                  License file
```

## Known Limitations

- V2.5.2 is a rule-based generator.
- It generates editable draft charts, not final human-quality charts.
- It does not produce official Phigros charts.
- It does not learn from reference charts or imitate a specific charter style.
- Timing and accent detection are based on traditional audio analysis and may need manual correction.
- Complex music with tempo changes, weak transients, or dense layered instruments may require more editing.
- The current chart output is intentionally conservative: one judge line, no gimmicks, no complex line movement.
- Final chart quality depends on manual refinement in Re:PhiEdit.

## Roadmap

V3 is planned as a learning-based generation direction. The broad goals are:

- Learn from user-provided audio and reference chart pairs.
- Model timing, phrase, density, lane, and pattern choices from examples.
- Support configurable style profiles.
- Keep the V2 rule-based system as a validator, fallback, and post-processing layer.

No release date is currently promised.

## Contributing

Contributions are welcome if they keep the project practical and compatible with Re:PhiEdit workflows.

Good contribution areas include:

- Format compatibility fixes.
- Export/import validation improvements.
- Test coverage.
- Documentation clarity.
- Windows packaging reliability.
- Audio analysis improvements that do not require training data.

Before changing generation behavior, please add or update tests that show the intended chart-quality improvement.

## License

This project is released under the license in [LICENSE](LICENSE).

## Acknowledgements

- Re:PhiEdit / Phigros Fanmade Chart Editor community for the target editing workflow.
- The open-source Python audio ecosystem, including NumPy, SciPy, soundfile, and librosa.
- PyInstaller and Inno Setup for Windows release packaging.

Re:PhiEdit and Phigros are names associated with their respective owners and communities. This project is an independent helper tool and is not an official Re:PhiEdit or Phigros product.
