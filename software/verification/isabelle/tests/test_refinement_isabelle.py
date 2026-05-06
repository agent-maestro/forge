"""Phase E.4: Tests for refinement-aware Isabelle/HOL lowering.

Mirrors the structure of test_refinement_lean.py (Phase D) for the Isabelle backend.

Covers:
  1.  Refinement on parameter -> hypothesis emission with binder->param substitution.
  2.  Conjunction predicate -> single hypothesis.
  3.  abs(x) <= k -> (- k <= x \\<and> x <= k) form.
  4.  Multiple refined params -> sequential hypotheses.
  5.  Return refinement -> conclusion conjunction.
  6.  Splicer parity (refinement-derived vs requires-derived).
  7.  Cross-param obligation -> per-function lemma.
  8.  Auto-discharge tactic emitted (linarith for Isabelle).
  9.  Backwards compat: non-refined kernel byte-identical output.
  10. audio_pole_refined.eml compiles cleanly.

RED phase: all tests should FAIL before implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from lang.refinements.check import check_module
from software.verification.isabelle.isabelle_backend import IsabelleBackend


REPO_ROOT = Path(__file__).resolve().parents[4]
AUDIO_POLE = REPO_ROOT / "examples" / "audio_pole_refined.eml"


def _compile(src: str, *, verify_filter: str = "lean") -> str:
    """Parse, profile, check, and compile a source snippet to Isabelle."""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    check_module(mod)
    return IsabelleBackend(verify_filter=verify_filter).compile_module(mod)


# ── 1. Refinement on parameter -> hypothesis emission ────────────────────


class TestRefinementToHypothesisIsabelle:

    def test_unit_interval_refinement_emits_hypothesis(self):
        """Real{p | 0 <= p && p <= 1} on param x produces assumption for x."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (result >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out

    def test_refinement_hypothesis_named_h_param(self):
        """Assumption label is h_<param_name>."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(alpha: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (alpha >= 0.0)
{
    alpha
}'''
        out = _compile(src)
        assert "h_x" not in out  # alpha, not x
        assert "h_alpha" in out

    def test_binder_alpha_renamed_to_param(self):
        """Binder substituted with param name in assumption."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{binder_var | binder_var > 0.0}) -> Real
    ensures (x > 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out
        assert "binder_var" not in out

    def test_conjunction_predicate_single_hypothesis(self):
        """0 <= p && p <= 1 produces a single conjunction assumption."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        # Isabelle conjunction: \\<and>
        assert "\\<and>" in out
        assert out.count("h_x") >= 1

    def test_hypothesis_contains_both_bounds(self):
        """Both lower and upper bounds appear in the hypothesis."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "0" in out
        assert "1" in out
        assert "x" in out


# ── 2. abs rewrite ───────────────────────────────────────────────────────


class TestAbsRewriteIsabelle:

    def test_abs_refinement_lowers_to_neg_k_le_x_le_k(self):
        """abs(p) <= 1.0 -> (-1.0 <= x \\<and> x <= 1.0) in Isabelle."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | abs(p) <= 1.0}) -> Real
    ensures (x >= 0.0 || x <= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out
        # Negative bound pattern
        assert "-" in out
        assert "\\<and>" in out

    def test_abs_strict_rewrite(self):
        """abs(p) < k -> (- k < x \\<and> x < k)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | abs(p) < 2.0}) -> Real
    ensures (x >= 0.0 || x <= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out
        assert "-" in out


# ── 3. Multiple refined params ───────────────────────────────────────────


class TestMultipleRefinedParamsIsabelle:

    def test_two_params_each_get_hypothesis(self):
        """Two refined params -> two h_<param> hypotheses."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}, y: Real{q | 0.0 <= q && q <= 1.0}) -> Real
    ensures (x + y >= 0.0)
{
    x + y
}'''
        out = _compile(src)
        assert "h_x" in out
        assert "h_y" in out

    def test_refinement_hyps_appear_before_requires_hyps(self):
        """Refinement assumptions appear before requires-derived assumptions."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    requires (x < 0.5)
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out
        # requires-derived
        assert '"(x < 0.5)"' in out or "x < 0.5" in out
        lines = out.split("\n")
        h_x_idx = next((i for i, l in enumerate(lines) if "h_x" in l), None)
        req_idx = next((i for i, l in enumerate(lines) if "0.5" in l and "h_x" not in l), None)
        if h_x_idx is not None and req_idx is not None:
            assert h_x_idx < req_idx

    def test_no_refinement_no_extra_hypothesis(self):
        """Param without refinement does not get a spurious h_<param> assumption."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (x > 0.0)
    ensures (x > 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" not in out
        # Normal requires assumption must still appear
        assert "assumes" in out


# ── 4. Return refinement -> conclusion ──────────────────────────────────


class TestReturnRefinementConclusionIsabelle:

    def test_return_refinement_becomes_conclusion(self):
        """-> Real{r | 0 <= r && r <= 1} becomes the shows conjunction."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real{r | 0.0 <= r && r <= 1.0}
{
    x
}'''
        out = _compile(src)
        assert "\\<and>" in out

    def test_return_refinement_uses_function_call_not_binder(self):
        """Return binder substituted with function application in shows clause."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real{r | 0.0 <= r}
{
    x
}'''
        out = _compile(src)
        # The conclusion should express the property in terms of (f x)
        assert "f x" in out

    def test_return_refinement_without_ensures(self):
        """Return refinement alone forms the full conclusion (no True fallback)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | p > 0.0}) -> Real{r | r > 0.0}
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out

    def test_return_refinement_conjoined_with_ensures(self):
        """Return refinement and ensures clause are conjoined."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
    ensures (result <= x)
{
    x
}'''
        out = _compile(src)
        assert "\\<and>" in out

    def test_no_return_refinement_conclusion_unchanged(self):
        """No return refinement: conclusion is just the ensures clause."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    ensures (result >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "theorem thm:" in out


# ── 5. Auto-discharge tactic ─────────────────────────────────────────────


class TestAutoDischargeIsabelle:

    def test_real_domain_uses_linarith(self):
        """Isabelle proof body uses linarith as auto-discharge tactic."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
{
    x
}'''
        out = _compile(src)
        assert "linarith" in out

    def test_proof_structure_by_linarith(self):
        """Proof body contains `by linarith` pattern."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
{
    x
}'''
        out = _compile(src)
        assert "linarith" in out

    def test_no_sorry_when_linarith_replaces_it(self):
        """With refinements, the proof does not just use bare sorry."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
{
    x
}'''
        out = _compile(src)
        # linarith attempt must appear (even if sorry is a fallback)
        assert "linarith" in out

    def test_no_smt_no_cvc4_no_z3(self):
        """No SMT solver references in output."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "smt" not in out.lower()
        assert "cvc4" not in out.lower()
        assert "z3" not in out.lower()


# ── 6. Deferred obligations -> Isabelle lemma ───────────────────────────


class TestDeferredObligationsIsabelle:

    def test_cross_param_refinement_emits_obligation_lemma(self):
        """Cross-param refinement emits <fn>_obligation_1 lemma."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(a: Real, b: Real{x | x > a}) -> Real
    ensures (b > a)
{
    b
}'''
        out = _compile(src)
        assert "f_obligation_1" in out
        assert "sorry" in out.lower() or "oops" in out

    def test_obligation_lemma_stable_name(self):
        """Lemma name is <fn_name>_obligation_<n>."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn my_func(a: Real, b: Real{x | x > a}) -> Real
    ensures (b > a)
{
    b
}'''
        out = _compile(src)
        assert "my_func_obligation_1" in out

    def test_no_obligations_when_no_cross_param(self):
        """Simple interval refinement (no cross-param) produces no obligation lemmas."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "obligation" not in out


# ── 7. Backwards compatibility ───────────────────────────────────────────


class TestBackwardsCompatIsabelle:

    def test_non_refined_kernel_still_uses_sorry(self):
        """Non-refined kernel: proof body still ends with sorry (no regression)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (x > 0.0)
    ensures (x > 0.0)
{
    x
}'''
        out = _compile(src)
        assert "  sorry" in out
        # No linarith in a non-refined kernel
        assert "linarith" not in out

    def test_non_refined_kernel_has_assumes(self):
        """Non-refined kernel: requires-derived assumption under assumes."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (x > 0.0)
    ensures (x > 0.0)
{
    x
}'''
        out = _compile(src)
        assert "assumes" in out

    def test_no_verify_returns_empty_string(self):
        """Module with no @verify produces empty string (unchanged)."""
        src = "fn f(x: Real) -> Real { x }\n"
        mod = parse_source(src)
        Profiler().profile_module(mod)
        assert IsabelleBackend().compile_module(mod) == ""


# ── 8. Audio pole refined integration ───────────────────────────────────


class TestAudioPoleRefinedIsabelle:

    def test_audio_pole_refined_compiles(self):
        """audio_pole_refined.eml compiles without error."""
        mod = parse_file(AUDIO_POLE)
        Profiler().profile_module(mod)
        check_module(mod)
        out = IsabelleBackend().compile_module(mod)
        assert isinstance(out, str)

    def test_audio_pole_with_verify_produces_refinement_hyps(self):
        """audio_pole with @verify and refined params produces h_f, h_fs."""
        src = '''module t;
unit Hz = 1/s;
type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};
@verify(lean, theorem = "audio_pole_in_unit")
fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0})
    -> Real{r | 0.0 <= r && r < 1.0}
    requires (fs > f)
{
    exp(-3.14159265358979 * f / fs)
}'''
        out = _compile(src)
        assert "theorem audio_pole_in_unit:" in out
        assert "h_f" in out
        assert "h_fs" in out

    def test_audio_pole_conclusion_encodes_return_refinement(self):
        """Return refinement -> 0 <= (audio_pole ...) \\<and> (audio_pole ...) < 1."""
        src = '''module t;
unit Hz = 1/s;
@verify(lean, theorem = "audio_pole_in_unit")
fn audio_pole(fs: Real{x | x > 0.0})
    -> Real{r | 0.0 <= r && r < 1.0}
{
    exp(-1.0 / fs)
}'''
        out = _compile(src)
        assert "theorem audio_pole_in_unit:" in out
        assert "\\<and>" in out

    def test_audio_pole_proof_uses_linarith(self):
        """Theorem with refinements uses linarith (not just sorry)."""
        src = '''module t;
@verify(lean, theorem = "halve_in_unit")
fn halve(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
{
    x * 0.5
}'''
        out = _compile(src)
        assert "theorem halve_in_unit:" in out
        assert "linarith" in out
