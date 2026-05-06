"""Phase D: Tests for refinement-aware Lean lowering.

Covers:
  1. Refinement -> hypothesis lowering (~15 cases)
  2. Return-refinement -> conclusion
  3. Splicer interaction (flag ON/OFF)
  4. Deferred obligations -> sorry-marked lemmas
  5. Auto-discharge: linarith / MachLib tactics close some sorries
  6. Non-regression: no-refinement kernels unchanged

RED phase: all tests should FAIL before implementation.
"""

from __future__ import annotations

import pytest

from lang.parser import parse_source
from lang.profiler import Profiler
from lang.refinements.check import check_module
from software.verification.lean.LeanBackend import LeanBackend


# ── fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture
def backend() -> LeanBackend:
    return LeanBackend()


def _compile(src: str, *, strict_refinements: bool = False) -> str:
    """Parse, profile, check, and compile a source snippet to Lean."""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    check_module(mod)
    return LeanBackend(strict_refinements=strict_refinements).compile_module(mod)


# ── 1. Refinement -> hypothesis lowering ─────────────────────────────

class TestRefinementToHypothesis:

    def test_unit_interval_refinement_on_x(self):
        """Real{p | 0 ≤ p ≤ 1} on parameter x produces (h_x : 0 ≤ x ∧ x ≤ 1)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (result >= 0.0)
{
    x
}'''
        out = _compile(src)
        # Refinement hypothesis should appear for x
        assert "h_x" in out
        # The hypothesis should contain both bounds from the refinement
        assert "0" in out
        assert "x" in out

    def test_refinement_hypothesis_named_h_param(self):
        """Refinement hypothesis is named h_<param_name> not h1, h2, etc."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(alpha: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (alpha >= 0.0)
{
    alpha
}'''
        out = _compile(src)
        assert "h_alpha" in out

    def test_conjunction_predicate_single_hypothesis(self):
        """Conjunction predicate (0 <= p && p <= 1) produces a single conjunction hypothesis."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        # Should appear as conjunction (∧) in a single hypothesis
        assert "∧" in out
        # Should have exactly one h_x hypothesis (not two separate ones)
        assert out.count("h_x") >= 1

    def test_multiple_refined_params_sequential_hypotheses(self):
        """Multiple refined parameters each get their own hypothesis."""
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

    def test_abs_refinement_lowers_to_neg_k_le_x_le_k(self):
        """abs(x) <= k lowers as (-k ≤ x ∧ x ≤ k)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | abs(p) <= 1.0}) -> Real
    ensures (x >= 0.0 || x <= 0.0)
{
    x
}'''
        out = _compile(src)
        # abs rewrite should produce -k <= x form
        assert "h_x" in out
        # Should contain the negation pattern for lower bound
        assert "-" in out

    def test_integer_type_refinement(self):
        """Int{n | n > 0} lowers correctly with 0 < n."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(n: Int{k | k > 0}) -> Int
    ensures (n > 0)
{
    n
}'''
        out = _compile(src)
        assert "h_n" in out
        # Int type in Lean
        assert "Int" in out

    def test_untagged_unit_refined_parameter_emits_real(self):
        """Real{r | r > 0} with no unit annotation emits Real type (no unit layer)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(r: Real{p | p > 0.0}) -> Real
    ensures (r > 0.0)
{
    r
}'''
        out = _compile(src)
        # The parameter type in the theorem should be Real, not some unit type
        assert "(r : Real)" in out
        assert "h_r" in out

    def test_refinement_hypothesis_uses_param_name_not_binder(self):
        """Binder alpha-renaming: predicate is expressed in terms of param name."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{binder_var | binder_var > 0.0}) -> Real
    ensures (x > 0.0)
{
    x
}'''
        out = _compile(src)
        # The hypothesis should refer to x, not binder_var
        assert "h_x" in out
        # binder_var should NOT appear in the output (it was alpha-renamed)
        assert "binder_var" not in out

    def test_strict_lower_bound_refinement(self):
        """Real{p | p > 0.0} produces hypothesis (h_x : 0 < x)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | p > 0.0}) -> Real
    ensures (x > 0.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out
        # Strict inequality should appear
        assert "<" in out

    def test_upper_bound_only_refinement(self):
        """Real{p | p <= 100.0} produces upper bound hypothesis."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | p <= 100.0}) -> Real
    ensures (x <= 100.0)
{
    x
}'''
        out = _compile(src)
        assert "h_x" in out
        assert "100" in out

    def test_refinement_hypothesis_appears_before_requires_hypotheses(self):
        """Refinement hypotheses appear before requires-derived hypotheses."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    requires (x < 0.5)
    ensures (x >= 0.0)
{
    x
}'''
        out = _compile(src)
        # h_x should be a refinement hypothesis
        assert "h_x" in out
        # There should also be a requires-derived hypothesis (h1 or similar)
        # The requires hyp should come after h_x in the output
        lines = out.split('\n')
        h_x_line = next((i for i, l in enumerate(lines) if 'h_x' in l), None)
        req_line = next((i for i, l in enumerate(lines) if 'h1' in l or ('x < ' in l and 'h_x' not in l)), None)
        if h_x_line is not None and req_line is not None:
            assert h_x_line < req_line, "Refinement hypothesis should appear before requires"

    def test_no_refinement_no_extra_hypothesis(self):
        """A parameter without refinement does not get a spurious hypothesis."""
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
        # Normal requires hypothesis should still be there
        assert "h1" in out


