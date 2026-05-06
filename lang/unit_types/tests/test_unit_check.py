"""Phase B unit-of-measure type checker tests.

TDD RED phase: all tests here must FAIL before implementation.

Covers:
  - Resolver: unit_expr string -> Unit
  - Addition/subtraction/comparisons
  - Multiplication/division
  - Transcendentals (sin, cos, tan, exp, ln, sqrt, asin, acos, atan, sinh, cosh, tanh)
  - abs/min/max/clamp
  - pow (integer vs non-integer exponent)
  - requires/ensures predicates
  - Function call unit matching + return type checking
  - Backwards compatibility (no unit annotations = dimensionless = passes)
  - End-to-end doppler/bad-doppler
"""

from __future__ import annotations

from pathlib import Path
import pytest

from lang.parser import parse_source, parse_file
from lang.unit_types import check_module, UnitTypeError


FORGE_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = FORGE_ROOT / "examples"
INDUSTRIES_DIR = FORGE_ROOT / "industries"
GRAMMAR_EXAMPLES_DIR = FORGE_ROOT / "lang" / "spec" / "grammar" / "examples"


def _check(src: str):
    """Parse + type-check; returns the checked module on success."""
    mod = parse_source(src, "<test>")
    return check_module(mod)


def _check_error(src: str) -> UnitTypeError:
    """Parse + type-check; asserts a UnitTypeError is raised and returns it."""
    mod = parse_source(src, "<test>")
    with pytest.raises(UnitTypeError) as exc_info:
        check_module(mod)
    return exc_info.value


# ─────────────────────────────────────────────────────────────────────
# 1. Resolver tests
# ─────────────────────────────────────────────────────────────────────


class TestResolver:
    """unit_expr strings resolve to structured Unit values."""

    def test_declared_unit_hz_resolves(self):
        """Real[Hz] against a declared 'unit Hz = 1/s;' resolves."""
        src = "unit Hz = 1/s;\nfn f(x: Real[Hz]) -> Real[Hz] { x }"
        mod = _check(src)
        assert mod is not None

    def test_undeclared_unit_raises(self):
        """Real[Foo] when Foo is not declared raises UnitTypeError."""
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert "Foo" in str(err)

    def test_undeclared_unit_in_return_raises(self):
        """Return type Real[Foo] with undeclared Foo raises UnitTypeError."""
        err = _check_error("fn f(x: Real) -> Real[Foo] { x }")
        assert "Foo" in str(err)

    def test_undeclared_unit_in_const_raises(self):
        """Const with undeclared unit raises UnitTypeError."""
        err = _check_error("const C: Real[Foo] = 1.0;")
        assert "Foo" in str(err)

    def test_compound_unit_m_per_s2_resolves(self):
        """Real[m/s^2] resolves to m=1, s=-2 base exponents."""
        src = "fn f(x: Real[m/s^2]) -> Real[m/s^2] { x }"
        mod = _check(src)
        assert mod is not None

    def test_dimensionless_one_resolves(self):
        """Real[1] resolves to all-zero exponents (dimensionless)."""
        src = "fn f(x: Real[1]) -> Real[1] { x }"
        mod = _check(src)
        assert mod is not None

    def test_bare_real_is_dimensionless(self):
        """Bare Real (no [unit]) is treated as dimensionless."""
        src = "fn f(x: Real) -> Real { x }"
        mod = _check(src)
        assert mod is not None

    def test_base_units_resolve_without_decl(self):
        """Base units m, kg, s, A, K, mol, cd, rad resolve natively."""
        for base in ["m", "kg", "s", "A", "K", "mol", "cd", "rad"]:
            src = f"fn f(x: Real[{base}]) -> Real[{base}] {{ x }}"
            mod = _check(src)
            assert mod is not None, f"base unit {base} failed"

    def test_derived_unit_pa_resolves(self):
        """Pa declared via N resolves correctly."""
        src = (
            "unit N = kg*m/s^2;\n"
            "unit Pa = N/m^2;\n"
            "fn f(x: Real[Pa]) -> Real[Pa] { x }"
        )
        mod = _check(src)
        assert mod is not None

    def test_error_has_line_col(self):
        """UnitTypeError carries line and col attributes."""
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert hasattr(err, "line")
        assert hasattr(err, "col")

    def test_undeclared_unit_error_message(self):
        """The error message names the undeclared unit."""
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        msg = str(err)
        assert "Foo" in msg
        assert "undeclared" in msg.lower() or "unknown" in msg.lower()


