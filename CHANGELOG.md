# Changelog

## 2.4.0

Rule-based final feature release.

### Added

- Added `rephi_auto_chart/pattern_generator.py`, a deterministic Pattern Generator that plans Pattern blocks before note emission.
- Added `rephi_auto_chart/layout.py`, a Spatial Layout Generator for X-position balance, lane diversity, jump control, and playability scoring.
- Added Pattern Library entries: Single, Double, Triple, Quad, Alternating, Stair, Jump, Burst, Stream, Anchor, Jack, Trill, Drag Chain, and Hold Anchor.
- Added final report metrics: `pattern_diversity_score`, `layout_diversity_score`, `playability_score`, `average_jump_distance`, `hand_alternation_score`, `lane_distribution`, `pattern_histogram`, `longest_same_pattern`, and `longest_same_lane`.
- Added GUI Pattern Density and Layout Heatmap previews, plus Pattern/Layout/Playability statistics.
- Added validators for pattern plans and layout distribution.
- Added regression tests for pattern library coverage, V2.4 report metrics, layout lane-run avoidance, AT pattern complexity, and Hold-safe layout validation.

### Changed

- Reorganized generation flow around phrase-level Pattern blocks and spatial layout instead of per-note lane decisions.
- AT difficulty now favors Pattern Complexity, Layout Complexity, and Rhythm Complexity instead of simply raising note count.
- Hold Phrase generation is stricter in AT and must not dominate sustained but rhythmically active sections.
- Hold playability enforcement now runs after fallback sustain Hold insertion and before final validation, preventing fallback Hold from bypassing ratio and coverage rules.
- Pre-validator same-time same-lane collision handling avoids moving rhythm notes into Hold regions during final validation.

### Fixed

- Fixed V2.4 integration regression where many Hold Anchor phrases could concentrate notes on one side and trigger layout warnings.
- Fixed fallback sustain Hold bypassing Hold ratio and timeline coverage caps.
- Fixed a validator interaction where same-time collision repair could create a note-inside-Hold repair after generator-side Hold checks.

## 2.3.2

### Fixed

- Added final Hold legality validation so Tap, Drag, and Flick notes cannot remain inside the same-line, same-X-region time span of a Hold.
- Added automatic Hold repair that trims or splits Hold segments around protected rhythm notes instead of deleting rhythm.
- Added per-difficulty maximum Hold durations: EZ 4.0s, HD 3.5s, IN 3.0s, AT 2.0s.
- Made AT Hold generation stricter: Hold now requires strong sustain evidence and low transient density.
- Stopped AT type balancing from forcing Hold merely to satisfy key-type coverage.
- Added Hold quality metrics to `META.autoChartReport`: `hold_ratio`, `longest_hold_duration`, `hold_timeline_coverage`, `notes_inside_hold_fixed_count`, `holds_trimmed_count`, and `holds_split_count`.

### Tests

- Added regressions for notes inside Hold regions, AT Hold duration limits, long-sustain repair, AT not being Hold-dominated, and rhythm density not being suppressed by Hold.

## 2.3.0

First formal release.

### Added

- Professional Windows release pipeline with `Release\Setup.exe` and `Release\Portable`.
- One-click release build through `build_release.bat`.
- Inno Setup installer with Windows 10+ check, x64-compatible architecture check, VC++ Runtime check, shortcuts, icon, version metadata, optional `.pez` association, and uninstall support.
- Portable PyInstaller build with bundled GUI, analyzer, exporter, and audio dependencies.
- First-launch runtime folders under `%LOCALAPPDATA%\RePhiEditAutoChart`.
- Runtime config repair for damaged JSON config.
- Update checker placeholder for V3.
- Version metadata and custom icon.
- Release checklist.
- Clean repository layout with generated outputs removed.

### Changed

- Tap remains the primary note language.
- Drag, Hold, and Flick are phrase-level modifiers rather than ratio targets.
- README reorganized for ordinary Windows users first.

### Known Limits

- Final `Setup.exe` must be built on Windows with Inno Setup 6.
- V2 remains rule-based; V3 should move to learning-based generation.