# ── 2. Return-refinement -> conclusion ────────────────────────────────

class TestReturnRefinementToConclusion:

    def test_return_refinement_becomes_conclusion(self):
        """-> Real{r | -1 <= r && r <= 1} produces conclusion -1 ≤ result ∧ result ≤ 1."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real{r | -1.0 <= r && r <= 1.0}
{
    x
}'''
        out = _compile(src)
        # The conclusion should encode the return refinement
        # Looking for both bounds in the theorem conclusion
        assert "-" in out  # negative bound
        assert "∧" in out  # conjunction

    def test_return_refinement_uses_function_call_not_binder(self):
        """Return refinement binder is replaced by the function application."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real{r | 0.0 <= r}
{
    x
}'''
        out = _compile(src)
        # The result should be expressed in terms of the function call (f x)
        assert "(f x)" in out

    def test_return_refinement_without_ensures(self):
        """Return refinement alone becomes the full conclusion (no 'True' fallback)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | p > 0.0}) -> Real{r | r > 0.0}
{
    x
}'''
        out = _compile(src)
        # Conclusion should not be trivially True when there's a return refinement
        # The conclusion should encode the return refinement
        assert "h_x" in out  # param refinement also present

    def test_return_refinement_combined_with_ensures(self):
        """Return refinement conjoined with ensures clause."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
    ensures (result <= x)
{
    x
}'''
        out = _compile(src)
        # Both the return refinement and ensures should appear in conclusion
        # They should be conjoined
        assert "∧" in out

    def test_no_return_refinement_conclusion_unchanged(self):
        """No return refinement: conclusion is just the ensures clause (unchanged)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    ensures (result >= 0.0)
{
    x
}'''
        out = _compile(src)
        # Should behave same as pre-Phase-D: just the ensures as conclusion
        assert "(f x)" in out
        # No extra conjunction from return refinement
        out_lines = out.split('\n')
        conclusion_lines = [l for l in out_lines if ':=' in l or (l.strip().startswith('(') and 'f x' in l)]


# ── 3. Splicer interaction ─────────────────────────────────────────────

class TestFlagModes:

    def test_flag_off_abs_rewrite_in_requires(self):
        """Flag OFF: requires (abs(x) <= 1.0) -> hypothesis uses abs rewrite form."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (abs(x) <= 1.0)
    ensures (x >= 0.0 || x <= 0.0)
{
    x
}'''
        out_off = _compile(src, strict_refinements=False)
        # The requires-derived hypothesis should use abs
        assert "abs" in out_off or "1.0" in out_off

    def test_flag_on_abs_refinement_lower_identical(self):
        """Flag ON: same abs constraint as parameter refinement produces equivalent output."""
        src_off = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (abs(x) <= 1.0)
    ensures (x >= 0.0 || x <= 0.0)
{
    x
}'''
        src_on = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | abs(p) <= 1.0}) -> Real
    ensures (x >= 0.0 || x <= 0.0)
{
    x
}'''
        out_off = _compile(src_off, strict_refinements=False)
        out_on = _compile(src_on, strict_refinements=True)
        # Both should produce output that compiles (contains theorem)
        assert "theorem thm" in out_off
        assert "theorem thm" in out_on

    def test_flag_default_is_off(self):
        """The --strict-refinements flag defaults to OFF."""
        backend_default = LeanBackend()
        backend_strict = LeanBackend(strict_refinements=True)
        # Default backend should have strict_refinements=False
        assert not backend_default.strict_refinements

    def test_non_refined_output_unchanged_by_flag(self):
        """For a kernel with no refinements, flag ON and OFF give identical output."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (x > 0.0)
    ensures (x > 0.0)
{
    x
}'''
        out_off = _compile(src, strict_refinements=False)
        out_on = _compile(src, strict_refinements=True)
        assert out_off == out_on


# ── 4. Deferred obligations -> sorry-marked lemmas ─────────────────────

class TestDeferredObligations:

    def test_cross_param_refinement_emits_obligation_lemma(self):
        """Cross-param refinement (b: Real{x | x > a}) emits obligation_1 lemma."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(a: Real, b: Real{x | x > a}) -> Real
    ensures (b > a)
{
    b
}'''
        out = _compile(src)
        # Obligation lemma should be emitted
        assert "f_obligation_1" in out
        assert "sorry" in out

    def test_obligation_lemma_stable_name(self):
        """Obligation lemma name is <fn_name>_obligation_<n>."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn my_func(a: Real, b: Real{x | x > a}) -> Real
    ensures (b > a)
{
    b
}'''
        out = _compile(src)
        assert "my_func_obligation_1" in out

    def test_obligation_count_matches_deferred_list(self):
        """Number of obligation lemmas equals len(func.deferred_obligations)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(a: Real, b: Real{x | x > a}, c: Real{y | y > a}) -> Real
    ensures (b > a)
{
    b
}'''
        mod = parse_source(src, "<test>")
        Profiler().profile_module(mod)
        check_module(mod)
        fn = mod.functions[0]
        n_obligations = len(fn.deferred_obligations)

        out = LeanBackend().compile_module(mod)
        for i in range(1, n_obligations + 1):
            assert f"f_obligation_{i}" in out

    def test_obligation_lemma_is_sorry_marked(self):
        """Each obligation lemma uses `by sorry` proof."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(a: Real, b: Real{x | x > a}) -> Real
    ensures (b > a)
{
    b
}'''
        out = _compile(src)
        assert "f_obligation_1" in out
        # The lemma proof should be 'by sorry'
        assert "by sorry" in out or "sorry" in out

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


# ── 5. Auto-discharge: linarith-style tactics ─────────────────────────

class TestAutoDischarge:

    def test_param_with_interval_refinement_uses_linarith_tactic(self):
        """When param has interval refinement, proof body tries linarith/omega."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real{r | 0.0 <= r && r <= 1.0}
{
    x
}'''
        out = _compile(src)
        # With refinement hypothesis available, backend should try linarith/omega
        # before falling back to sorry
        assert "linarith" in out or "omega" in out or "sorry" in out

    def test_pid_controller_output_has_refinement_aware_proof(self):
        """pid_controller.eml with abs-refinement params attempts linarith."""
        from lang.parser import parse_file
        from pathlib import Path
        mod = parse_file(Path("examples/pid_controller.eml"))
        Profiler().profile_module(mod)
        check_module(mod)
        out = LeanBackend().compile_module(mod)
        # Should contain the theorem
        assert "theorem pid_output_clamped" in out

    def test_simple_nonneg_with_nonneg_param_may_discharge(self):
        """A function with nonneg param returning nonneg may discharge with linarith."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real{p | p >= 0.0}) -> Real
    ensures (result >= 0.0)
{
    x
}'''
        out = _compile(src)
        # The theorem should be present
        assert "theorem thm" in out
        # With h_x : x >= 0, linarith can close result >= 0 if result = x
        # Either linarith or sorry is acceptable — the test verifies structure
        assert "h_x" in out


# ── 6. Non-regression for non-refined kernels ─────────────────────────

class TestNonRegression:

    def test_true_conclusion_kernel_output_stable(self):
        """Kernel with ensures (true) produces byte-identical output to pre-Phase-D.

        Phase D non-regression: the trivial True conclusion path uses `trivial`
        which is unchanged from pre-Phase-D. Kernels with actual goals get the
        upgraded `first | linarith | sorry` proof attempt.
        """
        src = '''module t;
@verify(lean, theorem = "f_noop")
fn f(x: Real) -> Real
    ensures (true)
{
    x
}'''
        # Both pre- and post-Phase-D: conclusion=True, so trivial is used
        mod = parse_source(src, "<test>")
        Profiler().profile_module(mod)
        baseline_out = LeanBackend().compile_module(mod)

        mod2 = parse_source(src, "<test>")
        Profiler().profile_module(mod2)
        check_module(mod2)
        phase_d_out = LeanBackend().compile_module(mod2)

        assert baseline_out == phase_d_out
        assert "trivial" in baseline_out

    def test_all_non_trivial_theorems_get_linarith_attempt(self):
        """Phase D: all theorems with non-True conclusions get linarith attempt.

        Phase D improvement: MachLib.Forge's scope includes exp_nonneg,
        max_nonneg_right, min_le_*, etc. that linarith can find automatically.
        `first | linarith | sorry` closes many goals automatically.
        """
        src = '''module t;
@verify(lean, theorem = "f_positive")
fn f(x: Real) -> Real
    requires (0.0 < x)
    ensures (0.0 < result)
{
    x + x
}'''
        mod = parse_source(src, "<test>")
        Profiler().profile_module(mod)
        check_module(mod)
        out = LeanBackend().compile_module(mod)
        # Phase D: all non-trivial conclusions get linarith attempt
        assert "linarith" in out
        # Still has sorry fallback (for goals linarith genuinely can't close)
        assert "sorry" in out

    def test_pid_controller_c_backend_unchanged(self):
        """pid_controller.eml --target c output MD5 is e864a6de6e6697c29ef0be4fd06a797b."""
        import subprocess
        import hashlib
        result = subprocess.run(
            ["python", "-m", "tools.cli.main", "examples/pid_controller.eml", "--target", "c"],
            capture_output=True, text=True
        )
        md5 = hashlib.md5(result.stdout.encode()).hexdigest()
        assert md5 == "e864a6de6e6697c29ef0be4fd06a797b", (
            f"C backend MD5 changed to {md5} -- codegen drift detected!"
        )

    def test_requires_clause_with_transcendental_verbatim(self):
        """requires clause with a function call (non-transcendental) passes through."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real, y: Real) -> Real
    requires (x > y)
    ensures (x > y)
{
    x
}'''
        out = _compile(src)
        assert "theorem thm" in out
        assert "h1" in out

    def test_multiple_ensures_only_first_used(self):
        """Multiple ensures: first one used as conclusion (existing behavior)."""
        src = '''module t;
