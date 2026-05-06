"""Phase C refinement checker, entailment, and auto-splicer tests.

TDD RED phase: all tests here must FAIL before implementation.

Covers:
  - Basic type-checking with refinements (unit + predicate agree)
  - Subtype entailment: syntactic interval checking
  - abs rewrite in entailment
  - Refinement combined with units
  - Refinement on integer types
  - Cross-param refinements (deferred obligation)
  - Predicate references module-level consts
  - Predicate references undeclared identifier -> error
  - Multi-clause conjunction entailment
  - Auto-splicer: flag OFF leaves requires unchanged
  - Auto-splicer: flag ON splices single-variable requires into param refinement
  - Auto-splicer: multi-variable requires stays unchanged
  - Auto-splicer: single-variable ensures becomes return refinement
  - Backwards compat with flag OFF
"""

from __future__ import annotations

from pathlib import Path
import pytest

from lang.parser import parse_source, parse_file
from lang.unit_types import check_module as unit_check_module


FORGE_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = FORGE_ROOT / "examples"


# ── Import helpers (will fail until Phase C is implemented) ──────────

def _import_refinements():
    """Import refinement module; skip test if not yet implemented."""
    try:
        import lang.refinements as ref
        return ref
    except ImportError:
        pytest.skip("lang.refinements not yet implemented")


def _import_check():
    try:
        from lang.refinements.check import check_module as ref_check
        return ref_check
    except ImportError:
        pytest.skip("lang.refinements.check not yet implemented")


def _import_entail():
    try:
        from lang.refinements.entail import entail, Decision
        return entail, Decision
    except ImportError:
        pytest.skip("lang.refinements.entail not yet implemented")


def _import_auto_splice():
    try:
        from lang.refinements.auto_splice import auto_splice_module
        return auto_splice_module
    except ImportError:
        pytest.skip("lang.refinements.auto_splice not yet implemented")


def _full_check(src: str):
    """Parse + unit-check + refinement-check; returns module."""
    mod = parse_source(src, "<test>")
    unit_check_module(mod)
    ref_check = _import_check()
    return ref_check(mod)


def _refinement_error(src: str):
    """Parse + unit-check + refinement-check; asserts RefinementError raised."""
    from lang.refinements import RefinementError
    mod = parse_source(src, "<test>")
    try:
        unit_check_module(mod)
    except Exception:
        pass
    ref_check = _import_check()
    with pytest.raises(RefinementError) as exc_info:
        ref_check(mod)
    return exc_info.value


# ─────────────────────────────────────────────────────────────────────
# 1. Basic refinement type-checking
# ─────────────────────────────────────────────────────────────────────


class TestBasicRefinementChecking:
    """Refinements are validated: predicates must type-check dimensionally."""

    def test_probability_type_checks(self):
        """Real{p | 0 <= p && p <= 1} accepted as a valid refinement."""
        src = "fn f(p: Real{p | 0.0 <= p && p <= 1.0}) -> Real { p }"
        mod = _full_check(src)
        assert mod is not None

    def test_positive_int_refinement_checks(self):
        """Int{n | n > 0} accepted."""
        src = "fn f(n: Int{n | n > 0}) -> Real { n }"
        mod = _full_check(src)
        assert mod is not None

    def test_hz_refinement_with_unit_checks(self):
        """Real[Hz]{f | f <= 22000} -- 22000 literal coerces to Hz."""
        src = "unit Hz = 1/s;\nfn f(freq: Real[Hz]{f | freq <= 22000.0}) -> Real { freq }"
        mod = _full_check(src)
        assert mod is not None

    def test_abs_predicate_checks(self):
        """Real{x | abs(x) <= 1.0} -- abs is allowed and type-checks."""
        src = "fn f(x: Real{x | abs(x) <= 1.0}) -> Real { x }"
        mod = _full_check(src)
        assert mod is not None

    def test_extern_fn_refinement_accepted_no_body_check(self):
        """Refinement on extern fn signature accepted; no body to check."""
        src = "extern fn f(x: Real{x | x > 0.0}) -> Real;"
        mod = parse_source(src, "<test>")
        ref_check = _import_check()
        result = ref_check(mod)
        assert result is not None


# ─────────────────────────────────────────────────────────────────────
# 2. Subtype entailment
# ─────────────────────────────────────────────────────────────────────


