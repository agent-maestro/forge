"""Phase C refinement-type parser tests.

TDD RED phase: all tests here must FAIL before implementation.

Covers:
  - Basic refinement syntax: Real{p | 0.0 <= p && p <= 1.0}
  - Refinement + unit: Real[Hz]{f | f <= 22000.0}
  - Refinements on integer types: Int{n | n > 0}, u8{n | n < 16}
  - Allowed predicate calls: abs, min, max
  - Rejected predicate calls: sin, exp, cos, tan, etc.
  - Rejected undeclared identifiers in predicate
  - Cross-param predicate (syntactically allowed)
  - Type alias with refinement
  - Backwards compat: bare Real still works
  - Negative: empty body, missing |, missing binder
  - pid and audio_pole from the spec parse correctly
  - Caret (^) improved error message
  - Existing .eml files parse unchanged
"""

from __future__ import annotations

from pathlib import Path
import pytest

from lang.parser import parse_source, parse_file, ParseError


FORGE_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = FORGE_ROOT / "examples"
INDUSTRIES_DIR = FORGE_ROOT / "industries"
GRAMMAR_EXAMPLES_DIR = FORGE_ROOT / "lang" / "spec" / "grammar" / "examples"


def _parse(src: str):
    """Parse source; returns EMLModule on success."""
    return parse_source(src, "<test>")


def _parse_error(src: str) -> ParseError:
    """Parse source; asserts ParseError is raised and returns it."""
    with pytest.raises(ParseError) as exc_info:
        parse_source(src, "<test>")
    return exc_info.value


# ─────────────────────────────────────────────────────────────────────
# 1. Basic refinement syntax
# ─────────────────────────────────────────────────────────────────────