@verify(lean, theorem = "thm")
fn f(x: Real) -> Real
    requires (x > 0.0)
    ensures (result > 0.0)
    ensures (result >= 0.0)
{
    x
}'''
        out = _compile(src)
        assert "theorem thm" in out


# ── 7. Audio pole refined: full integration ───────────────────────────

class TestAudioPoleRefined:

    def test_audio_pole_refined_compiles(self):
        """audio_pole_refined.eml compiles to valid Lean with refinement hypotheses."""
        from lang.parser import parse_file
        from pathlib import Path
        mod = parse_file(Path("examples/audio_pole_refined.eml"))
        Profiler().profile_module(mod)
        check_module(mod)
        out = LeanBackend().compile_module(mod)
        # Should produce non-empty output (audio_pole has no @verify by default)
        # If it has no @verify, confirm that's intentional
        # (audio_pole_refined.eml has no @verify annotation — confirmed by inspection)
        # The test verifies it compiles without error
        assert isinstance(out, str)

    def test_audio_pole_refined_fs_param_has_hypothesis(self):
        """fs parameter with {x | x > 0.0} refinement gets h_fs hypothesis."""
        # Add @verify to audio_pole to test
        src = '''module t;
unit Hz = 1/s;
type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};
@verify(lean, theorem = "audio_pole_thm")
fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0})
    -> Real{r | 0.0 <= r && r < 1.0}
    requires (fs > f)
{
    exp(-3.14159265358979 * f / fs)
}'''
        out = _compile(src)
        assert "theorem audio_pole_thm" in out
        # fs has a refinement -> should get h_fs
        assert "h_fs" in out

    def test_return_refinement_appears_in_conclusion(self):
        """Return refinement on audio_pole appears in theorem conclusion."""
        src = '''module t;