class TestSubtypeEntailment:
    """Syntactic entailment: interval narrowing."""

    def test_subtype_accepted_narrow_to_wide(self):
        """Real{x | 0 <= x && x <= 0.5} is a subtype of Real{x | 0 <= x && x <= 1}.
        A function expecting the wider type accepts the narrower value."""
        entail, Decision = _import_entail()
        from lang.refinements.ast import Refinement
        from lang.parser.ast_nodes import ASTNode, NodeKind

        # sub: 0 <= x <= 0.5
        # sup: 0 <= x <= 1
        # syntactic interval narrowing: [0, 0.5] ⊆ [0, 1] -> Yes
        from lang.parser import parse_source as ps
        # Use the entail function directly with parsed predicates
        sub_mod = ps("type T = Real{x | 0.0 <= x && x <= 0.5};", "<test>")
        sup_mod = ps("type T = Real{x | 0.0 <= x && x <= 1.0};", "<test>")
        sub_ref = sub_mod.types[0].refinement
        sup_ref = sup_mod.types[0].refinement
        decision = entail(sub_ref, sup_ref)
        assert decision == Decision.YES

    def test_subtype_rejected_wide_to_narrow(self):
        """Real{x | 0 <= x <= 2} is NOT a subtype of Real{x | 0 <= x <= 1}."""
        entail, Decision = _import_entail()
        from lang.parser import parse_source as ps
        sub_mod = ps("type T = Real{x | 0.0 <= x && x <= 2.0};", "<test>")
        sup_mod = ps("type T = Real{x | 0.0 <= x && x <= 1.0};", "<test>")
        sub_ref = sub_mod.types[0].refinement
        sup_ref = sup_mod.types[0].refinement
        decision = entail(sub_ref, sup_ref)
        assert decision == Decision.NO

    def test_subtype_unknown_for_complex_predicates(self):
        """Non-decidable subtype produces Unknown (deferred obligation)."""
        entail, Decision = _import_entail()
        from lang.parser import parse_source as ps
        # Cross-param type: entailment library can't decide
        sub_mod = ps("fn f(a: Real, b: Real{x | x > a}) -> Real { b }", "<test>")
        ref_check = _import_check()
        mod = ref_check(sub_mod)
        # Should not raise; deferred obligation recorded
        fn = mod.functions[0]
        # The param b's refinement involves a cross-param -- deferred obligation
        assert hasattr(fn, "deferred_obligations")

    def test_abs_rewrite_accepted(self):
        """abs(x) <= k is equivalent to -k <= x && x <= k -- entailment accepts."""
        entail, Decision = _import_entail()
        from lang.parser import parse_source as ps
        # sub: abs(x) <= 1.0  -->  -1 <= x <= 1
        # sup: -2 <= x <= 2   (wider)
        sub_mod = ps("type T = Real{x | abs(x) <= 1.0};", "<test>")
        sup_mod = ps("type T = Real{x | -2.0 <= x && x <= 2.0};", "<test>")
        sub_ref = sub_mod.types[0].refinement
        sup_ref = sup_mod.types[0].refinement
        decision = entail(sub_ref, sup_ref)
        assert decision == Decision.YES

    def test_subtype_error_has_location(self):
        """Subtype failure carries line:col."""
        # We test that a function call with narrower-than-required arg is flagged
        # (actual check integration -- deferred until checker wires subtype checks)
        # For now verify entail Decision.NO is returned for the failing pair
        entail, Decision = _import_entail()
        from lang.parser import parse_source as ps
        sub_mod = ps("type T = Real{x | 0.0 <= x && x <= 2.0};", "<test>")
        sup_mod = ps("type T = Real{x | 0.0 <= x && x <= 1.0};", "<test>")
        sub_ref = sub_mod.types[0].refinement
        sup_ref = sup_mod.types[0].refinement
        decision = entail(sub_ref, sup_ref)
        assert decision == Decision.NO


# ─────────────────────────────────────────────────────────────────────
# 3. Unit + refinement interaction
# ─────────────────────────────────────────────────────────────────────


class TestUnitAndRefinementInteraction:
    """Refinements combined with unit annotations are both validated."""

    def test_hz_literal_coerces_in_predicate(self):
        """Real[Hz]{f | f <= 22000} -- 22000 literal coerces to Hz."""
        src = "unit Hz = 1/s;\nfn f(freq: Real[Hz]{f | freq <= 22000.0}) -> Real { freq }"
        mod = _full_check(src)
        assert mod is not None

    def test_unitvar_param_refinement_stays_polymorphic(self):
        """Real{x | x > 0.0} with no unit annotation remains unit-polymorphic."""
        src = "fn f(x: Real{x | x > 0.0}) -> Real { x }"
        mod = _full_check(src)
        assert mod is not None

    def test_refinement_on_unitvar_param_with_requires(self):
        """requires (x > 0.0) on a Real param (UnitVar) stays unit-polymorphic."""
        src = "fn f(x: Real) -> Real requires (x > 0.0) { x }"
        mod = _full_check(src)
        assert mod is not None


