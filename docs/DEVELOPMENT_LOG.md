# Development Log

## V2.4.0 Rule-Based Final Feature Release

Current goal: make the V2 rule-based generator produce more human-readable first drafts by reorganizing generation around Pattern blocks and Spatial Layout rather than isolated per-note decisions. No machine learning, reference-chart training, or AI model behavior was introduced.

Architecture changes:
- Added `rephi_auto_chart/pattern_generator.py` for PatternBlock planning.
- Added `rephi_auto_chart/layout.py` for X-position layout, lane balance, and playability metrics.
- Updated `rephi_auto_chart/generator.py` so selected candidates become phrases, then pattern blocks, then notes, then layout, then validation.
- Updated the GUI to show Pattern Density, Layout Heatmap, Pattern Diversity, Layout Diversity, Playability, average jump distance, hand alternation, longest same pattern, and longest same lane.

Important debugging result:
- Initial V2.4 integration caused `Hold Anchor` to dominate sustained pattern songs and concentrate notes on the left lane.
- Root cause was that Hold Phrase labels were too permissive on sustained-but-rhythmic audio, pattern lane templates restarted from the same phase each block, and fallback sustain Hold insertion happened after type-ratio enforcement.
- Fixes: stricter AT Hold Phrase gate, pattern phase rotation, lane concentration rebalancing, post-sustain Hold Playability enforcement, and pre-validator same-time same-bucket collision handling.

Tests added:
- `test_v240_pattern_generator_exposes_rule_based_library`
- `test_v240_report_includes_pattern_layout_playability_metrics`
- `test_v240_layout_avoids_long_same_lane_runs`
- `test_v240_at_uses_more_pattern_complexity_than_hd`
- `test_v240_layout_validator_keeps_hold_conflicts_clean`

Verification performed in macOS workspace:
- `env PYTHONPYCACHEPREFIX=/private/tmp/rephi_pycache_v240 python3 -m unittest discover -s tests`: 50 tests passed.
- `env PYTHONPYCACHEPREFIX=/private/tmp/rephi_pycache_v240 python3 -m py_compile rephi_auto_chart/*.py packaging/windows/gui_entry.py`: passed.

Remaining release requirement:
- Windows `build_release.bat` and Inno Setup installer compilation still must be run on Windows 10/11 with Python 3.12 and Inno Setup 6.

## Release 2.4.0

### Goal

Prepare the first formal Windows release for ordinary users.

### Completed

- Self-contained PyInstaller application configuration.
- Inno Setup professional installer.
- Release output layout:
  - `Release\Setup.exe`
  - `Release\Portable\RePhiEditAutoChartAssistant.exe`
- Desktop shortcut.
- Start menu shortcut.
- Optional `.pez` association for Analyzer.
- Runtime folders under `%LOCALAPPDATA%\RePhiEditAutoChart`.
- Damaged config auto-repair.
- Update checker placeholder for V3.
- Version metadata and custom icon.
- Release checklist.
- Clean repository layout with generated outputs removed.

### Verification

- `python3 -m unittest discover -s tests`: passed.
- `env PYTHONPYCACHEPREFIX=.pycache_tmp python3 -m py_compile rephi_auto_chart/*.py packaging/windows/gui_entry.py`: passed.
- Static release packaging tests passed.

### Build Requirement

Final `Setup.exe` compilation requires Windows 10/11 with Python 3.12 and Inno Setup 6. This macOS workspace cannot compile the installer binary.

## V2.3 Release Candidate Final Hotfix - Runtime Data Directory Fix

Current goal: fix the installed Windows release writing to `./outputs` under `C:\Program Files\RePhiEdit Auto Chart Assistant`, which caused `PermissionError: [WinError 5]` for normal users.

