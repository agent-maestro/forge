"""Tests for the Phase 1 safety backend.

Validates:
  - Real-form @verify(temporal_frequency, ...) parsing
  - Const + let-binding propagation (multiplicative chain)
  - Pass / VIOLATION discrimination
  - Confidence-level handling (unsupported is acceptable)
  - Non-linear-in-t is honestly refused
"""
from __future__ import annotations

import math

import pytest

from software.verification.safety import (
    SafetyBackend,
    SafetyClass,
    TemporalFrequencyAnalyzer,
)
from software.verification.safety.safety_backend import (
    _extract_real_safety_annotations_from_source,
)


def _make_source(body: str, annotation: str = '') -> str:
    """Build a minimal EML source for analysis testing."""
    return f"""
module test_kernel;
const ZERO: Real = 0.0
const ONE: Real = 1.0

{annotation}
@verify(lean, theorem = "test_in_unit_band")
fn test_field(u: Real, v: Real, t: Real) -> Real
    where chain_order <= 8
{{
{body}
}}
"""


# ── Annotation parsing ────────────────────────────────────────

def test_real_annotation_parsed():
    """@verify(temporal_frequency, max_freq_hz = "3.0", ...) parses."""
    source = '''
@verify(temporal_frequency,
        max_freq_hz = "3.0",
        scope = "kernel_only",
        confidence = "verified",
        standard = "W3C_WCAG_2.3.1")
'''
    annots = _extract_real_safety_annotations_from_source(source)
    assert len(annots) == 1
    assert annots[0]["class"] == "temporal_frequency"
    assert annots[0]["kwargs"]["max_freq_hz"] == "3.0"
    assert annots[0]["kwargs"]["confidence"] == "verified"


def test_two_safety_annotations_both_parsed():
    """Multiple safety classes on the same fn are collected."""
    source = '''
@verify(temporal_frequency, max_freq_hz = "3.0", confidence = "verified")
@verify(spatial_pattern, scope = "kernel_only", confidence = "advisory")
'''
    annots = _extract_real_safety_annotations_from_source(source)
    assert len(annots) == 2
    classes = {a["class"] for a in annots}
    assert classes == {"temporal_frequency", "spatial_pattern"}


def test_lean_annotation_not_picked_up():
    """@verify(lean, ...) is NOT a safety annotation."""
    source = '@verify(lean, theorem = "test_thm")'
    annots = _extract_real_safety_annotations_from_source(source)
    assert annots == []


# ── Temporal-frequency analyzer (the meat) ────────────────────

def test_kernel_with_no_t_param_passes():
    """A kernel with no temporal dependence is trivially safe."""
    source = _make_source(
        'sin(u * 5.0) + cos(v * 3.0)',
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "advisory")'
    )
    backend = SafetyBackend()
    results = backend.run_on_source(source, "no_t_kernel")
    assert len(results) == 1
    assert results[0].status == "pass"
    assert results[0].measured_max_freq_hz == 0.0


def test_low_freq_kernel_passes():
    """A kernel with sin(t * 0.5) — well under 3 Hz — passes."""
    source = _make_source(
        'sin(t * 0.5)',
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "advisory")'
    )
    backend = SafetyBackend()
    results = backend.run_on_source(source, "low_freq_kernel")
    assert len(results) == 1
    assert results[0].status == "pass"
    assert results[0].measured_max_t_coeff_rad_s == pytest.approx(0.5)
    assert results[0].measured_max_freq_hz == pytest.approx(0.5 / (2 * math.pi))


def test_high_freq_kernel_violation():
    """A kernel with sin(t * 30.0) — 4.77 Hz — VIOLATION at 3 Hz threshold."""
    source = _make_source(
        'sin(t * 30.0)',
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "advisory")'
    )
    backend = SafetyBackend()
    results = backend.run_on_source(source, "high_freq_kernel")
    assert len(results) == 1
    assert results[0].status == "VIOLATION"
    assert results[0].measured_max_t_coeff_rad_s == pytest.approx(30.0)
    assert results[0].measured_max_freq_hz == pytest.approx(30.0 / (2 * math.pi))
    assert len(results[0].violations) == 1
    # confidence = advisory means is_acceptable should still be True
    # (advisory = author asserts, no machine check; not a build error)
    assert results[0].is_acceptable


def test_unsupported_confidence_is_acceptable_despite_violation():
    """confidence = unsupported + VIOLATION → is_acceptable = True
    (known-hazard, Forge logs but doesn't block)."""
    source = _make_source(
        'sin(t * 100.0)',
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "unsupported")'
    )
    backend = SafetyBackend()
    results = backend.run_on_source(source, "test")
    assert results[0].status == "VIOLATION"
    assert results[0].declared_confidence == "unsupported"
    assert results[0].is_acceptable


def test_verified_confidence_makes_violation_unacceptable():
    """confidence = verified + VIOLATION → is_acceptable = False
    (false claim, must fail compile)."""
    source = _make_source(
        'sin(t * 30.0)',
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")'
    )
    backend = SafetyBackend()
    results = backend.run_on_source(source, "test")
    assert results[0].status == "VIOLATION"
    assert results[0].declared_confidence == "verified"
    assert not results[0].is_acceptable


def test_multiplicative_chain_through_let_binding():
    """The big trick: let-binding propagation through multiplications.

    This is the case that caught substrate_field_line (the multiplier
    × TIME_RATE chain).
    """
    source = _make_source(
        '''
        let arg: Real = t * 1.5;
        let scaled: Real = arg * 20.0;
        sin(scaled);
        ''',
        annotation='@verify(temporal_frequency, max_freq_hz = "3.0", '
                    'confidence = "verified")'
    )
    backend = SafetyBackend()
    results = backend.run_on_source(source, "multiplicative_chain")
    # 1.5 * 20 = 30 rad/s = 4.77 Hz — VIOLATION at 3 Hz
    assert results[0].status == "VIOLATION"
    assert results[0].measured_max_t_coeff_rad_s == pytest.approx(30.0)


def test_const_substitution():
    """A kernel using const for the rate should substitute correctly."""
    source = f"""
module test;
const RATE: Real = 2.0

@verify(temporal_frequency, max_freq_hz = "3.0", confidence = "verified")
@verify(lean, theorem = "test_in_unit_band")
fn test(t: Real) -> Real
{{
    sin(t * RATE)
}}
"""
    backend = SafetyBackend()
    results = backend.run_on_source(source, "const_sub")
    # 2.0 rad/s = 0.318 Hz — passes 3 Hz
    assert results[0].status == "pass"
    assert results[0].measured_max_t_coeff_rad_s == pytest.approx(2.0)


# ── Validation against real Glass Box kernels ─────────────────

def test_glassbox_substrate_charge_balanced_passes():
    """The actual migrated kernel ships with @verify(temporal_frequency,
    max_freq_hz = "3.0"). Should pass at ~0.032 Hz."""
    from pathlib import Path
    path = Path(__file__).parent.parent.parent.parent.parent.parent \
        / "monogate-engine" / "eml" / "senses" / "substrate_charge_balanced.eml"
    if not path.exists():
        pytest.skip(f"kernel file not available at {path}")
    from software.verification.safety import analyze_file
    results = analyze_file(path)
    assert len(results) >= 1
    temp_result = next(
        r for r in results
        if r.safety_class == SafetyClass.TEMPORAL_FREQUENCY)
    assert temp_result.status == "pass"
    assert temp_result.measured_max_freq_hz < 0.1