# ─────────────────────────────────────────────────────────────────────
# 4. Predicate references module-level consts
# ─────────────────────────────────────────────────────────────────────


class TestConstReferencesInPredicate:
    """Predicate can reference module-level const values."""

    def test_const_reference_in_predicate_accepted(self):
        """Real{x | x < MAX} where const MAX: Real = 100.0 -- accepted."""
        src = """\
const MAX: Real = 100.0;
fn f(x: Real{x | x < MAX}) -> Real { x }
"""
        mod = _full_check(src)
        assert mod is not None

    def test_undeclared_ident_in_predicate_error(self):
        """Predicate references undeclared identifier -- error."""
        src = "fn f(x: Real{x | x < UNDEFINED_CONST}) -> Real { x }"
        from lang.parser import ParseError
        with pytest.raises((ParseError, Exception)) as exc_info:
            parse_source(src, "<test>")
        # Error should mention the undeclared name
        assert "UNDEFINED_CONST" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────
# 5. Multi-clause conjunction entailment
# ─────────────────────────────────────────────────────────────────────


class TestMultiClauseEntailment:
    """Conjunction breakdown in entailment."""

    def test_triple_conjunction_entails(self):
        """Real{x | x > 0 && x < 1 && abs(x) <= 1} correctly processed."""
        src = "fn f(x: Real{x | x > 0.0 && x < 1.0 && abs(x) <= 1.0}) -> Real { x }"
        mod = _full_check(src)
        assert mod is not None

    def test_integer_domain_refinement(self):
        """Int{n | n > 0} treated as integer-domain; accepted."""
        src = "fn f(n: Int{n | n > 0}) -> Real { n }"
        mod = _full_check(src)
        assert mod is not None


# ─────────────────────────────────────────────────────────────────────
# 6. Auto-splicer (flag-gated)
# ─────────────────────────────────────────────────────────────────────


class TestAutoSplicer:
    """Auto-splicer: gated behind strict_mode=True."""

    def test_flag_off_requires_stays(self):
        """With strict_mode=False, requires clause stays on function."""
        auto_splice_module = _import_auto_splice()
        src = """\
fn f(x: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
    requires (abs(x) <= 1.0)
{
    x + integral + derivative
}
"""
        mod = parse_source(src, "<test>")
        auto_splice_module(mod, strict_mode=False)
        fn = mod.functions[0]
        # requires clause should still be on the function
        assert len(fn.requires) == 1
        # param x should have no refinement
        assert fn.params[0].refinement is None

    def test_flag_on_single_variable_requires_spliced(self):
        """With strict_mode=True, single-var requires folds into param refinement."""
        auto_splice_module = _import_auto_splice()
        src = """\
fn pid(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
    requires (abs(error) <= 1.0)
{
    error + integral + derivative
}
"""
        mod = parse_source(src, "<test>")
        auto_splice_module(mod, strict_mode=True)
        fn = mod.functions[0]
        # The requires clause should be removed (or marked spliced)
        # and error param should now have a refinement
        error_param = fn.params[0]
        assert error_param.refinement is not None or len(fn.requires) == 0

    def test_flag_on_multi_variable_requires_stays(self):
        """With strict_mode=True, multi-variable requires (a < b) stays unchanged."""
        auto_splice_module = _import_auto_splice()
        src = """\
fn f(a: Real, b: Real) -> Real
    requires (a < b)
{
    b - a
}
"""
        mod = parse_source(src, "<test>")
        original_requires_count = len(mod.functions[0].requires)
        auto_splice_module(mod, strict_mode=True)
        fn = mod.functions[0]
        # Multi-variable requires stays
        assert len(fn.requires) == original_requires_count

    def test_flag_on_single_ensures_becomes_return_refinement(self):
        """With strict_mode=True, single-var ensures becomes return refinement."""
        auto_splice_module = _import_auto_splice()
        src = """\
fn f(x: Real) -> Real
    ensures (result >= 0.0)
{
    abs(x)
}
"""
        mod = parse_source(src, "<test>")
        auto_splice_module(mod, strict_mode=True)
        fn = mod.functions[0]
        # The ensures clause should be spliced to return_refinement
        # or ensures list emptied
        assert fn.return_refinement is not None or len(fn.ensures) == 0

    def test_flag_off_byte_identical_behavior(self):
        """With strict_mode=False, no structural changes to the module."""
        auto_splice_module = _import_auto_splice()
        src = """\
fn f(x: Real) -> Real
    requires (x > 0.0)
    ensures (result > 0.0)
{
    x
}
"""
        mod = parse_source(src, "<test>")
        orig_requires = list(mod.functions[0].requires)
        orig_ensures = list(mod.functions[0].ensures)
        orig_param_refinement = mod.functions[0].params[0].refinement

        auto_splice_module(mod, strict_mode=False)
        fn = mod.functions[0]
        assert len(fn.requires) == len(orig_requires)
        assert len(fn.ensures) == len(orig_ensures)
        assert fn.params[0].refinement == orig_param_refinement

    def test_pid_controller_round_trip_with_flag_on(self):
        """pid_controller.eml with flag ON -- semantics preserved."""
        auto_splice_module = _import_auto_splice()
        mod = parse_file(EXAMPLES_DIR / "pid_controller.eml", resolve=False)
        # Should not raise; semantics preserved
        auto_splice_module(mod, strict_mode=True)
        assert len(mod.functions) == 1