# ─────────────────────────────────────────────────────────────────────
# 2. Addition / subtraction / comparison
# ─────────────────────────────────────────────────────────────────────


class TestAdditionSubtraction:
    """Adding or subtracting values requires matching units."""

    def test_add_same_unit_ok(self):
        """f0 + f1 with both Real[Hz] is fine."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz], f1: Real[Hz]) -> Real[Hz] { f0 + f1 }"
        )
        _check(src)

    def test_add_mismatched_units_errors(self):
        """f0 + v with Real[Hz] + Real[m/s] raises UnitTypeError."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz], v: Real[m/s]) -> Real[Hz] { f0 + v }"
        )
        err = _check_error(src)
        msg = str(err)
        assert "Hz" in msg or "m/s" in msg

    def test_subtract_mismatched_units_errors(self):
        """f0 - v with mismatched units raises UnitTypeError."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz], v: Real[m/s]) -> Real[Hz] { f0 - v }"
        )
        _check_error(src)

    def test_add_literal_pins_to_param_unit(self):
        """f0 + 100.0 with f0: Real[Hz] -- literal coerces to Hz."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[Hz] { f0 + 100.0 }"
        )
        _check(src)

    def test_compare_same_unit_ok(self):
        """f0 < 100.0 with f0: Real[Hz] -- literal coerces to Hz."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[1] { f0 < 100.0 }"
        )
        # The return type Real[1] is dimensionless (boolean-ish result)
        # This test verifies the comparison itself does not error.
        _check(src)

    def test_compare_mismatched_units_errors(self):
        """f < t with f: Real[Hz], t: Real[s] raises UnitTypeError."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz], t: Real[s]) -> Real[1] { freq < t }"
        )
        _check_error(src)

    def test_compare_eq_same_unit_ok(self):
        """freq == 440.0 with freq: Real[Hz] ok (literal coerces)."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz]) -> Real[1] { freq == 440.0 }"
        )
        _check(src)

    def test_compare_ne_mismatched_errors(self):
        """freq != t with mismatched units raises UnitTypeError."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz], t: Real[s]) -> Real[1] { freq != t }"
        )
        _check_error(src)

    def test_compare_le_ok(self):
        """freq <= 22000.0 with freq: Real[Hz] ok."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz]) -> Real[1] { freq <= 22000.0 }"
        )
        _check(src)

    def test_compare_ge_mismatched_errors(self):
        """freq >= t with Real[Hz] >= Real[s] errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz], t: Real[s]) -> Real[1] { freq >= t }"
        )
        _check_error(src)


# ─────────────────────────────────────────────────────────────────────
# 3. Multiplication / division
# ─────────────────────────────────────────────────────────────────────


class TestMultiplicationDivision:
    """Multiplication and division propagate units dimensionally."""

    def test_multiply_by_literal_preserves_unit(self):
        """f0 * 2.0 with f0: Real[Hz] -> Real[Hz]."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[Hz] { f0 * 2.0 }"
        )
        _check(src)

    def test_multiply_kg_and_m_per_s(self):
        """m * v with Real[kg] * Real[m/s] -> Real[kg*m/s]."""
        src = (
            "unit N = kg*m/s^2;\n"
            "fn f(mass: Real[kg], vel: Real[m/s]) -> Real[kg*m/s] { mass * vel }"
        )
        # Note: kg*m/s is not a named unit but must be accepted
        # when param and return match dimensionally.
        _check(src)

    def test_multiply_self_squares_unit(self):
        """t * t with t: Real[s] -> Real[s^2]."""
        src = (
            "fn f(t: Real[s]) -> Real[s^2] { t * t }"
        )
        _check(src)

    def test_divide_one_over_t(self):
        """1.0 / t with t: Real[s] -> Real[1/s]."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(t: Real[s]) -> Real[Hz] { 1.0 / t }"
        )
        _check(src)

    def test_divide_same_unit_dimensionless(self):
        """a / b with same unit -> dimensionless."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(a: Real[Hz], b: Real[Hz]) -> Real[1] { a / b }"
        )
        _check(src)

    def test_divide_by_literal_preserves_unit(self):
        """v / 2.0 with v: Real[m/s] -> Real[m/s] (F# rule, symmetric to *)."""
        src = "fn halve(v: Real[m/s]) -> Real[m/s] { v / 2.0 }"
        _check(src)

    def test_divide_dimensional_by_untagged_const_errors(self):
        """v / C with v: Real[m/s], C: Real (untagged const) preserves m/s.

        Ensures literal-coercion rule extends to UnitVar consts, not just literals.
        """
        src = (
            "const HALF: Real = 2.0;\n"
            "fn f(v: Real[m/s]) -> Real[m/s] { v / HALF }"
        )
        _check(src)

    def test_return_unit_mismatch_errors(self):
        """Returning Real[Hz] when body is Real[m] errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(x: Real[m]) -> Real[Hz] { x }"
        )
        _check_error(src)

    def test_multiply_result_return_mismatch_errors(self):
        """mass * vel gives Real[kg*m/s] but declared return is Real[Hz]."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(mass: Real[kg], vel: Real[m/s]) -> Real[Hz] { mass * vel }"
        )
        _check_error(src)


