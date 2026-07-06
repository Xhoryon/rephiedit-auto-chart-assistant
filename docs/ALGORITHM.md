# Algorithm Notes

## V2.0 Problem

V2.0 mainly used onset detection plus sparse deterministic gates. This made charts importable, but AT density could collapse on simple audio because the generator only kept a small fraction of beat/onset candidates. Accent placement also depended too much on section labels, so Flick and heavy notes could appear in weak places while real drum accents were missed.

## V2.1 Pipeline

V2.1 keeps the same export format and one-line chart limitation, but replaces the generation core:

1. Decode audio and compute normalized frame energy.
2. Build an attack curve from positive energy deltas.
3. Detect onsets, estimate BPM, build beat grid, and segment Intro/Verse/Drop/Bridge/Outro.
4. Estimate timing offset from onset peaks against a 1/16 beat grid.
5. Build difficulty-specific candidates from onsets and beat subdivisions.
6. Refine each candidate to a local attack peak.
7. Snap near-grid candidates according to `snap_strength`.
8. Score candidates with accent features.
9. Select candidates to satisfy target NPS and note-count floors.
10. Backfill if actual density is clearly below target.
11. Assign Tap/Hold/Drag/Flick using stable context rules.
12. Apply readable lane patterns.
13. Export a quality report into `META.autoChartReport`.

## V2.1 Drag Problem

V2.1 fixed low AT density, but the classifier still treated continuous short-interval candidates as Drag too aggressively. That made AT/IN charts look dense while feeling unlike Phigros/Phira reference charts, where Tap streams are the normal expression of repeated rhythm and Drag is a special gesture.

The root cause was priority order: Drag evidence was checked before Tap default behavior. V2.2 changes this so Tap is the baseline type and Drag must prove that it is a hat roll, slide-like melody, explicit decorative pattern, or user-weighted choice.

## V2.2 BPM-Aware Density

V2.2 no longer treats AT as a fixed note count or fixed NPS. The target is computed from three components:

- `target_notes_from_bpm`
- `target_notes_from_onsets`
- `target_notes_from_energy`

The BPM component uses:

```text
total_beats = song_length_seconds * BPM / 60
target_notes_from_bpm = total_beats * subdivision_density * difficulty_multiplier * section_multiplier
```

Low BPM charts can use more subdivisions per beat. High BPM charts are capped by minimum interval and maximum practical notes per second so they do not grow without limit.

The onset component reflects detected rhythmic material. The energy component lifts high-energy sections and drops. The final target is a weighted blend of all three, then clamped by playability:

```text
target_notes_final = weighted(BPM target, onset target, energy target)
target_notes_final <= duration / min_interval
```

The report includes:

- `BPM`
- `song_length`
- `total_beats`
- `onset_count`
- `target_notes_from_bpm`
- `target_notes_from_onsets`
- `target_notes_from_energy`
- `target_notes_final`
- `actual_notes`
- `actual_nps`

## Density System

Difficulty presets are defined in `rephi_auto_chart/config.py` and include:

- `target_nps`
- `min_notes_per_minute`
- `max_notes_per_minute`
- `section_density_multiplier`
- `drop_density_multiplier`
- `chorus_density_multiplier`
- `min_interval`

EZ keeps only core rhythm. HD covers main beats and important onsets. IN keeps most rhythm detail. AT uses 1/16 and 1/32-like candidate density through 1/8 beat subdivisions plus onsets, then backfills until the target floor is reached when possible.

The final report includes:

- `song_length`
- `note_count`
- `average_nps`
- `max_10s_nps`
- `difficulty`
- `density_target`
- `density_actual`

## Timing Calibration

V2.1 adds `rephi_auto_chart/timing.py`.

`recommended_offset_ms` is estimated by comparing detected onset peaks against a beat subdivision grid. The generator applies:

- automatic recommended offset when enabled
- `manual_offset_ms`
- legacy `offset_ms` for compatibility

Positive offset moves generated notes later. Negative offset moves notes earlier.

Before placing a note, V2.1 also:

- refines each candidate to the strongest nearby attack peak
- snaps near 1/4, 1/8, or 1/16 grid positions
- blends snap distance by `snap_strength`
- avoids forcing far off-beat events onto the grid

## Accent Detection

V2.1 added `rephi_auto_chart/accent.py`; V2.2 extends it with lightweight frequency-band energy.

Each candidate receives:

- `accent_score`
- `kick_score`
- `snare_score`
- `hat_score`
- `energy_score`
- `onset_score`
- `section_intensity`
- `bass_energy`
- `mid_energy`
- `high_energy`

The current implementation uses RMS-like energy, positive energy flux, local peak prominence, onset density, beat proximity, section intensity, and Goertzel band probes:

- kick: low-frequency energy around 20-160 Hz
- snare/crash body: mid/high transient energy around 150-4000 Hz
- hat/crash brightness: high-frequency transient energy above roughly 5000 Hz

It is not full drum separation, but it is more stable than using onset presence alone.