Analysis:
- The installed GUI still initialized `Export To` with `outputs/generated.pez`.
- Mode switching reset output paths to `outputs/generated.pez`, `outputs/generated_rephi_folder`, or `outputs/generated_chart.json`.
- The bundled default config still contained `export_path: outputs/generated_chart.json`.
- Startup diagnostics special-cased only one old relative path and could still probe current-working-directory paths.
- This failed after installation because the app working directory is under Program Files, which is not writable for normal users.

Technical decision:
- Runtime app data belongs under `%LOCALAPPDATA%\RePhiEditAutoChart`.
- User-facing chart exports belong under `%USERPROFILE%\Documents\RePhiEdit Charts` by default.
- Relative output paths are treated as unsafe for the release GUI and are migrated to the Documents export folder.
- PyInstaller `_internal` resource lookup remains unchanged and continues to support bundled config/docs/assets.

Files changed:
- `rephi_auto_chart/runtime.py`: added `export_root`, Documents export folder helpers, runtime config read/write helpers, export path migration, and safe output directory resolution.
- `rephi_auto_chart/gui.py`: removed `./outputs` defaults, initializes from runtime config or Documents default, persists user-selected export paths, and uses Documents defaults for mode switching.
- `rephi_auto_chart/diagnostics.py`: checks writable output folders through runtime-safe resolution instead of probing `./outputs`.
- `rephi_auto_chart/config.py`: changed default `export_path` to empty so runtime policy chooses the correct release-safe path.
- `config/default_config.json`: removed stale `outputs/generated_chart.json` default.
- `rephi_auto_chart/cli.py`: developer CLI defaults now use runtime outputs or Documents export paths instead of repository-relative `outputs`.
- `release_check.ps1`: added checks preventing GUI/default config from reintroducing relative `outputs/generated...` defaults.
- `tests/test_core.py`: added regression tests for LocalAppData runtime folders, Documents export folder, migration away from relative outputs, and GUI/default config safety.
- `README.md` and `docs/RELEASE_CHECKLIST.md`: documented the runtime data and default export directory policy.

Verification performed in this macOS workspace:
- `python3 -m unittest discover -s tests`: 38 tests passed.
- `python3 -m py_compile rephi_auto_chart/*.py packaging/windows/gui_entry.py`: passed.
- `packaging/windows/gui_entry.py --smoke-check` with isolated `LOCALAPPDATA` and `USERPROFILE`: created LocalAppData folders and `Documents/RePhiEdit Charts`.
- Generated a test PEZ with isolated environment: output path was `Documents/RePhiEdit Charts/generated.pez`.

Windows release verification still required:
- Run `build_release.bat`, choose `1 Normal incremental build`.
- Confirm `Release\Setup.exe` and `Release\Portable\RePhiEditAutoChartAssistant.exe` are regenerated.
- Run `release_check.ps1` and confirm all checks pass.
- Install the new Setup.exe as a normal Windows user and confirm Generate writes to Documents without `PermissionError` or `WinError 5`.


## V2.3.2 Hotfix - Hold Legality and AT Hold Control

Current goal: fix real Re:PhiEdit playback/editing issues where Tap/Drag/Flick notes could appear inside Hold bodies and some AT charts became Hold-dominated.

Document review:
- Re-read `!) HelpDocument.pdf` from the Re:PhiEdit install. The document defines four note types: Tap, Drag, Flick, and Hold. All notes have start time and X coordinate; Hold also has end time. The chart checker section lists Tap/Hold and Hold/Hold overlaps as errors, confirming that generated Hold regions must be structurally checked, not only exported.

Root cause:
- `validate_and_fix_chart()` only repaired negative time, illegal types, same-time same-X collisions, and Hold end-before-start. It did not detect non-Hold notes inside the time span and X region of an existing Hold.
- `_hold_length()` allowed up to 2.4 seconds for every difficulty and did not use per-difficulty caps.
- AT `_ensure_all_types()` forced a Hold even when the source was a click track or dense transient rhythm with no sustain evidence.
- Hold classification accepted phrase-level Hold too early and could treat sustained RMS as enough evidence even when neighboring rhythm density was high.

