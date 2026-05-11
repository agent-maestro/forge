"""Forge safety-verification backend.

Implements `@verify(<safety_class>, ...)` annotations for the
EML safety verification protocol v0.1. Phase 1 ships the
`temporal_frequency` class; Phase 2 will add `spatial_pattern`,
`saturated_red`, and pipeline composition.

Protocol contract:
  monogate-research/roadmap/safety-verification-protocol.md

Implementation spec:
  monogate-engine/docs/forge-safety-analyzer-spec.md

Public entrypoints:
  - `SafetyBackend` — Forge backend class following the LeanBackend
    / IsabelleBackend / CoqBackend pattern. Filters @verify
    annotations by safety class, runs the appropriate analyzer.
  - `analyze_file()` — convenience function for standalone usage.
"""
from .safety_backend import (
    SafetyBackend,
    SafetyClass,
    SafetyAnalysisResult,
    SafetyViolation,
    TemporalFrequencyAnalyzer,
    analyze_file,
)

__all__ = [
    "SafetyBackend",
    "SafetyClass",
    "SafetyAnalysisResult",
    "SafetyViolation",
    "TemporalFrequencyAnalyzer",
    "analyze_file",
]
