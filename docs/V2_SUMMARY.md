# V2 Summary

V2 is complete as the rule-based generation era of Re:PhiEdit Auto Chart Assistant. V2.4.0 is the final rule-based feature release.

## Completed Goals

- Real `.pez` export compatible with Re:PhiEdit Import.
- GUI generation workflow for ordinary users.
- Windows one-click run and build scripts.
- Audio decoding for WAV and optional MP3/FLAC/OGG paths.
- BPM-aware density.
- Timing Calibration.
- Accent Detection.
- Density Filler.
- Analyzer, Compare, and Batch modes.
- Tap as the default playable language.
- Drag ratio limits and deliberate Drag Chain generation.
- Hold legality validation and AT Hold control.
- Phrase Generator.
- Pattern Generator.
- Pattern Library.
- Spatial Layout Generator.
- Pattern Diversity, Layout Diversity, and Playability scoring.
- Quality Evaluator.

## Final V2 Design

V2.4 uses deterministic audio rules:

1. Audio Analysis
2. Section Analysis
3. Candidate timing and density selection
4. Phrase grouping
5. Pattern Generation
6. Spatial Layout
7. Difficulty Scaling
8. Validation
9. Export

The generator plans phrase-level patterns first, then maps patterns to notes and layout. This produces a more coherent editable draft than isolated per-note classification.

## Practical Limit

V2 can generate useful editable reference drafts. It cannot fully infer human charting intent, author style, instrument identity, or advanced musical phrasing from rules alone. Continuing to add rules will have decreasing returns because new rules increasingly conflict across genres and charting styles.

V2 should now be treated as:

- a stable fallback generator
- a post-processing layer
- a validation layer
- a quality checker
- a deterministic baseline for V3

V3 should move to learning-based generation using user-provided Audio + Reference Chart pairs, while keeping V2 as fallback and validator.