Implementation:
- Added `detect_notes_inside_holds()` and `repair_notes_inside_holds()` in `rephi_auto_chart/validator.py`.
- Repair trims or splits Hold segments around protected Tap/Drag/Flick notes in the same X region, preserving rhythm notes whenever possible.
- Added Hold metrics to `ValidationReport`.
- Added `max_hold_duration_by_difficulty` to `AssistantConfig` with EZ 4.0, HD 3.5, IN 3.0, AT 2.0.
- Generator now passes `config.max_hold_duration` into final validation.
- Hold evidence now requires sustained region duration, low onset/transient score, low nearby rhythm density, and stricter AT gating.
- Type ratio enforcement now caps excessive Hold and downgrades low-evidence excess Hold to Tap; it does not create Hold to satisfy ratios.
- AT fallback type coverage no longer forces Hold on non-sustain audio.
- `META.autoChartReport` now reports final post-validation Hold counts, ratio, longest Hold duration, timeline coverage, and repair counts.

Tests added/updated:
- `test_no_tap_inside_hold`
- `test_no_notes_inside_hold_region`
- `test_at_hold_duration_limit`
- `test_long_sustain_split_for_at`
- `test_at_not_hold_dominated`
- `test_at_has_external_rhythm_notes`
- `test_hold_does_not_suppress_density`
- Updated older tests that incorrectly required Hold on click-track or non-sustain audio.

Verification in macOS workspace:
- `python3 -m unittest discover -s tests`: 45 tests passed.
- `python3 -m py_compile rephi_auto_chart/*.py packaging/windows/gui_entry.py`: passed.

Windows release follow-up:
- Regenerate release artifacts on Windows with `build_release.bat`, choose `1 Normal incremental build`.
- Install the new `Release\Setup.exe` and verify PEZ generation in Re:PhiEdit with no Tap/Drag/Flick inside Hold bodies and no AT Hold domination.


## V2.3.2 Final Release整理

目标：将已经包含 V2.3.2 Hotfix 的工程正式整理为 V2.3.2 Release Candidate Final。

执行内容：
- 工程目录已重命名为 `re-phiedit-auto-chart-assistant-v2.4.0`。
- 统一源码、GUI 标题、PyInstaller version info、Inno Setup `AppVersion`、`release_check.ps1`、`pyproject.toml`、`VERSION`、README、CHANGELOG 和 Release Checklist 到版本 `2.4.0`。
- 删除旧 `build/`、`dist/`、`Release/`，避免旧 `Setup.exe` 被误发为 V2.4.0。
- 删除旧 `rephi_auto_chart_assistant.egg-info` 和 `.DS_Store` 生成产物。
- 保留 `.venv-windows-build`，供 Windows Normal incremental build 复用依赖。

验证结果（macOS 侧）：
- `python3 -m unittest discover -s tests`: 45 tests passed。
- `python3 -m py_compile rephi_auto_chart/*.py packaging/windows/gui_entry.py`: passed。
- 版本和路径扫描：源码、脚本、installer、tests、docs 中无旧当前版本号残留。
- PEZ smoke：隔离 `LOCALAPPDATA` 和 `USERPROFILE` 后成功创建 runtime folders 和 `Documents/RePhiEdit Charts/pattern.pez`。
- Hold smoke：AT pattern 样本 `inside_holds=0`，`longest_hold_duration=2.0`，`hold_ratio=0.0132`。

未在本机完成：
- `build_release.bat`、`release_check.ps1`、Inno Setup 编译、Setup.exe 安装验证必须在 Windows 10/11 + Python 3.12 + Inno Setup 6 环境运行。
- 当前 macOS 环境没有 PowerShell/Inno Setup，不能生成新的 `Release/Setup.exe`。

发布状态：源码和发布工程已整理到 V2.4.0，但正式 GitHub Release 仍需 Windows 端重新运行 `build_release.bat` 选择 `1 Normal incremental build` 并通过 `release_check.ps1` 后再发布。