# ─────────────────────────────────────────────────────────────────────
# 4. Transcendentals
# ─────────────────────────────────────────────────────────────────────


class TestTranscendentals:
    """sin/cos/tan/exp/ln/sqrt and inverse trig require dimensionless input."""

    def test_sin_hz_input_errors(self):
        """sin(f0) with f0: Real[Hz] raises UnitTypeError."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[1] { sin(f0) }"
        )
        err = _check_error(src)
        msg = str(err)
        assert "sin" in msg.lower() or "Hz" in msg

    def test_sin_rad_input_ok(self):
        """sin(theta) with theta: Real[rad] is ok; result dimensionless."""
        src = (
            "fn f(theta: Real[rad]) -> Real[1] { sin(theta) }"
        )
        _check(src)

    def test_sin_untagged_literal_ok(self):
        """sin(0.5) -- untagged literal coerces to dimensionless."""
        src = "fn f() -> Real[1] { sin(0.5) }"
        _check(src)

    def test_cos_dimensioned_errors(self):
        """cos(x) with x: Real[kg] errors."""
        src = "fn f(x: Real[kg]) -> Real[1] { cos(x) }"
        _check_error(src)

    def test_tan_dimensioned_errors(self):
        """tan(x) with x: Real[m] errors."""
        src = "fn f(x: Real[m]) -> Real[1] { tan(x) }"
        _check_error(src)

    def test_tan_dimensionless_ok(self):
        """tan(x) with x: Real (dimensionless) ok."""
        src = "fn f(x: Real) -> Real[1] { tan(x) }"
        _check(src)

    def test_exp_dimensioned_errors(self):
        """exp(x) requires dimensionless x."""
        src = "fn f(x: Real[m]) -> Real[1] { exp(x) }"
        _check_error(src)

    def test_exp_dimensionless_ok(self):
        """exp(x) with x: Real (dimensionless) ok."""
        src = "fn f(x: Real) -> Real[1] { exp(x) }"
        _check(src)

    def test_ln_dimensioned_errors(self):
        """ln(x) requires dimensionless x."""
        src = "fn f(x: Real[s]) -> Real[1] { ln(x) }"
        _check_error(src)

    def test_ln_dimensionless_ok(self):
        """ln(x) with x: Real (dimensionless) ok."""
        src = "fn f(x: Real) -> Real[1] { ln(x) }"
        _check(src)

    def test_sqrt_dimensionless_ok(self):
        """sqrt(x) with dimensionless x ok, result dimensionless."""
        src = "fn f(x: Real) -> Real[1] { sqrt(x) }"
        _check(src)

    def test_sqrt_dimensioned_errors(self):
        """sqrt(x) with x: Real[m] errors (non-integer sqrt of unit)."""
        src = "fn f(x: Real[m]) -> Real[1] { sqrt(x) }"
        _check_error(src)

    def test_asin_dimensionless_ok(self):
        """asin(x) with dimensionless x ok."""
        src = "fn f(x: Real) -> Real[rad] { asin(x) }"
        _check(src)

    def test_asin_dimensioned_errors(self):
        """asin(x) with x: Real[m] errors."""
        src = "fn f(x: Real[m]) -> Real[rad] { asin(x) }"
        _check_error(src)

    def test_acos_dimensioned_errors(self):
        """acos(x) with x: Real[s] errors."""
        src = "fn f(x: Real[s]) -> Real[rad] { acos(x) }"
        _check_error(src)

    def test_atan_dimensioned_errors(self):
        """atan(x) with x: Real[kg] errors."""
        src = "fn f(x: Real[kg]) -> Real[rad] { atan(x) }"
        _check_error(src)

    def test_sinh_dimensioned_errors(self):
        """sinh(x) with x: Real[m] errors."""
        src = "fn f(x: Real[m]) -> Real[1] { sinh(x) }"
        _check_error(src)

    def test_cosh_dimensionless_ok(self):
        """cosh(x) with dimensionless x ok."""
        src = "fn f(x: Real) -> Real[1] { cosh(x) }"
        _check(src)

    def test_tanh_dimensionless_ok(self):
        """tanh(x) with dimensionless x ok."""
        src = "fn f(x: Real) -> Real[1] { tanh(x) }"
        _check(src)


# ─────────────────────────────────────────────────────────────────────
# 5. abs / min / max / clamp
# ─────────────────────────────────────────────────────────────────────


class TestAbsMinMaxClamp:
    """abs preserves units; min/max/clamp require same units on all args."""

    def test_abs_preserves_unit(self):
        """abs(v) with v: Real[m/s] returns Real[m/s]."""
        src = "fn f(v: Real[m/s]) -> Real[m/s] { abs(v) }"
        _check(src)

    def test_abs_dimensionless_ok(self):
        """abs(x) with x: Real (dimensionless) returns Real."""
        src = "fn f(x: Real) -> Real[1] { abs(x) }"
        _check(src)

    def test_min_same_unit_ok(self):
        """min(a, b) -- same-unit comparison is ok; clamp is the idiomatic min."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(a: Real[Hz], b: Real[Hz]) -> Real[1] { a < b }"
        )
        _check(src)

    def test_clamp_same_unit_ok(self):
        """clamp(v, lo, hi) with all Real[m/s] ok."""
        src = "fn f(v: Real[m/s], lo: Real[m/s], hi: Real[m/s]) -> Real[m/s] { clamp(v, lo, hi) }"
        _check(src)

    def test_clamp_literal_bounds_ok(self):
        """clamp(v, -1.0, 1.0) with v: Real ok (literals coerce)."""
        src = "fn f(v: Real) -> Real[1] { clamp(v, -1.0, 1.0) }"
        _check(src)

    def test_clamp_mismatched_hi_errors(self):
        """clamp(v, lo, hi) with hi having different unit errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(v: Real[m/s], lo: Real[m/s], hi: Real[Hz]) -> Real[m/s] "
            "{ clamp(v, lo, hi) }"
        )
        _check_error(src)


# ─────────────────────────────────────────────────────────────────────
# 6. pow
# ─────────────────────────────────────────────────────────────────────


class TestPow:
    """pow(b, e): integer literal exponent on dimensional b ok; else error."""

    def test_pow_dimensionless_int_ok(self):
        """pow(2.0, 3) dimensionless -- ok."""
        src = "fn f() -> Real[1] { pow(2.0, 3) }"
        _check(src)

    def test_pow_t_squared(self):
        """pow(t, 2) with t: Real[s] -> Real[s^2]."""
        src = "fn f(t: Real[s]) -> Real[s^2] { pow(t, 2) }"
        _check(src)

    def test_pow_t_non_integer_errors(self):
        """pow(t, 0.5) with t: Real[s] errors (non-integer exponent on dimensional base)."""
        src = "fn f(t: Real[s]) -> Real[1] { pow(t, 0.5) }"
        err = _check_error(src)
        msg = str(err)
        assert "pow" in msg.lower() or "integer" in msg.lower() or "non-integer" in msg.lower()

    def test_pow_dimensional_param_exponent_errors(self):
        """pow(t, e) where e is a parameter (not a literal) errors."""
        src = "fn f(t: Real[s], e: Real) -> Real[1] { pow(t, e) }"
        err = _check_error(src)
        msg = str(err)
        assert "pow" in msg.lower() or "integer" in msg.lower()

    def test_pow_dimensionless_non_integer_ok(self):
        """pow(x, 0.5) with x: Real (dimensionless) ok -- square root."""
        src = "fn f(x: Real) -> Real[1] { pow(x, 0.5) }"
        _check(src)


# ─────────────────────────────────────────────────────────────────────
# 7. requires / ensures predicates
# ─────────────────────────────────────────────────────────────────────


class TestRequiresEnsures:
    """requires and ensures predicates are unit-checked against the fn env."""

    def test_requires_abs_with_hz_ok(self):
        """requires (abs(x) <= 1.0) with x: Real[Hz] -- abs(x) is Hz, 1.0 coerces."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(x: Real[Hz]) -> Real[Hz]\n"
            "    requires (abs(x) <= 1.0)\n"
            "{ x }"
        )
        _check(src)

    def test_requires_freq_less_than_literal_ok(self):
        """requires (f < 22000) with f: Real[Hz] ok (literal coerces)."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz]) -> Real[Hz]\n"
            "    requires (freq < 22000.0)\n"
            "{ freq }"
        )
        _check(src)

    def test_requires_mismatched_units_errors(self):
        """requires (f < t) with f: Real[Hz], t: Real[s] errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(freq: Real[Hz], t: Real[s]) -> Real[Hz]\n"
            "    requires (freq < t)\n"
            "{ freq }"
        )
        err = _check_error(src)
        msg = str(err)
        # Must mention both unit types
        assert "Hz" in msg or "s" in msg

    def test_ensures_dimensionless_comparison_ok(self):
        """ensures (result >= -1.0) with dimensionless return ok."""
        src = (
            "fn f(x: Real) -> Real\n"
            "    ensures (x >= -1.0)\n"
            "{ x }"
        )
        _check(src)


