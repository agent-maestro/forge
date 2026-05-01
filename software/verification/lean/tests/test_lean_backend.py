"""Tests for the Lean 4 backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.verification.lean.LeanBackend import LeanBackend


REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> LeanBackend:
    return LeanBackend()


# ── Behaviour around the @verify annotation ─────────────────────────


def test_no_verify_emits_empty_string(profiler, backend):
    """A function without @verify should yield empty Lean output."""
    src = "module t;\nfn f(x: Real) -> Real { x + 1.0 }"
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    assert backend.compile_module(mod) == ""


def test_non_lean_verify_skipped(profiler, backend):
    """@verify(z3, ...) should not produce Lean output."""
    src = '''module t;
@verify(z3, theorem = "foo")
fn f(x: Real) -> Real { x + 1.0 }'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    assert backend.compile_module(mod) == ""


def test_basic_verify_block_renders(profiler, backend):
    src = '''module t;
@verify(lean, theorem = "f_positive")
fn f(x: Real) -> Real
    requires (0.0 < x)
    ensures (0.0 < result)
{
    x + x
}'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    out = backend.compile_module(mod)
    assert "import MachLib.EML" in out
    assert "import MachLib.Trig" in out
    assert "open MachLib" in out
    assert "open MachLib.Real" in out
    # Function definition rendered
    assert "def f (x : Real) : Real :=" in out
    # Theorem statement
    assert "theorem f_positive" in out
    # Hypothesis from requires
    assert "h1 :" in out
    # `result` substituted with the function call
    assert "(f x)" in out
    # Proof body
    assert "sorry" in out


# ── Comprehensive demo ──────────────────────────────────────────────


def test_motor_control_safe_pid_renders(profiler, backend):
    """motor_control.eml has the canonical safe_pid @verify block."""
    mod = parse_file(EXAMPLES_DIR / "motor_control.eml")
    profiler.profile_module(mod)
    out = backend.compile_module(mod)
    # Theorem name from the @verify(theorem = "pid_bounded") arg
    assert "theorem pid_bounded" in out
    # Two `requires` clauses -> two hypotheses
    assert "h1 :" in out
    assert "h2 :" in out
    # `ensures abs(result) < 50000.0` survives substitution
    assert "(safe_pid error integral deriv)" in out
    assert "50000.0" in out


# ── AST emission spot checks ────────────────────────────────────────


def _render_expr(profiler, backend, body_expr_src: str) -> str:
    """Tiny helper: return the Lean-rendered theorem body for a
    minimal @verify block whose ensures clause is the supplied src."""
    src = f'''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    ensures ({body_expr_src})
{{
    x
}}'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    return backend.compile_module(mod)


def test_real_exp_dispatch(profiler, backend):
    out = _render_expr(profiler, backend, "exp(x) > 0.0")
    assert "(Real.exp x)" in out


def test_real_log_dispatch(profiler, backend):
    out = _render_expr(profiler, backend, "ln(x) < 100.0")
    assert "(Real.log x)" in out


def test_abs_dispatch(profiler, backend):
    out = _render_expr(profiler, backend, "abs(x) < 1.0")
    assert "(abs x)" in out


def test_unary_minus_dispatch(profiler, backend):
    out = _render_expr(profiler, backend, "-x < 0.0")
    assert "(-x)" in out


def test_machlib_imports_emitted(profiler, backend):
    """LeanBackend imports the MachLib foundations only — no Mathlib,
    no MonogateEML.Runtime. Phase 1 retarget."""
    src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    ensures (true)
{
    x
}'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    out = backend.compile_module(mod)
    assert "import MachLib.EML" in out
    assert "import MachLib.Trig" in out
    assert "Mathlib" not in out
    assert "MonogateEML" not in out


def test_stdlib_call_passes_through_unmangled(profiler, backend):
    """A CALL to `sigmoid(x)` renders as `(sigmoid x)` — the
    Runtime namespace rewrite (`mg_sigmoid`) is gone in the
    MachLib retarget; downstream MachLib stdlib provides the
    definition."""
    src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    ensures (sigmoid(x) > 0.0)
{
    x
}'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    out = backend.compile_module(mod)
    assert "(sigmoid x)" in out
    assert "mg_sigmoid" not in out


# ── Complex bodies become axiom declarations ───────────────────────
# Lean 4's `opaque` requires an executable default value; our `Real`
# is noncomputable so we declare these as `axiom` instead, which
# Lean accepts as a pure signature without a body.


def test_complex_body_emits_axiom(profiler, backend):
    """A function with `let mut` / `while` is declared as an axiom
    (Lean doesn't have first-class iteration in pure terms), so the
    theorem can still talk about it."""
    src = '''module t;
@verify(lean, theorem = "thm")
fn loop_fn(n: u8) -> Real
    requires (true)
    ensures (true)
{
    let mut x = 0.0;
    while n > 0 {
        x = x + 1.0;
    }
    x
}'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    out = backend.compile_module(mod)
    assert "axiom loop_fn" in out
    # The theorem still renders (against the axiom-declared def)
    assert "theorem thm" in out


def test_tuple_return_emits_axiom(profiler, backend):
    """Tuple-return functions become axiom declarations (Lean tuple
    types are declared inline; backend defers to Phase 2.5)."""
    src = '''module t;
@verify(lean, theorem = "thm")
fn pair(x: Real) -> (Real, Real)
    ensures (true)
{
    (x, x)
}'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    out = backend.compile_module(mod)
    assert "axiom pair" in out
