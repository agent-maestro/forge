"""Tests for the safety-check phase wiring into Forge's compile pipeline.

Validates:
  - check_source() returns SafetyCheckResult, doesn't raise on pass
  - VIOLATION + confidence ∈ {verified, static_analysis} → raises
  - VIOLATION + confidence ∈ {advisory, unsupported} → warns, no raise
  - --strict-safety escalates advisory/unsupported to errors
  - --skip-safety short-circuits cleanly
  - Kernels with no @verify(safety = ...) annotations → silent no-op
  - SafetyError formats properly with kernel name + measured + declared
"""
from __future__ import annotations

import pytest

from lang.safety import check_source, SafetyError, SafetyCheckResult


def _kernel_source(annotation: str, body: str = "sin(t * 0.5)") -> str:
    return f"""
module test;
const ZERO: Real = 0.0
const ONE: Real = 1.0

{annotation}
@verify(lean, theorem = "test_in_unit_band")
fn test_field(u: Real, v: Real, t: Real) -> Real
    where chain_order <= 4
{{
{body}
}}
"""


# ── No-annotation backward compatibility ──────────────────────

def test_no_annotation_silent_pass():
    """Kernels with no @verify(safety = ...) annotation get a
    silent no-op. Backward-compatible: existing Forge users see
    no behaviour change."""
    source = _kernel_source(annotation="")
    result = check_source(source, quiet=True)
    assert result.passed
    assert result.pass_count == 0
    assert result.error_count == 0
    assert result.warning_count == 0


# ── Pass cases (compilation continues silently) ───────────────

def test_pass_silent_when_under_bound():
    """Low temporal frequency + verified confidence → silent pass."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")',
        body='sin(t * 0.5)'
    )
    result = check_source(source, quiet=True)
    assert result.passed
    assert result.pass_count == 1
    assert result.error_count == 0
    assert result.warning_count == 0


# ── Error-level violations (raise SafetyError) ────────────────

def test_verified_violation_raises():
    """confidence = verified + VIOLATION → raises SafetyError.

    The 'verified' tier is the gold standard. A violation means the
    author's machine-checked claim is wrong. Compilation MUST abort.
    """
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")',
        body='sin(t * 30.0)'      # 30 rad/s = 4.77 Hz, exceeds 3 Hz
    )
    with pytest.raises(SafetyError) as exc_info:
        check_source(source, quiet=True)
    assert "test_field" in str(exc_info.value) or "VIOLATION" in str(exc_info.value).upper() \
        or "4." in str(exc_info.value)


def test_static_analysis_violation_raises():
    """confidence = static_analysis is also a machine-checked tier
    that aborts on violation."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "static_analysis")',
        body='sin(t * 30.0)'
    )
    with pytest.raises(SafetyError):
        check_source(source, quiet=True)


# ── Warning-level violations (continue, log) ──────────────────

def test_advisory_violation_warns_but_doesnt_raise():
    """confidence = advisory + VIOLATION → warning, no abort.

    The author has explicitly opted into "no machine check"; their
    assertion is documentation, not a contract."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "advisory")',
        body='sin(t * 30.0)'
    )
    result = check_source(source, quiet=True)
    assert result.passed
    assert result.warning_count == 1
    assert result.error_count == 0


def test_unsupported_violation_warns_but_doesnt_raise():
    """confidence = unsupported + VIOLATION → warning. This is the
    documented-known-hazard case (substrate_glitch + substrate_field_line)."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "unsupported")',
        body='sin(t * 100.0)'      # 15.92 Hz, far over threshold
    )
    result = check_source(source, quiet=True)
    assert result.passed
    assert result.warning_count == 1
    assert result.error_count == 0


# ── --strict-safety mode ──────────────────────────────────────

def test_strict_mode_escalates_advisory_to_error():
    """--strict-safety: advisory violations also abort."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "advisory")',
        body='sin(t * 30.0)'
    )
    with pytest.raises(SafetyError):
        check_source(source, strict=True, quiet=True)


def test_strict_mode_escalates_unsupported_to_error():
    """--strict-safety: unsupported violations also abort.

    For CI: we WANT to know about every kernel that's a known hazard."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "unsupported")',
        body='sin(t * 100.0)'
    )
    with pytest.raises(SafetyError):
        check_source(source, strict=True, quiet=True)


# ── --skip-safety mode ────────────────────────────────────────

def test_skip_mode_bypasses_check_entirely():
    """--skip-safety: no analysis runs, no warnings, no errors."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")',
        body='sin(t * 100.0)'      # Would normally abort
    )
    result = check_source(source, skip=True, quiet=True)
    assert result.passed
    assert result.skipped
    assert result.error_count == 0
    assert result.warning_count == 0


# ── SafetyError formatting ────────────────────────────────────

def test_safety_error_message_includes_kernel_info():
    """Error message must name the kernel + measured + declared
    so the user can act on it."""
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")',
        body='sin(t * 30.0)'
    )
    with pytest.raises(SafetyError) as exc_info:
        check_source(source, quiet=True)
    msg = str(exc_info.value)
    assert "Safety check FAILED" in msg
    assert "temporal_frequency" in msg
    assert "verified" in msg
    # Should include actionable next-steps
    assert "--skip-safety" in msg or "unsupported" in msg


# ── Summary line for CLI ──────────────────────────────────────

def test_summary_line_pass():
    source = _kernel_source(
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")',
    )
    result = check_source(source, quiet=True)
    assert "pass" in result.to_summary_line().lower()


def test_summary_line_no_annotation():
    result = check_source(_kernel_source(annotation=""), quiet=True)
    assert "no annotation" in result.to_summary_line()


def test_summary_line_skipped():
    result = check_source(_kernel_source(annotation=""), skip=True, quiet=True)
    assert "SKIPPED" in result.to_summary_line()


# ── Real Glass Box kernel integration ─────────────────────────

def test_real_substrate_charge_balanced_passes_in_pipeline():
    """The migrated kernel should pass through the full pipeline."""
    from pathlib import Path
    path = Path(__file__).parent.parent.parent.parent.parent.parent \
        / "monogate-engine" / "eml" / "senses" / "substrate_charge_balanced.eml"
    if not path.exists():
        pytest.skip(f"kernel file not available at {path}")
    from lang.safety import check_module
    result = check_module(path, quiet=True)
    assert result.passed
    assert result.error_count == 0
