"""Tests for the Isabelle / HOL verification backend (Phase 3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.verification.isabelle.isabelle_backend import IsabelleBackend


REPO_ROOT = Path(__file__).resolve().parents[4]
AUTOPILOT = REPO_ROOT / "industries" / "aerospace" / "flight_control" / "autopilot.eml"


@pytest.fixture
def backend() -> IsabelleBackend:
    return IsabelleBackend()


def _compile_file(path: Path, backend: IsabelleBackend) -> str:
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return backend.compile_module(mod)


# ── Theory header ───────────────────────────────────────────


def test_no_verify_returns_empty_string(backend):
    src = "fn f(x: Real) -> Real { x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    assert backend.compile_module(mod) == ""


def test_theory_header_imports_complex_main(backend):
    out = _compile_file(AUTOPILOT, backend)
    assert "theory Autopilot" in out
    assert "imports Complex_Main" in out
    assert "begin" in out
    assert out.rstrip().endswith("end")


def test_theory_name_is_title_cased(backend):
    src = (
        "module my_pretty_module;\n"
        "@verify(lean, theorem = \"f_pos\")\n"
        "fn f(x: Real) -> Real ensures (result >= 0.0) { x }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = IsabelleBackend().compile_module(mod)
    assert "theory My_Pretty_Module" in out


# ── Constants + functions ───────────────────────────────────


def test_constant_definition_format(backend):
    out = _compile_file(AUTOPILOT, backend)
    assert 'definition Kp :: real where "Kp = 2.5"' in out
    assert 'definition ELEVATOR_MAX :: real where "ELEVATOR_MAX = 0.349"' in out


def test_function_signature_uses_arrow(backend):
    out = _compile_file(AUTOPILOT, backend)
    assert "definition autopilot_step :: \"real => real => real => real\"" in out


def test_function_body_let_chain(backend):
    out = _compile_file(AUTOPILOT, backend)
    assert "let pitch_error = " in out
    assert "rate_target =" in out
    assert "in min ELEVATOR_MAX (max ELEVATOR_MIN" in out


# ── Theorem with assumes/shows ──────────────────────────────


def test_theorem_uses_assumes_and_shows(backend):
    out = _compile_file(AUTOPILOT, backend)
    assert "theorem autopilot_command_within_limits:" in out
    assert "assumes" in out
    assert "shows" in out
    # Three input refinements become three `assumes h_<param>` lines
    # (Phase F refinement-aware Isabelle lowering names hypotheses
    # after the bound parameter rather than via a raw abs predicate).
    assert "h_pitch_setpoint" in out
    assert "h_pitch_measured" in out
    assert "h_pitch_integral" in out


def test_proof_body_is_sorry(backend):
    out = _compile_file(AUTOPILOT, backend)
    # Phase F refinement-aware Isabelle lowering tries `linarith`
    # first and falls back to `sorry` only when linear-arithmetic
    # cannot discharge the goal. The autopilot bound now closes
    # via linarith with the refinement hypotheses in scope; for
    # other kernels (e.g. those with transcendentals) the body
    # remains `sorry`. Both forms are valid.
    assert ("sorry" in out) or ("by linarith" in out) or ("by simp" in out)


# ── Builtin mapping ─────────────────────────────────────────


def test_clamp_lowers_to_min_max():
    src = (
        "@verify(lean, theorem = \"cl_bound\")\n"
        "fn cl(x: Real, lo: Real, hi: Real) -> Real "
        "ensures (abs(result) <= 1.0)\n"
        "{ clamp(x, lo, hi) }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = IsabelleBackend().compile_module(mod)
    assert "min hi (max lo x)" in out


def test_eml_lowers_to_exp_minus_ln():
    src = (
        "@verify(lean, theorem = \"e_pos\")\n"
        "fn e(x: Real, y: Real) -> Real "
        "ensures (result >= 0.0)\n"
        "{ eml(x, y) }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = IsabelleBackend().compile_module(mod)
    assert "(exp x - ln y)" in out


# ── Custom verify_filter ────────────────────────────────────


def test_default_filter_picks_lean_verify_block():
    src = (
        "@verify(lean, theorem = \"f_pos\")\n"
        "fn f(x: Real) -> Real ensures (result >= 0.0) { x }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = IsabelleBackend().compile_module(mod)
    assert "theorem f_pos" in out