## Note Type Rules

Tap:

- default note type
- kick-like hits
- main beats
- clear non-explosive onsets
- ordinary continuous rhythm streams

Flick:

- strong accents
- strong snare-like transients
- Drop accents
- limited by minimum Flick gap and consecutive Flick cap

Drag:

- hat-like rolls
- slide-like melody evidence
- small decorative chains in dense sections
- explicit user Drag weighting
- capped by difficulty ratio
- isolated Drag is downgraded to Tap

Hold:

- sustained energy regions
- minimum length threshold
- avoided inside dense short-note bursts

V2.2 classifier priority:

1. Tap is the default.
2. Hold only wins with sustained-energy evidence.
3. Flick only wins with strong accent/drop/snare/crash evidence.
4. Drag only wins with enough drag evidence and a valid short chain.

Each generated report includes `note_type_debug`, with `selected_type`, `type_reason`, `tap_score`, `hold_score`, `flick_score`, and `drag_score` for the first notes.

## Drag Ratio Control

Default caps:

- EZ: 0.05
- HD: 0.08
- IN: 0.12
- AT: 0.16

After classification, the generator downgrades isolated Drag notes and excess low-evidence Drag notes to Tap. This keeps Tap as the playable body of the chart.

## Density Filler

If the selected notes fall below the target floor, V2.2 fills deterministically. It does not randomize. Fill priority is encoded through candidate scoring:

1. high accent unused points
2. strong onset points
3. beat subdivision points
4. high-energy sections
5. repeated pattern locations

The filler still obeys `min_interval`, practical maximum density, note type ratio limits, and pattern readability.

## Chart Styles

- `Official-like`: Tap-heavy, conservative Drag, Flick for accents, Hold for sustained sound.
- `Balanced`: slightly more decorative while keeping Tap as the main body.
- `Dense`: more high-energy subdivision fill.
- `Experimental`: more aggressive decoration, still ratio-capped.

## V2.3 Phrase Generator

V2.3 is the final rule-based V2 algorithm. It adds a phrase layer above note classification.

Instead of deciding each note independently, the generator now:

1. Selects candidate rhythm points with V2.2 density logic.
2. Groups neighboring candidates into phrases.
3. Labels phrases as Tap Stream, Drag Chain, Hold Phrase, Accent Phrase, Burst, Build, or Outro.
4. Applies a Pattern Library to the full phrase.
5. Classifies notes with phrase context.
6. Scores the result with the Quality Evaluator.

This makes the output closer to a human reference draft: Tap remains the main language, while Drag, Hold, and Flick become phrase-level modifiers.

## Drag Chain Generator

Drag Chain is no longer a collection of isolated Drag notes. V2.3 detects continuous high-frequency, hat-like, build-up, drop, or forward-motion material and creates a chain.

Rules:

- minimum length: 2
- maximum length: 12
- common length: 3-6
- patterns: Left->Right, Right->Left, Stair, Zigzag, Center, Wave

The chain uses deterministic lane movement from `rephi_auto_chart/patterns.py`.

## Pattern Library

The rule library includes:

- Tap Stream
- Alternating
- Double
- Triple
- Stair
- Burst
- Drag Chain
- Jack
- Trill
- Wave
- Jump
- Center Expand
- Center Close
- Drop Pattern
- Build Pattern
- Outro Pattern

Patterns are selected by phrase and section, not randomly.

## Section Generator

Section behavior:

- Intro: Tap-heavy and readable.
- Verse: Tap streams with small phrase variation.
- Build: increasing movement through Build Pattern and occasional Drag Chain.
- Drop: Tap + Burst + Drag Chain + accent Flick.
- Bridge: reduced density and simpler phrases.
- Outro: gradually simpler Outro Pattern.

## Quality Evaluator

After generation, V2.3 scores:

- Density
- Timing
- Pattern Diversity
- Phrase Quality
- Type Balance
- Readability
- Flow
- Overall

If Overall is below 80, generation may run once more with a slightly denser Balanced profile and keep the better result.

## Pattern System

Lane placement is deterministic and readable:

- EZ: simple two-lane alternation
- HD: alternation and triples
- IN: stairs, four-runs, triples, bursts
- AT: stairs, bursts, Drop patterns, wide Flick accents

The goal is to avoid both fixed-position monotony and random lane noise.

## V2.4 Rule-Based Final Architecture

V2.4 is the final feature release of the rule-based generator. It keeps the V2.1/V2.2 audio, timing, accent, and BPM-aware density layers, but changes how selected rhythm candidates become chart objects. The generator now follows this pipeline:

1. **Audio Analysis**: decode audio, estimate BPM, detect onsets, energy, long regions, and section labels.
2. **Section Analysis**: classify Intro, Verse, Build, Drop, Bridge, and Outro intensity.
3. **Pattern Generation**: group selected candidates into `PatternBlock` objects before creating notes.
4. **Spatial Layout**: assign X positions with lane balance, side balance, jump limits, and same-lane run control.
5. **Difficulty Scaling**: EZ/HD stay simple; IN/AT use more complex Pattern blocks and richer movement.
6. **Validation**: enforce note legality, Hold legality, pattern sanity, layout sanity, and PEZ-safe output.
7. **Export**: write chart.json, folder package, or PEZ without changing the chart format.