class TestBasicRefinementSyntax:
    """Core refinement syntax parsing."""

    def test_real_simple_refinement_parses(self):
        """Real{p | 0.0 <= p && p <= 1.0} parses successfully."""
        src = "fn f(p: Real{p | 0.0 <= p && p <= 1.0}) -> Real { p }"
        mod = _parse(src)
        assert len(mod.functions) == 1
        param = mod.functions[0].params[0]
        assert param.refinement is not None

    def test_real_refinement_binder(self):
        """Binder name is captured correctly."""
        src = "fn f(p: Real{p | 0.0 <= p && p <= 1.0}) -> Real { p }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.refinement.binder == "p"

    def test_real_refinement_has_predicate(self):
        """Predicate AST is populated."""
        src = "fn f(p: Real{p | 0.0 <= p && p <= 1.0}) -> Real { p }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.refinement.predicate is not None

    def test_real_with_unit_and_refinement_parses(self):
        """Real[Hz]{f | f <= 22000.0} -- unit before refinement."""
        src = "unit Hz = 1/s;\nfn f(freq: Real[Hz]{f | f <= 22000.0}) -> Real { freq }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.unit_expr == "Hz"
        assert param.refinement is not None
        assert param.refinement.binder == "f"

    def test_real_hz_conjunction_refinement(self):
        """Real[Hz]{f | 20.0 <= f && f <= 22000.0} -- conjunction with unit."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz]{f | 20.0 <= f && f <= 22000.0}) -> Real { freq }"
        )
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.unit_expr == "Hz"
        assert param.refinement is not None

    def test_int_refinement_parses(self):
        """Int{n | n > 0} -- refinement on integer type."""
        src = "fn f(n: Int{n | n > 0}) -> Real { n }"
        # Int may be mapped as a type name; parser must accept it
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.type_name == "Int"
        assert param.refinement is not None
        assert param.refinement.binder == "n"

    def test_u8_refinement_parses(self):
        """u8{n | n < 16} -- refinement on u8."""
        src = "fn f(n: u8{n | n < 16}) -> Real { n }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.type_name == "u8"
        assert param.refinement is not None

    def test_i32_refinement_parses(self):
        """i32{n | n >= 0} -- refinement on i32."""
        src = "fn f(n: i32{n | n >= 0}) -> Real { n }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.type_name == "i32"
        assert param.refinement is not None

    def test_abs_in_predicate_allowed(self):
        """Real{x | abs(x) <= 1.0} -- abs is allowed in predicate."""
        src = "fn f(x: Real{x | abs(x) <= 1.0}) -> Real { x }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.refinement is not None

    def test_min_in_predicate_allowed(self):
        """Real{x | min(x, 1.0) >= 0.0} -- min allowed."""
        src = "fn f(x: Real{x | min(x, 1.0) >= 0.0}) -> Real { x }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.refinement is not None

    def test_max_in_predicate_allowed(self):
        """Real{x | max(x, 0.0) <= 1.0} -- max allowed."""
        src = "fn f(x: Real{x | max(x, 0.0) <= 1.0}) -> Real { x }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.refinement is not None


# ─────────────────────────────────────────────────────────────────────
# 2. Rejected predicate calls (transcendentals)
# ─────────────────────────────────────────────────────────────────────


class TestRejectedPredicateCalls:
    """sin, cos, tan, exp, ln, sqrt, floor, ceil, round are banned."""

    def test_sin_in_predicate_rejected(self):
        """Real{x | sin(x) > 0} -- sin rejected with clear message."""
        src = "fn f(x: Real{x | sin(x) > 0}) -> Real { x }"
        err = _parse_error(src)
        msg = str(err)
        assert "sin" in msg.lower()

    def test_exp_in_predicate_rejected(self):
        """Real{x | exp(x) >= 0} -- exp rejected."""
        src = "fn f(x: Real{x | exp(x) >= 0}) -> Real { x }"
        err = _parse_error(src)
        msg = str(err)
        assert "exp" in msg.lower()

    def test_cos_in_predicate_rejected(self):
        """cos rejected."""
        src = "fn f(x: Real{x | cos(x) < 1.0}) -> Real { x }"
        err = _parse_error(src)
        assert "cos" in str(err).lower()

    def test_tan_in_predicate_rejected(self):
        """tan rejected."""
        src = "fn f(x: Real{x | tan(x) > 0.0}) -> Real { x }"
        err = _parse_error(src)
        assert "tan" in str(err).lower()

    def test_ln_in_predicate_rejected(self):
        """ln rejected."""
        src = "fn f(x: Real{x | ln(x) >= 0.0}) -> Real { x }"
        err = _parse_error(src)
        assert "ln" in str(err).lower()

    def test_sqrt_in_predicate_rejected(self):
        """sqrt rejected."""
        src = "fn f(x: Real{x | sqrt(x) >= 0.0}) -> Real { x }"
        err = _parse_error(src)
        assert "sqrt" in str(err).lower()

    def test_error_message_names_rejected_function(self):
        """Error message explicitly names the rejected function."""
        src = "fn f(x: Real{x | sin(x) > 0}) -> Real { x }"
        err = _parse_error(src)
        msg = str(err)
        # Must name 'sin' in the error
        assert "sin" in msg


# ─────────────────────────────────────────────────────────────────────
# 3. Rejected undeclared identifiers
# ─────────────────────────────────────────────────────────────────────


class TestRejectedUndeclaredIdents:
    """Identifiers not in scope in a predicate are rejected at parse time."""

    def test_undeclared_ident_rejected(self):
        """Real{x | x > undef} -- undef is not in scope, rejected."""
        src = "fn f(x: Real{x | x > undef}) -> Real { x }"
        err = _parse_error(src)
        msg = str(err)
        assert "undef" in msg

    def test_undeclared_in_conjunction_rejected(self):
        """Real{x | x > 0 && unknown > 0} -- unknown rejected."""
        src = "fn f(x: Real{x | x > 0 && unknown > 0}) -> Real { x }"
        err = _parse_error(src)
        assert "unknown" in str(err)


# ─────────────────────────────────────────────────────────────────────
# 4. Cross-parameter predicates (syntactically allowed)
# ─────────────────────────────────────────────────────────────────────


class TestCrossParamPredicates:
    """Cross-param references are allowed syntactically."""

    def test_cross_param_allowed(self):
        """Real{x | x > a} where a is another param -- allowed syntactically."""
        src = "fn f(a: Real, b: Real{x | x > a}) -> Real { b }"
        mod = _parse(src)
        param_b = mod.functions[0].params[1]
        assert param_b.refinement is not None

    def test_cross_param_conjunction(self):
        """Real{x | x > 0 && x < b} where b is another param -- allowed."""
        src = "fn f(b: Real, x: Real{v | v > 0.0 && v < b}) -> Real { x }"
        mod = _parse(src)
        assert mod.functions[0].params[1].refinement is not None


# ─────────────────────────────────────────────────────────────────────
# 5. Type alias with refinement
# ─────────────────────────────────────────────────────────────────────


class TestTypeAliasWithRefinement:
    """type NAME = BASE{binder | predicate} aliases carry a refinement."""

    def test_type_alias_simple_refinement(self):
        """type Probability = Real{p | 0.0 <= p && p <= 1.0};"""
        src = "type Probability = Real{p | 0.0 <= p && p <= 1.0};"
        mod = _parse(src)
        assert len(mod.types) == 1
        alias = mod.types[0]
        assert alias.name == "Probability"
        assert alias.refinement is not None
        assert alias.refinement.binder == "p"

    def test_type_alias_with_unit_and_refinement(self):
        """type AudibleFreq = Real[Hz]{f | f <= 22000};"""
        src = "unit Hz = 1/s;\ntype AudibleFreq = Real[Hz]{f | f <= 22000};"
        mod = _parse(src)
        alias = mod.types[0]
        assert alias.name == "AudibleFreq"
        assert alias.unit_expr == "Hz"
        assert alias.refinement is not None

    def test_type_alias_refinement_binder(self):
        """Binder in type alias refinement is captured."""
        src = "type Prob = Real{q | q >= 0.0 && q <= 1.0};"
        mod = _parse(src)
        assert mod.types[0].refinement.binder == "q"


# ─────────────────────────────────────────────────────────────────────
# 6. Return-type refinement
# ─────────────────────────────────────────────────────────────────────


class TestReturnTypeRefinement:
    """Refinements may appear on the return type."""

    def test_return_type_with_refinement(self):
        """-> Real{r | 0.0 <= r && r < 1.0} on return type."""
        src = "fn f(x: Real) -> Real{r | 0.0 <= r && r < 1.0} { x }"
        mod = _parse(src)
        fn = mod.functions[0]
        assert fn.return_refinement is not None
        assert fn.return_refinement.binder == "r"

    def test_return_type_with_unit_and_refinement(self):
        """-> Real[Hz]{f | f > 0.0} on return type."""
        src = "unit Hz = 1/s;\nfn f(x: Real) -> Real[Hz]{f | f > 0.0} { x }"
        mod = _parse(src)
        fn = mod.functions[0]
        assert fn.return_unit_expr == "Hz"
        assert fn.return_refinement is not None


# ─────────────────────────────────────────────────────────────────────
# 7. Negative cases: malformed refinement bodies
# ─────────────────────────────────────────────────────────────────────


class TestMalformedRefinementBodies:
    """Malformed refinement bodies are rejected at parse time."""

    def test_empty_refinement_body_rejected(self):
        """Real{} -- empty body rejected."""
        src = "fn f(x: Real{}) -> Real { x }"
        _parse_error(src)

    def test_missing_pipe_rejected(self):
        """Real{x} -- missing | rejected."""
        src = "fn f(x: Real{x}) -> Real { x }"
        _parse_error(src)

    def test_missing_binder_rejected(self):
        """Real{| x > 0} -- missing binder rejected."""
        src = "fn f(x: Real{| x > 0}) -> Real { x }"
        _parse_error(src)


# ─────────────────────────────────────────────────────────────────────
# 8. Backwards compatibility: bare Real still works
# ─────────────────────────────────────────────────────────────────────


class TestBackwardsCompat:
    """Bare Real (no refinement) parses unchanged."""

    def test_bare_real_no_refinement(self):
        """fn f(x: Real) -> Real { x } -- no refinement, still works."""
        src = "fn f(x: Real) -> Real { x }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.refinement is None

    def test_real_with_unit_no_refinement(self):
        """Real[Hz] without refinement still works."""
        src = "unit Hz = 1/s;\nfn f(x: Real[Hz]) -> Real[Hz] { x }"
        mod = _parse(src)
        param = mod.functions[0].params[0]
        assert param.unit_expr == "Hz"
        assert param.refinement is None

    @pytest.mark.parametrize("path", [
        EXAMPLES_DIR / "pid_controller.eml",
        EXAMPLES_DIR / "sigmoid.eml",
        EXAMPLES_DIR / "gaussian.eml",
        EXAMPLES_DIR / "lerp.eml",
        EXAMPLES_DIR / "sine_oscillator.eml",
        GRAMMAR_EXAMPLES_DIR / "motor_control.eml",
        GRAMMAR_EXAMPLES_DIR / "kalman.eml",
        GRAMMAR_EXAMPLES_DIR / "arrhenius.eml",
        INDUSTRIES_DIR / "geospatial" / "mercator_projection.eml",
        INDUSTRIES_DIR / "semiconductor" / "op_amp_inverting.eml",
    ])
    def test_existing_eml_parses_unchanged(self, path: Path):
        """All existing .eml files parse without error."""
        mod = parse_file(path, resolve=False)
        assert mod is not None


# ─────────────────────────────────────────────────────────────────────
# 9. Full spec examples: pid and audio_pole
# ─────────────────────────────────────────────────────────────────────


class TestSpecExamples:
    """The spec's pid and audio_pole examples parse and have populated ASTs."""

    PID_SRC = """\
unit Hz = 1/s;

type Probability      = Real{p | 0.0 <= p && p <= 1.0};
type AudibleFreq      = Real[Hz]{f | 20.0 <= f && f <= 22000.0};
type PositiveCount    = Int{n | n > 0};

fn pid(error:      Real{e | -1.0 <= e && e <= 1.0},
       integral:   Real{i | abs(i) <= 1.0},
       derivative: Real{d | abs(d) <= 1.0})
   -> Real{r | -1.5 <= r && r <= 1.5}
   where chain_order <= 0
{
   1.0 * error + 0.2 * integral + 0.3 * derivative
}
"""

    AUDIO_POLE_SRC = """\
unit Hz = 1/s;

fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0})
   -> Real{r | 0.0 <= r && r < 1.0}
   requires (fs > f)
{
   exp(-3.14159265358979 * f / fs)
}
"""

    def test_pid_parses(self):
        """pid example from spec parses."""
        mod = _parse(self.PID_SRC)
        assert len(mod.functions) == 1
        assert mod.functions[0].name == "pid"

    def test_pid_params_have_refinements(self):
        """All three pid params have refinements."""
        mod = _parse(self.PID_SRC)
        fn = mod.functions[0]
        for param in fn.params:
            assert param.refinement is not None, f"{param.name} missing refinement"

    def test_pid_return_has_refinement(self):
        """pid return type has refinement."""
        mod = _parse(self.PID_SRC)
        fn = mod.functions[0]
        assert fn.return_refinement is not None

    def test_pid_type_aliases_have_refinements(self):
        """Probability, AudibleFreq, PositiveCount all have refinements."""
        mod = _parse(self.PID_SRC)
        for alias in mod.types:
            assert alias.refinement is not None, f"{alias.name} missing refinement"

    def test_audio_pole_parses(self):
        """audio_pole from spec parses (requires AudibleFreq as alias context)."""
        # standalone version where AudibleFreq must be parseable
        standalone = """\
unit Hz = 1/s;
type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};

fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0})
   -> Real{r | 0.0 <= r && r < 1.0}
   requires (fs > f)
{
   exp(-3.14159265358979 * f / fs)
}
"""
        mod = _parse(standalone)
        assert len(mod.functions) == 1
        assert mod.functions[0].name == "audio_pole"

    def test_audio_pole_fs_has_refinement(self):
        """fs parameter has unit Hz and refinement {x | x > 0.0}."""
        standalone = """\
unit Hz = 1/s;
type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};
fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0})
   -> Real{r | 0.0 <= r && r < 1.0}
   requires (fs > f)
{
   exp(-3.14159265358979 * f / fs)
}
"""
        mod = _parse(standalone)
        fn = mod.functions[0]
        # fs is second param
        fs = fn.params[1]
        assert fs.unit_expr == "Hz"
        assert fs.refinement is not None
        assert fs.refinement.binder == "x"