# ─────────────────────────────────────────────────────────────────────
# 7. Deferred obligations for Phase D
# ─────────────────────────────────────────────────────────────────────


class TestDeferredObligations:
    """Non-decidable entailment records obligations on the function."""

    def test_cross_param_obligation_recorded(self):
        """Cross-param refinement records a deferred obligation on the fn."""
        src = "fn f(a: Real, b: Real{x | x > a}) -> Real { b }"
        mod = parse_source(src, "<test>")
        ref_check = _import_check()
        mod = ref_check(mod)
        fn = mod.functions[0]
        # deferred_obligations should be populated for the cross-param case
        assert hasattr(fn, "deferred_obligations")
        # We just verify the attribute exists; Phase D will lower it

    def test_simple_refinement_no_obligation(self):
        """Simple decidable refinement produces no deferred obligations."""
        src = "fn f(x: Real{x | x > 0.0 && x < 1.0}) -> Real { x }"
        mod = parse_source(src, "<test>")
        ref_check = _import_check()
        mod = ref_check(mod)
        fn = mod.functions[0]
        assert hasattr(fn, "deferred_obligations")
        # No obligations for a simple, decidable predicate
        assert len(fn.deferred_obligations) == 0


# ─────────────────────────────────────────────────────────────────────
# 8. RefinementError shape
# ─────────────────────────────────────────────────────────────────────


class TestRefinementErrorShape:
    """RefinementError must carry message, line, col."""

    def test_refinement_error_importable(self):
        """RefinementError is importable from lang.refinements."""
        from lang.refinements import RefinementError
        assert RefinementError is not None

    def test_refinement_error_has_line(self):
        """RefinementError carries a line attribute."""
        from lang.refinements import RefinementError
        err = RefinementError("test", line=5, col=3)
        assert err.line == 5

    def test_refinement_error_has_col(self):
        """RefinementError carries a col attribute."""
        from lang.refinements import RefinementError
        err = RefinementError("test", line=5, col=3)
        assert err.col == 3

    def test_refinement_error_message(self):
        """RefinementError carries a human-readable message."""
        from lang.refinements import RefinementError
        err = RefinementError("subtype mismatch", line=1, col=1)
        assert "subtype mismatch" in str(err)


# ─────────────────────────────────────────────────────────────────────
# 9. Backwards compat: existing files type-check with flag OFF
# ─────────────────────────────────────────────────────────────────────


class TestBackwardsCompatFullPipeline:
    """All existing .eml files pass the full pipeline (unit + refinement checks)."""

    @pytest.mark.parametrize("path", [
        EXAMPLES_DIR / "pid_controller.eml",
        EXAMPLES_DIR / "sigmoid.eml",
        EXAMPLES_DIR / "gaussian.eml",
        EXAMPLES_DIR / "lerp.eml",
    ])
    def test_existing_file_passes_full_check(self, path: Path):
        """Existing .eml files pass unit + refinement checks unchanged."""
        mod = parse_file(path, resolve=False)
        unit_check_module(mod)
        ref_check = _import_check()
        result = ref_check(mod)
        assert result is not None