This replaces the older style where each candidate independently decided lane and type. The goal is to create a coherent editable draft rather than a list of isolated audio detections.

## V2.4 Pattern Generator

`rephi_auto_chart/pattern_generator.py` plans patterns before notes. The Pattern Library includes:

- Single
- Double
- Triple
- Quad
- Alternating
- Stair
- Jump
- Burst
- Stream
- Anchor
- Jack
- Trill
- Drag Chain
- Hold Anchor

Pattern choice is deterministic. It uses phrase label, section, local accent, hat/onset evidence, difficulty, and recent pattern repetition. AT favors Stream, Burst, Stair, Jump, Anchor, and Drag Chain where the audio supports them. Hold Anchor is conservative and must not dominate rhythmically active sections.

The report includes:

- `pattern_count`
- `pattern_histogram`
- `pattern_diversity_score`
- `pattern_complexity`
- `longest_same_pattern`
- pattern preview data for the GUI

## V2.4 Spatial Layout Generator

`rephi_auto_chart/layout.py` owns X-position placement. It receives Pattern blocks and note context, then assigns lanes with:

- left/right balance
- center balance
- pattern phase rotation
- same-lane run limits
- same-side run limits
- jump-distance limits
- lane concentration rebalancing
- Hold-safe rhythm placement

The report includes:

- `layout_diversity_score`
- `playability_score`
- `average_jump_distance`
- `hand_alternation_score`
- `lane_distribution`
- `longest_same_lane`
- layout validator warnings

Layout Generator intentionally avoids completely random lanes. Repeated rhythms should look readable: alternating streams, stairs, bursts, anchor patterns, and drag chains use stable movement templates with phase rotation so sections do not all begin on the same side.

## V2.4 AT Difficulty

AT no longer means only more notes. The AT profile increases:

- Pattern Complexity
- Layout Complexity
- Rhythm Complexity
- subdivision retention in dense sections
- controlled Drag Chain use
- accent Flick placement

AT still treats Tap as the main language. Drag is a second-language gesture used in chains or high-frequency phrases. Hold remains a sustain marker and is capped by ratio, duration, and timeline coverage. Flick remains an accent marker.

## V2.4 Validation And Quality

V2.4 keeps V2.3.2 Hold legality checks and adds generator-side checks before final validation:

- Hold Playability enforcement after fallback sustain Hold insertion.
- Same-time same-lane pre-validation collision handling.
- Pattern validator for unknown or repeated patterns.
- Layout validator for lane concentration and long same-lane runs.

Quality reporting now combines density, phrase, pattern, layout, and playability information. If the rule-based system cannot infer enough musical intent, V2.4 prefers a simpler playable draft over a dense but awkward chart.

## Known Limits

- No multi-BPM or per-section BPM map yet.
- Timing offset is global plus local peak correction, not a full dynamic time-warp.
- Accent detection uses lightweight audio features; it does not perform real instrument separation.
- Generated charts are editable references, not finished human charts.


## V2.3.2 Hold Legality Baseline

Real Re:PhiEdit testing found that the previous V2.3 baseline could produce Tap, Drag, or Flick notes inside the visible body of a Hold on the same judge line and nearby X position. Re:PhiEdit documents Hold as a note with both start and end time, and its chart checker treats overlapping Tap/Hold and Hold/Hold situations as errors. V2.3.2 therefore added a final structural validator after generation; V2.4 keeps that validator and adds generator-side Hold Playability checks before final validation.

The validator now exposes:

- `detect_notes_inside_holds(chart)`
- `repair_notes_inside_holds(chart)`

Repair prefers preserving rhythm notes. If an important Tap, Drag, or Flick lands inside a Hold region, the Hold is trimmed or split around that rhythm note. Only unusably short Hold fragments are removed. This keeps AT rhythm coverage while preventing illegal blue-bar overlap.

Hold generation is also stricter. Hold evidence now combines sustained region duration, low onset density, spectral/energy stability proxy, low kick/snare/hat transient score, and phrase context. RMS stability alone is not enough. AT uses the strictest threshold, a 2.0 second max Hold duration, and a timeline coverage cap. Long sustain in AT is expressed as short Hold decoration plus Tap/Drag/Flick rhythm, not one long blue bar covering the section.

The report adds:

- `hold_count`
- `hold_ratio`
- `longest_hold_duration`
- `hold_timeline_coverage`
- `notes_inside_hold_fixed_count`
- `holds_trimmed_count`
- `holds_split_count`

Hold and Flick are allowed to be rare. Tap remains the body of the chart, Drag remains phrase/chain decoration, and Hold is only used when the audio actually supports sustain.
