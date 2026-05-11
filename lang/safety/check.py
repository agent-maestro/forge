"""Safety-check phase for Forge's compile pipeline.

Algorithm:
  1. Read the .eml source file (or accept source text directly)
  2. Run SafetyBackend.run_on_source() to get per-annotation
     analysis results
  3. Categorise:
     - VIOLATION + confidence ∈ {verified, static_analysis}
         → ERROR (abort)
     - VIOLATION + confidence ∈ {advisory, unsupported}
         → WARNING (continue, log to stderr)
     - pass / no_annotation
         → SILENT (no log)
  4. If --strict-safety: also escalate advisory + unsupported
     violations to ERROR
  5. If --skip-safety: short-circuit, log "safety check skipped"
  6. Return SafetyCheckResult; raise SafetyError if errors > 0

Backward-compatible: kernels with NO @verify(safety = ...)
annotations get a silent no-op. Existing Forge users see no
behaviour change until they opt in via real-form annotations.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from software.verification.safety import (
    SafetyBackend,
    SafetyAnalysisResult,
    SafetyClass,
)


# Confidence levels that cause compilation to ABORT on violation.
# `verified` and `static_analysis` are the "machine-checked" tiers
# where a violation means the kernel author's claim is wrong.
ERROR_CONFIDENCES = {"verified", "static_analysis"}

# Confidence levels that cause a WARNING (compilation continues).
# `advisory` and `unsupported` are documented known-gaps; the
# author has explicitly opted into "this is not formally checked"
# or "this is a known hazard."
WARNING_CONFIDENCES = {"advisory", "unsupported", "partial", "runtime_required"}


class SafetyError(Exception):
    """Raised when a safety violation must abort compilation."""

    def __init__(self, violations: list[SafetyAnalysisResult],
                 source_path: Optional[Path] = None) -> None:
        self.violations = violations
        self.source_path = source_path
        super().__init__(self._format())

    def _format(self) -> str:
        lines = ["Safety check FAILED"]
        if self.source_path:
            lines[0] = f"Safety check FAILED in {self.source_path}"
        for r in self.violations:
            lines.append(f"  {r.kernel_name}: {r.safety_class.value} "
                         f"measured {r.measured_max_freq_hz:.4f} Hz "
                         f"> declared {r.declared_max_freq_hz} Hz "
                         f"(confidence={r.declared_confidence})")
            for v in r.violations:
                lines.append(f"    • {v.detail}")
        lines.append("")
        lines.append("To override: add `confidence = \"unsupported\"` to the kernel's")
        lines.append("@verify(safety = ...) clause + document why in a HAZARD block.")
        lines.append("To bypass (emergency only): pass --skip-safety to eml-compile.")
        return "\n".join(lines)


@dataclass
class SafetyCheckResult:
    """Aggregate result of a check_module() / check_source() call."""
    source_path: Optional[Path] = None
    pass_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    skipped: bool = False
    results: list[SafetyAnalysisResult] = field(default_factory=list)
    warnings: list[SafetyAnalysisResult] = field(default_factory=list)
    errors: list[SafetyAnalysisResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def to_summary_line(self) -> str:
        if self.skipped:
            return "safety: SKIPPED (--skip-safety)"
        if self.error_count > 0:
            return (f"safety: FAILED ({self.error_count} error"
                    f"{'s' if self.error_count != 1 else ''})")
        if self.warning_count > 0:
            return (f"safety: pass with {self.warning_count} warning"
                    f"{'s' if self.warning_count != 1 else ''}")
        if self.pass_count > 0:
            return f"safety: pass ({self.pass_count} verified)"
        return "safety: no annotations"


def check_source(
    source: str,
    *,
    source_path: Optional[Path] = None,
    strict: bool = False,
    skip: bool = False,
    quiet: bool = False,
) -> SafetyCheckResult:
    """Run safety checks against raw .eml source text.

    Args:
        source: the .eml source as a string
        source_path: optional path for error messages
        strict: if True, advisory + unsupported violations also error
        skip: if True, skip the check entirely (for emergencies)
        quiet: if True, suppress stderr logging of warnings

    Returns:
        SafetyCheckResult with per-annotation results categorised
        into pass / warning / error buckets.

    Raises:
        SafetyError if any annotation hits an error-level violation.
    """
    result = SafetyCheckResult(source_path=source_path)

    if skip:
        result.skipped = True
        if not quiet:
            print("safety: SKIPPED (--skip-safety)", file=sys.stderr)
        return result

    backend = SafetyBackend()
    kernel_name = source_path.name if source_path else "<source>"
    analysis_results = backend.run_on_source(source, kernel_name=kernel_name)
    result.results = analysis_results

    for r in analysis_results:
        if r.status == "pass":
            result.pass_count += 1
            continue

        if r.status != "VIOLATION":
            # nonlinear / unparseable cases — treat as warning
            result.warning_count += 1
            result.warnings.append(r)
            if not quiet:
                print(f"safety WARNING: {r.kernel_name}: "
                      f"{r.safety_class.value} {r.status} "
                      f"(confidence={r.declared_confidence})",
                      file=sys.stderr)
            continue

        # VIOLATION: dispatch on confidence
        conf = r.declared_confidence
        is_error = (
            conf in ERROR_CONFIDENCES
            or (strict and conf in WARNING_CONFIDENCES)
        )
        if is_error:
            result.error_count += 1
            result.errors.append(r)
        else:
            result.warning_count += 1
            result.warnings.append(r)
            if not quiet:
                print(f"safety WARNING: {r.kernel_name}: "
                      f"{r.safety_class.value} VIOLATION "
                      f"({r.measured_max_freq_hz:.4f} Hz > "
                      f"{r.declared_max_freq_hz} Hz, "
                      f"confidence={conf})",
                      file=sys.stderr)

    if result.error_count > 0:
        raise SafetyError(result.errors, source_path=source_path)

    return result


def check_module(
    source_path: Path,
    *,
    strict: bool = False,
    skip: bool = False,
    quiet: bool = False,
) -> SafetyCheckResult:
    """Run safety checks against a parsed-and-profiled module by
    re-reading its source file.

    This is the entry point called from `tools/cli/main.py` between
    `profiler.profile_module()` and backend dispatch.

    Args:
        source_path: the .eml file path Forge is compiling
        strict: --strict-safety mode (advisory + unsupported also error)
        skip: --skip-safety mode (no-op)
        quiet: suppress warning logging

    Raises:
        SafetyError on any error-level violation.
    """
    if skip:
        return check_source("", source_path=source_path, skip=True, quiet=quiet)
    source = source_path.read_text(encoding="utf-8")
    return check_source(
        source,
        source_path=source_path,
        strict=strict,
        skip=False,
        quiet=quiet,
    )
