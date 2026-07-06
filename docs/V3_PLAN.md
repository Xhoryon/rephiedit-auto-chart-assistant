# V3 Plan: Learning-Based Auto Charter

V3 should not continue by adding more rules. It should become a learning-based auto charter.

## Core Idea

Allow users to provide:

- Audio
- Reference Chart

The system learns:

- Pattern choices
- Timing tendencies
- Density curves
- Lane movement
- Phrase structure
- Note type usage
- Section handling
- Charter style

Then it generates charts that match a selected reference style.

## V2 Role In V3

V2 should remain in the system as:

- Post Processing
- Quality Checker
- Fallback System
- Format Exporter
- Timing Validator
- PEZ Packager

## Suggested V3 Modules

- Reference chart parser and feature extractor
- Audio/chart alignment system
- Phrase and pattern embedding system
- Style profile builder
- Candidate generator
- Learned ranking model
- Rule-based post processor using V2
- Human-edit feedback loop

## Non-Goals For V2

V2 will not implement:

- neural network training
- user style learning
- reference-chart supervised generation
- model fine-tuning

Those belong to V3.