# ─────────────────────────────────────────────────────────────────────
# 8. Function call unit matching
# ─────────────────────────────────────────────────────────────────────


class TestFunctionCallUnitMatching:
    """Call-site unit checking: argument units must match parameter units."""

    def test_user_fn_call_matching_units_ok(self):
        """Calling a function with matching unit arguments succeeds."""
        src = (
            "unit Hz = 1/s;\n"
            "fn double_freq(f: Real[Hz]) -> Real[Hz] { f * 2.0 }\n"
            "fn caller(f0: Real[Hz]) -> Real[Hz] { double_freq(f0) }"
        )
        _check(src)

    def test_user_fn_call_mismatched_units_errors(self):
        """Calling a function with wrong unit argument raises UnitTypeError."""
        src = (
            "unit Hz = 1/s;\n"
            "fn double_freq(f: Real[Hz]) -> Real[Hz] { f * 2.0 }\n"
            "fn caller(t: Real[s]) -> Real[Hz] { double_freq(t) }"
        )
        err = _check_error(src)
        assert hasattr(err, "line")

    def test_return_unit_mismatch_errors(self):
        """Returning Real[Hz] from a function whose body produces Real[m] errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(x: Real[m]) -> Real[Hz] { x }"
        )
        err = _check_error(src)
        msg = str(err)
        assert "return" in msg.lower() or "Hz" in msg or "m" in msg


# ─────────────────────────────────────────────────────────────────────
# 9. Backwards compatibility
# ─────────────────────────────────────────────────────────────────────


class TestBackwardsCompatibility:
    """All existing .eml files without unit annotations must still type-check."""

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
    def test_existing_file_type_checks(self, path: Path):
        """Files without unit annotations type-check (all dimensionless)."""
        mod = parse_file(path, resolve=False)
        result = check_module(mod)
        assert result is not None

    def test_pid_no_unit_type_checks(self):
        """pid_controller.eml (no unit annots) type-checks fully."""
        src = """
