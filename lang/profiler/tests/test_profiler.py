"""Tests for `lang.profiler.profiler` -- end-to-end parse + profile."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


# ── All demo files profile cleanly ──────────────────────────────────


@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_demo_file_profiles(filename: str, profiler: Profiler) -> None:
    """Every demo file's functions get a populated profile (status
    in {'ok', 'tuple', 'complex_body', 'non_arithmetic'}) without
    raising."""
    mod = parse_file(EXAMPLES_DIR / filename)
    profiler.profile_module(mod)
    for fn in mod.functions:
        assert fn.profile is not None, f"{filename}::{fn.name}: profile is None"
        assert fn.profile.get("status") in {
            "ok", "tuple", "complex_body", "non_arithmetic",
        }, f"{filename}::{fn.name}: unexpected status {fn.profile.get('status')!r}"


# ── Specific structural expectations from the design doc ────────────


def _profile_one(profiler: Profiler, filename: str, fn_name: str) -> dict:
    mod = parse_file(EXAMPLES_DIR / filename)
    profiler.profile_module(mod)
    return next(f.profile for f in mod.functions if f.name == fn_name)


def test_pid_output_is_chain_order_0(profiler: Profiler):
    """The design doc explicitly states pid_output is chain_order=0
    (polynomial only). Lock that as a regression."""
    p = _profile_one(profiler, "motor_control.eml", "pid_output")
    assert p["status"] == "ok"
    assert p["chain_order"] == 0


def test_damped_response_is_chain_order_3(profiler: Profiler):
    """damped_response = amplitude * exp(-decay * t) * cos(omega * t)
    Design doc: chain_order = 3 (1 osc + 1 decay)."""
    p = _profile_one(profiler, "motor_control.eml", "damped_response")
    assert p["status"] == "ok"
    assert p["chain_order"] == 3
    assert p["dynamics"]["oscillations"] == 1
    assert p["dynamics"]["decays"] == 1
    assert p["dynamics"]["predicted_r"] == 3


def test_arrhenius_profile_includes_exp_unit(profiler: Profiler):
    p = _profile_one(profiler, "arrhenius.eml", "rate")
    assert p["status"] == "ok"
    assert p["chain_order"] == 1
    assert p["fpga_estimate"]["exp_units"] >= 1


def test_sigmoid_chain_order_1(profiler: Profiler):
    """1 / (1 + exp(-x)) reduces to chain order 1 after canonicalization
    -- the analyzer recognizes the sigmoid shape."""
    p = _profile_one(profiler, "sigmoid.eml", "sigmoid")
    assert p["status"] == "ok"
    assert p["chain_order"] == 1
    assert p["fp16_drift_risk"] in {"MEDIUM", "HIGH"}


def test_orbit_kepler_solve_is_complex_body(profiler: Profiler):
    """orbit.eml has `let mut` + `while` -- profiler must surface this
    as complex_body, not crash."""
    p = _profile_one(profiler, "orbit.eml", "kepler_solve")
    assert p["status"] == "complex_body"
    assert p["chain_order"] == -1


def test_motor_foc_park_is_tuple(profiler: Profiler):
    """park returns (f64, f64). Tuple branch should fire."""
    p = _profile_one(profiler, "motor_foc.eml", "park")
    assert p["status"] == "tuple"
    assert "tuple_components" in p
    assert len(p["tuple_components"]) == 2


def test_fm_voice_chain_order_4(profiler: Profiler):
    """sin nested in sin -> aggregate chain order 4 (2 oscillations).
    Tests the nesting + dynamics-counter interaction."""
    p = _profile_one(profiler, "bessel_fm.eml", "fm_voice")
    assert p["status"] == "ok"
    assert p["chain_order"] == 4
    assert p["dynamics"]["oscillations"] == 2


# ── FPGA estimate sanity checks ─────────────────────────────────────


def test_polynomial_function_needs_no_transcendental_units(profiler: Profiler):
    """A pure-polynomial function should require zero exp/ln/trig units."""
    p = _profile_one(profiler, "pid_basic.eml", "pid")
    assert p["status"] == "ok"
    fp = p["fpga_estimate"]
    assert fp["exp_units"] == 0
    assert fp["ln_units"] == 0
    assert fp["trig_units"] == 0
    assert fp["mac_units"] >= 1


def test_high_chain_order_demands_64_bit_precision(profiler: Profiler):
    """fp16_drift_risk = HIGH at chain >= 3 -> precision_bits_needed = 64."""
    p = _profile_one(profiler, "bessel_fm.eml", "fm_voice")
    assert p["fp16_drift_risk"] == "HIGH"
    assert p["fpga_estimate"]["precision_bits_needed"] == 64


# ── Stability warnings ──────────────────────────────────────────────


def test_log_expression_warns_on_domain(profiler: Profiler):
    """An expression with `log(x)` should warn about the domain
    restriction (only when the warning is on)."""
    from lang.parser import parse_source
    src = "module t;\nfn f(x: f64) -> f64 { ln(x) }"
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    p = mod.functions[0].profile
    assert p["status"] == "ok"
    assert any("log" in w or "ln" in w
               for w in p["stability_warnings"]), \
        f"expected ln/log warning in {p['stability_warnings']}"