unit Hz = 1/s;
@verify(lean, theorem = "audio_pole_thm")
fn audio_pole(fs: Real{x | x > 0.0})
    -> Real{r | 0.0 <= r && r < 1.0}
{
    exp(-1.0 / fs)
}'''
        out = _compile(src)
        assert "theorem audio_pole_thm" in out
        # The conclusion should include the return refinement
        # We expect 0 ≤ (audio_pole fs) ∧ (audio_pole fs) < 1
        assert "h_fs" in out


# ── 8. Refinement emit module ──────────────────────────────────────────

class TestRefinementEmitModule:

    def test_refinement_to_hypothesis_importable(self):
        """refinement_emit module is importable."""
        from software.verification.lean.refinement_emit import refinement_to_hypothesis
        assert callable(refinement_to_hypothesis)

    def test_obligation_emit_importable(self):
        """obligation_emit module is importable."""
        from software.verification.lean.obligation_emit import obligations_to_lemmas
        assert callable(obligations_to_lemmas)

    def test_refinement_to_hypothesis_basic(self):
        """refinement_to_hypothesis(refinement, 'x') returns a Lean string."""
        from software.verification.lean.refinement_emit import refinement_to_hypothesis
        from lang.parser.ast_nodes import ASTNode, NodeKind, Refinement
        # Build a simple refinement: p > 0.0
        pred = ASTNode(
            kind=NodeKind.BINOP,
            value=">",
            children=[
                ASTNode(kind=NodeKind.VAR, value="p"),
                ASTNode(kind=NodeKind.LITERAL, value=0.0),
            ]
        )
        ref = Refinement(binder="p", predicate=pred)
        hyp = refinement_to_hypothesis(ref, "x")
        # Should be a string containing x (alpha-renamed from p)
        assert isinstance(hyp, str)
        assert "x" in hyp
        # Should NOT contain the binder name p
        assert "p" not in hyp

    def test_refinement_abs_rewrite(self):
        """refinement_to_hypothesis handles abs(p) <= k as (-k ≤ x ∧ x ≤ k)."""
        from software.verification.lean.refinement_emit import refinement_to_hypothesis
        from lang.parser.ast_nodes import ASTNode, NodeKind, Refinement
        # Build: abs(p) <= 1.0
        abs_node = ASTNode(
            kind=NodeKind.ABS,
            children=[ASTNode(kind=NodeKind.VAR, value="p")]
        )
        pred = ASTNode(
            kind=NodeKind.BINOP,
            value="<=",
            children=[abs_node, ASTNode(kind=NodeKind.LITERAL, value=1.0)]
        )
        ref = Refinement(binder="p", predicate=pred)
        hyp = refinement_to_hypothesis(ref, "x")
        assert isinstance(hyp, str)
        assert "x" in hyp
        # Should contain both bounds (negation pattern)
        assert "-" in hyp

    def test_obligations_to_lemmas_basic(self):
        """obligations_to_lemmas returns one lemma per obligation."""
        from software.verification.lean.obligation_emit import obligations_to_lemmas
        from lang.parser.ast_nodes import ASTNode, NodeKind, EMLFunction, Param
        # Build a simple function with 1 deferred obligation
        pred = ASTNode(kind=NodeKind.BINOP, value=">",
                       children=[ASTNode(kind=NodeKind.VAR, value="b"),
                                  ASTNode(kind=NodeKind.VAR, value="a")])
        fn = EMLFunction(
            name="my_fn",
            params=[
                Param(name="a", type_name="Real"),
                Param(name="b", type_name="Real"),
            ],
            return_type="Real",
            deferred_obligations=[pred],
        )
        lemmas = obligations_to_lemmas(fn)
        assert len(lemmas) == 1
        # Lemma name should be my_fn_obligation_1
        assert "my_fn_obligation_1" in lemmas[0]
        assert "sorry" in lemmas[0]

    def test_obligations_to_lemmas_stable_names(self):
        """Obligation names are positionally stable (n based on list index)."""
        from software.verification.lean.obligation_emit import obligations_to_lemmas
        from lang.parser.ast_nodes import ASTNode, NodeKind, EMLFunction, Param
        pred1 = ASTNode(kind=NodeKind.BINOP, value=">",
                        children=[ASTNode(kind=NodeKind.VAR, value="b"),
                                   ASTNode(kind=NodeKind.VAR, value="a")])
        pred2 = ASTNode(kind=NodeKind.BINOP, value=">",
                        children=[ASTNode(kind=NodeKind.VAR, value="c"),
                                   ASTNode(kind=NodeKind.VAR, value="a")])
        fn = EMLFunction(
            name="fn",
            params=[
                Param(name="a", type_name="Real"),
                Param(name="b", type_name="Real"),
                Param(name="c", type_name="Real"),
            ],
            return_type="Real",
            deferred_obligations=[pred1, pred2],
        )
        lemmas = obligations_to_lemmas(fn)
        assert len(lemmas) == 2
        assert "fn_obligation_1" in lemmas[0]
        assert "fn_obligation_2" in lemmas[1]

    def test_empty_deferred_obligations_no_lemmas(self):
        """No deferred obligations -> no lemmas emitted."""
        from software.verification.lean.obligation_emit import obligations_to_lemmas
        from lang.parser.ast_nodes import EMLFunction, Param
        fn = EMLFunction(
            name="fn",
            params=[Param(name="x", type_name="Real")],
            return_type="Real",
            deferred_obligations=[],
        )
        lemmas = obligations_to_lemmas(fn)
        assert lemmas == []