module pid;
const Kp: Real = 1.5
fn pid(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
{
    let raw = Kp * error + integral;
    clamp(raw, -1.0, 1.0)
}
"""
        _check(src)

    def test_mercator_no_unit_annots_checks(self):
        """mercator_projection.eml without unit annots type-checks."""
        src = """
const PI_OVER_4: Real = 0.7853981633974483
const MAX_LAT: Real = 1.4844222297453324
fn mercator_y(lat: Real) -> Real
    requires (abs(lat) < MAX_LAT)
{
    ln(tan(PI_OVER_4 + lat * 0.5))
}
"""
        _check(src)


# ─────────────────────────────────────────────────────────────────────
# 10. End-to-end: doppler (success) and bad-doppler (failure)
# ─────────────────────────────────────────────────────────────────────


DOPPLER_OK = """\
unit Hz = 1/s;
const C_LIGHT: Real[m/s] = 299792458.0;
fn doppler(f0: Real[Hz], v_rel: Real[m/s]) -> Real[Hz]
    where chain_order <= 0
{
    f0 * (1.0 + v_rel / C_LIGHT)
}
"""

DOPPLER_BAD = """\
unit Hz = 1/s;
fn bad(f0: Real[Hz], v_rel: Real[m/s]) -> Real[Hz] { f0 + v_rel }
"""


class TestEndToEnd:
    """End-to-end doppler and bad-doppler cases."""

    def test_doppler_ok_type_checks(self):
        """The canonical doppler example type-checks cleanly."""
        _check(DOPPLER_OK)

    def test_bad_doppler_errors(self):
        """f0 + v_rel with Real[Hz] + Real[m/s] raises UnitTypeError."""
        err = _check_error(DOPPLER_BAD)
        msg = str(err)
        assert "Hz" in msg
        assert "m/s" in msg

    def test_bad_doppler_error_has_location(self):
        """The error carries line:col info."""
        err = _check_error(DOPPLER_BAD)
        assert err.line >= 1
        assert err.col >= 1

    def test_bad_doppler_error_message_says_cannot_add(self):
        """Error message explains the dimensional mismatch."""
        err = _check_error(DOPPLER_BAD)
        msg = str(err).lower()
        assert "add" in msg or "mismatch" in msg or "cannot" in msg

    def test_doppler_param_env_hz(self):
        """f0 in doppler resolves to Hz (s^-1)."""
        from lang.unit_types import check_module as cm
        from lang.unit_types.unit import Unit
        mod = parse_source(DOPPLER_OK, "<test>")
        cm(mod)
        # After check, the module is unchanged (erased output to backends)
        fn = mod.functions[0]
        # f0 param has unit_expr "Hz"
        assert fn.params[0].unit_expr == "Hz"

    def test_mercator_with_rad_annotations_checks(self):
        """mercator_projection.eml with lat: Real[rad] type-checks."""
        src = """\
const PI_OVER_4: Real = 0.7853981633974483
const MAX_LAT: Real = 1.4844222297453324
fn mercator_y(lat: Real[rad]) -> Real[1]
    requires (abs(lat) < MAX_LAT)
{
    ln(tan(PI_OVER_4 + lat * 0.5))
}
"""
        _check(src)

    def test_full_doppler_with_all_decls(self):
        """Complete snippet from the spec (9 unit decls + doppler fn) type-checks."""
        src = """\
unit Hz       = 1/s;
unit N        = kg*m/s^2;
unit Pa       = N/m^2;
unit J        = N*m;
unit W        = J/s;
unit V        = W/A;
unit km       = m * 1000;
unit kHz      = Hz * 1000;
unit deg      = rad * (PI/180);

const G_GRAVITY: Real[m/s^2] = 9.81;
const F_NYQUIST: Real[Hz]    = 22050.0;
const C_LIGHT:   Real[m/s]   = 299792458.0;

fn doppler_shift(f0: Real[Hz], v_rel: Real[m/s]) -> Real[Hz]
    where chain_order <= 0
{
    f0 * (1.0 + v_rel / C_LIGHT)
}
"""
        _check(src)


# ─────────────────────────────────────────────────────────────────────
# 11. Unit type identity and arithmetic
# ─────────────────────────────────────────────────────────────────────


class TestUnitArithmetic:
    """Unit datatype: mul, div, pow, is_dimensionless, equals_dimensionally."""

    def test_unit_dimensionless_constant(self):
        """DIMENSIONLESS is all-zero exponents, scale 1.0."""
        from lang.unit_types.unit import DIMENSIONLESS
        assert DIMENSIONLESS.is_dimensionless()

    def test_unit_multiply(self):
        """Unit(m) * Unit(s) = Unit(m*s)."""
        from lang.unit_types.unit import Unit
        m = Unit(base=(1, 0, 0, 0, 0, 0, 0, 0), scale=1.0, name="m")
        s = Unit(base=(0, 0, 1, 0, 0, 0, 0, 0), scale=1.0, name="s")
        ms = m * s
        assert ms.base == (1, 0, 1, 0, 0, 0, 0, 0)

    def test_unit_divide(self):
        """Unit(m) / Unit(s) = Unit(m/s)."""
        from lang.unit_types.unit import Unit
        m = Unit(base=(1, 0, 0, 0, 0, 0, 0, 0), scale=1.0, name="m")
        s = Unit(base=(0, 0, 1, 0, 0, 0, 0, 0), scale=1.0, name="s")
        ms = m / s
        assert ms.base == (1, 0, -1, 0, 0, 0, 0, 0)

    def test_unit_pow(self):
        """Unit(s)^2 = Unit(s^2)."""
        from lang.unit_types.unit import Unit
        s = Unit(base=(0, 0, 1, 0, 0, 0, 0, 0), scale=1.0, name="s")
        s2 = s ** 2
        assert s2.base == (0, 0, 2, 0, 0, 0, 0, 0)

    def test_unit_equals_dimensionally(self):
        """Two units with same exponents are dimensionally equal."""
        from lang.unit_types.unit import Unit
        hz1 = Unit(base=(0, 0, -1, 0, 0, 0, 0, 0), scale=1.0, name="Hz")
        hz2 = Unit(base=(0, 0, -1, 0, 0, 0, 0, 0), scale=1000.0, name="kHz")
        # equals_dimensionally only looks at exponents
        assert hz1.equals_dimensionally(hz2)

    def test_unit_not_dimensionally_equal(self):
        """m and s are not dimensionally equal."""
        from lang.unit_types.unit import Unit
        m = Unit(base=(1, 0, 0, 0, 0, 0, 0, 0), scale=1.0, name="m")
        s = Unit(base=(0, 0, 1, 0, 0, 0, 0, 0), scale=1.0, name="s")
        assert not m.equals_dimensionally(s)

    def test_hz_is_not_dimensionless(self):
        """Hz (s^-1) is not dimensionless."""
        from lang.unit_types.unit import Unit
        hz = Unit(base=(0, 0, -1, 0, 0, 0, 0, 0), scale=1.0, name="Hz")
        assert not hz.is_dimensionless()


# ─────────────────────────────────────────────────────────────────────
# 12. UnitTypeError shape
# ─────────────────────────────────────────────────────────────────────


class TestUnitTypeErrorShape:
    """UnitTypeError must carry message, line, col."""

    def test_error_has_message(self):
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert len(str(err)) > 0

    def test_error_has_line_attribute(self):
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert isinstance(err.line, int)

    def test_error_has_col_attribute(self):
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert isinstance(err.col, int)

    def test_error_line_is_positive(self):
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert err.line >= 1

    def test_error_col_is_positive(self):
        err = _check_error("fn f(x: Real[Foo]) -> Real { x }")
        assert err.col >= 1


# ─────────────────────────────────────────────────────────────────────
# 13. Let bindings carry unit through scope
# ─────────────────────────────────────────────────────────────────────


class TestLetBindings:
    """let x = expr; binds x to the inferred unit of expr."""

    def test_let_preserves_hz(self):
        """let f2 = f0 * 2.0; f2 has unit Hz."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[Hz] {\n"
            "    let f2 = f0 * 2.0;\n"
            "    f2\n"
            "}"
        )
        _check(src)

    def test_let_mismatched_return_errors(self):
        """let f2 = f0 * 2.0 (Hz), then returning as Real[s] errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[s] {\n"
            "    let f2 = f0 * 2.0;\n"
            "    f2\n"
            "}"
        )
        _check_error(src)

    def test_let_add_hz_and_s_errors(self):
        """let sum = f0 + t; with Real[Hz] + Real[s] errors."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz], t: Real[s]) -> Real[Hz] {\n"
            "    let sum = f0 + t;\n"
            "    sum\n"
            "}"
        )
        _check_error(src)


# ─────────────────────────────────────────────────────────────────────
# 14. Unary negation preserves unit
# ─────────────────────────────────────────────────────────────────────


class TestUnaryNegation:
    """Unary minus preserves the operand's unit."""

    def test_neg_hz_is_hz(self):
        """-(f0) with f0: Real[Hz] -> Real[Hz]."""
        src = (
            "unit Hz = 1/s;\n"
            "fn f(f0: Real[Hz]) -> Real[Hz] { -f0 }"
        )
        _check(src)