# ─────────────────────────────────────────────────────────────────────
# 10. Transcendental in requires clause -- rejected
# ─────────────────────────────────────────────────────────────────────


class TestRequiresTranscendentalRejected:
    """Transcendentals are rejected in refinement type bodies {binder | ...}.

    Note: standalone `requires`/`ensures` clauses continue to accept the full
    expression language (transcendentals included) for backwards compatibility
    with existing .eml files. Only the `{binder | predicate}` refinement
    syntax has the restricted predicate sub-language.
    """

    def test_sin_in_refinement_body_rejected(self):
        """Real{x | sin(x) > 0} in a type position is rejected at parse time."""
        src = "fn f(x: Real{x | sin(x) > 0}) -> Real { x }"
        err = _parse_error(src)
        msg = str(err)
        assert "sin" in msg.lower()

    def test_exp_in_refinement_body_rejected(self):
        """Real{x | exp(x) >= 0} in a type position is rejected."""
        src = "fn f(x: Real{x | exp(x) >= 0}) -> Real { x }"
        err = _parse_error(src)
        assert "exp" in str(err).lower()

    def test_standalone_requires_accepts_transcendentals(self):
        """Standalone requires (sin(x) > 0) is ALLOWED for backwards compat.

        The predicate sub-language restriction only applies inside the
        `{binder | predicate}` refinement type annotation body.
        Existing .eml files that use transcendentals in requires/ensures
        continue to parse unchanged.
        """
        src = """\
fn f(x: Real) -> Real
    requires (sin(x) > 0)
{ x }
"""
        mod = _parse(src)
        assert len(mod.functions) == 1
        assert len(mod.functions[0].requires) == 1


# ─────────────────────────────────────────────────────────────────────
# 11. Improved caret (^) error message
# ─────────────────────────────────────────────────────────────────────


class TestCaretImprovedError:
    """x^2 in expression position produces a structured error mentioning pow."""

    def test_caret_in_expression_gives_helpful_error(self):
        """fn f(x: Real) -> Real { x^2 } gives error mentioning pow(x, 2)."""
        src = "fn f(x: Real) -> Real { x^2 }"
        err = _parse_error(src)
        msg = str(err)
        assert "pow" in msg.lower()

    def test_caret_error_mentions_pow_form(self):
        """Error message suggests pow(x, 2) syntax."""
        src = "fn f(x: Real) -> Real { x^2 }"
        err = _parse_error(src)
        msg = str(err)
        # Should mention the correct replacement form
        assert "pow" in msg

    def test_caret_still_works_in_unit_expr(self):
        """s^2 in unit position is still valid (not affected)."""
        src = "fn f(t: Real[s^2]) -> Real[s^2] { t }"
        mod = _parse(src)
        assert mod.functions[0].params[0].unit_expr == "s^2"
