"""Phase A unit-of-measure parser tests.

TDD RED phase: these tests must all fail before implementation.
They describe the full Phase A contract:
  - unit declarations (derived + base-unit arithmetic)
  - Real[unit_expr] in param, const, and return-type positions
  - Bare Real (legacy form) still works untouched
  - Negative / rejection cases
  - Backwards-compatibility round-trips on existing .eml files
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import ParseError, parse_source, parse_file
from lang.parser.ast_nodes import (
    EMLUnitDecl,
    EMLConstant,
    EMLFunction,
    Param,
)


# ── Helpers ──────────────────────────────────────────────────────────

# parents[3] = forge/ (the project root of monogate-forge)
FORGE_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = FORGE_ROOT / "examples"
INDUSTRIES_DIR = FORGE_ROOT / "industries"
GRAMMAR_EXAMPLES_DIR = FORGE_ROOT / "lang" / "spec" / "grammar" / "examples"


def _parse(src: str):
    return parse_source(src, "<test>")


# ── 1. Unit declarations ─────────────────────────────────────────────


class TestUnitDeclarations:
    """unit NAME = <unit_expr> ; produces EMLUnitDecl in the module."""

    def test_unit_decl_appears_in_module(self):
        mod = _parse("unit Hz = 1/s;")
        assert len(mod.unit_decls) == 1

    def test_unit_decl_name(self):
        mod = _parse("unit Hz = 1/s;")
        assert mod.unit_decls[0].name == "Hz"

    def test_unit_decl_line_col(self):
        mod = _parse("unit Hz = 1/s;")
        decl = mod.unit_decls[0]
        assert decl.line == 1
        assert decl.col == 1

    def test_unit_derived_from_base_quotient(self):
        """Hz = 1/s  -- inverse-seconds."""
        mod = _parse("unit Hz = 1/s;")
        decl = mod.unit_decls[0]
        # base_exponents: (m, kg, s, A, K, mol, cd, rad)
        # Hz = s^-1  => index 2 = -1, rest 0
        assert decl.base_exponents[2] == -1
        assert decl.scale == pytest.approx(1.0)

    def test_unit_derived_product_of_bases(self):
        """N = kg*m/s^2."""
        mod = _parse("unit N = kg*m/s^2;")
        decl = mod.unit_decls[0]
        # (m=1, kg=1, s=-2, A=0, K=0, mol=0, cd=0, rad=0)
        assert decl.base_exponents[0] == 1   # m
        assert decl.base_exponents[1] == 1   # kg
        assert decl.base_exponents[2] == -2  # s
        assert decl.scale == pytest.approx(1.0)

    def test_unit_pa_from_n_per_m2(self):
        """Pa = N/m^2 -- requires previously declared N."""
        src = "unit N = kg*m/s^2;\nunit Pa = N/m^2;"
        mod = _parse(src)
        pa = next(d for d in mod.unit_decls if d.name == "Pa")
        # Pa = kg/(m*s^2)
        assert pa.base_exponents[0] == -1  # m
        assert pa.base_exponents[1] == 1   # kg
        assert pa.base_exponents[2] == -2  # s

    def test_unit_j_from_n_times_m(self):
        """J = N*m -- joules."""
        src = "unit N = kg*m/s^2;\nunit J = N*m;"
        mod = _parse(src)
        j = next(d for d in mod.unit_decls if d.name == "J")
        # J = kg*m^2/s^2
        assert j.base_exponents[0] == 2   # m^2
        assert j.base_exponents[1] == 1   # kg
        assert j.base_exponents[2] == -2  # s

    def test_unit_w_from_j_per_s(self):
        """W = J/s -- watts."""
        src = "unit N = kg*m/s^2;\nunit J = N*m;\nunit W = J/s;"
        mod = _parse(src)
        w = next(d for d in mod.unit_decls if d.name == "W")
        # W = kg*m^2/s^3
        assert w.base_exponents[0] == 2   # m^2
        assert w.base_exponents[1] == 1   # kg
        assert w.base_exponents[2] == -3  # s

    def test_unit_v_from_w_per_a(self):
        """V = W/A -- volts."""
        src = (
            "unit N = kg*m/s^2;\n"
            "unit J = N*m;\n"
            "unit W = J/s;\n"
            "unit V = W/A;\n"
        )
        mod = _parse(src)
        v = next(d for d in mod.unit_decls if d.name == "V")
        # V = kg*m^2/(s^3*A)
        assert v.base_exponents[3] == -1  # A^-1

    def test_unit_km_with_numeric_scale(self):
        """km = m * 1000 -- scaling by integer literal."""
        mod = _parse("unit km = m * 1000;")
        km = mod.unit_decls[0]
        assert km.base_exponents[0] == 1   # m^1
        assert km.scale == pytest.approx(1000.0)

    def test_unit_khz_with_numeric_scale(self):
        """kHz = Hz * 1000."""
        src = "unit Hz = 1/s;\nunit kHz = Hz * 1000;"
        mod = _parse(src)
        khz = next(d for d in mod.unit_decls if d.name == "kHz")
        assert khz.base_exponents[2] == -1  # s^-1
        assert khz.scale == pytest.approx(1000.0)

    def test_unit_deg_with_pi_constant(self):
        """deg = rad * (PI/180) -- PI scaling constant."""
        mod = _parse("unit deg = rad * (PI/180);")
        deg = mod.unit_decls[0]
        assert deg.base_exponents[7] == 1  # rad^1
        assert deg.scale == pytest.approx(3.141592653589793 / 180.0)

    def test_unit_tau_constant_allowed(self):
        """TAU is one of the permitted scaling constants."""
        mod = _parse("unit full_turn = rad * (TAU/1);")
        decl = mod.unit_decls[0]
        assert decl.scale == pytest.approx(6.283185307179586)

    def test_unit_euler_constant_allowed(self):
        """EULER is one of the permitted scaling constants."""
        mod = _parse("unit e_rad = rad * EULER;")
        decl = mod.unit_decls[0]
        import math
        assert decl.scale == pytest.approx(math.e)

    def test_multiple_unit_decls_in_order(self):
        src = (
            "unit Hz = 1/s;\n"
            "unit N = kg*m/s^2;\n"
            "unit Pa = N/m^2;\n"
        )
        mod = _parse(src)
        assert [d.name for d in mod.unit_decls] == ["Hz", "N", "Pa"]

    def test_unit_decl_before_const(self):
        """unit decls may precede const declarations."""
        src = "unit Hz = 1/s;\nconst F: Real[Hz] = 440.0;"
        mod = _parse(src)
        assert len(mod.unit_decls) == 1
        assert len(mod.constants) == 1

    def test_unit_dimensionless_one(self):
        """unit ratio = 1; -- dimensionless derived unit with scale 1."""
        mod = _parse("unit ratio = 1;")
        decl = mod.unit_decls[0]
        assert all(e == 0 for e in decl.base_exponents)
        assert decl.scale == pytest.approx(1.0)


# ── 2. Unit expressions in type positions ─────────────────────────────


class TestUnitTypeAnnotations:
    """Real[unit_expr] works in param, const, and return positions."""

    def test_param_type_with_hz(self):
        src = "fn f(x: Real[Hz]) -> Real { x }"
        # Hz is not declared so the parser treats it as an ident ref
        mod = _parse(src)
        p = mod.functions[0].params[0]
        assert p.type_name == "Real"
        assert p.unit_expr is not None
        assert p.unit_expr == "Hz"

    def test_param_type_real_bare_unchanged(self):
        """Bare `Real` with no bracket remains identical to pre-Phase-A."""
        src = "fn f(x: Real) -> Real { x }"
        mod = _parse(src)
        p = mod.functions[0].params[0]
        assert p.type_name == "Real"
        assert p.unit_expr is None

    def test_param_type_real_m_per_s2(self):
        """Real[m/s^2] -- compound unit expression in param."""
        src = "fn gravity(g: Real[m/s^2]) -> Real { g }"
        mod = _parse(src)
        p = mod.functions[0].params[0]
        assert p.type_name == "Real"
        assert p.unit_expr == "m/s^2"

    def test_param_type_real_dimensionless(self):
        """Real[1] -- explicit dimensionless annotation."""
        src = "fn f(x: Real[1]) -> Real { x }"
        mod = _parse(src)
        p = mod.functions[0].params[0]
        assert p.unit_expr == "1"

    def test_return_type_with_hz(self):
        """Return type Real[Hz] is captured on EMLFunction."""
        src = "fn f(x: Real[Hz]) -> Real[Hz] { x }"
        mod = _parse(src)
        fn = mod.functions[0]
        assert fn.return_type == "Real"
        assert fn.return_unit_expr == "Hz"

    def test_return_type_bare_real_unchanged(self):
        src = "fn f(x: Real) -> Real { x }"
        mod = _parse(src)
        fn = mod.functions[0]
        assert fn.return_type == "Real"
        assert fn.return_unit_expr is None

    def test_const_type_with_hz(self):
        """const F: Real[Hz] = 440.0; stores unit annotation."""
        src = "const F: Real[Hz] = 440.0;"
        mod = _parse(src)
        c = mod.constants[0]
        assert c.type_name == "Real"
        assert c.unit_expr == "Hz"

    def test_const_type_bare_real_unchanged(self):
        src = "const C: Real = 3.0;"
        mod = _parse(src)
        c = mod.constants[0]
        assert c.type_name == "Real"
        assert c.unit_expr is None

    def test_param_type_f64_no_unit_annotation(self):
        """Non-Real types (f64, etc.) remain untouched."""
        src = "fn f(x: f64) -> f64 { x }"
        mod = _parse(src)
        p = mod.functions[0].params[0]
        assert p.type_name == "f64"
        assert p.unit_expr is None

    def test_multiple_params_mixed_units(self):
        """Multiple params, some with units, some without."""
        src = "fn doppler(f0: Real[Hz], v: Real[m/s]) -> Real[Hz] { f0 }"
        mod = _parse(src)
        fn = mod.functions[0]
        assert fn.params[0].unit_expr == "Hz"
        assert fn.params[1].unit_expr == "m/s"
        assert fn.return_unit_expr == "Hz"

    def test_real_hz_const_value(self):
        """The constant's value expression is still parsed correctly."""
        src = "const F_NYQUIST: Real[Hz] = 22050.0;"
        mod = _parse(src)
        from lang.parser.ast_nodes import NodeKind
        c = mod.constants[0]
        assert c.value.kind == NodeKind.LITERAL
        assert c.value.value == pytest.approx(22050.0)


# ── 3. Full snippet round-trip ─────────────────────────────────────────


class TestFullSnippetRoundTrip:
    """The canonical Phase A snippet from the spec must parse cleanly."""

    DOPPLER_SRC = """\
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

fn doppler_shift(f0: Real[Hz], v_rel: Real[m/s]) -> Real[Hz]
    where chain_order <= 0
{
    f0 * (1.0 + v_rel / 299792458.0)
}
"""

    def test_full_snippet_parses(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        assert len(mod.unit_decls) == 9
        assert len(mod.constants) == 2
        assert len(mod.functions) == 1

    def test_unit_decls_correct_names(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        names = [d.name for d in mod.unit_decls]
        assert names == ["Hz", "N", "Pa", "J", "W", "V", "km", "kHz", "deg"]

    def test_g_gravity_constant(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        g = next(c for c in mod.constants if c.name == "G_GRAVITY")
        assert g.type_name == "Real"
        assert g.unit_expr == "m/s^2"

    def test_f_nyquist_constant(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        f = next(c for c in mod.constants if c.name == "F_NYQUIST")
        assert f.unit_expr == "Hz"

    def test_doppler_function_params(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        fn = mod.functions[0]
        assert fn.params[0].unit_expr == "Hz"
        assert fn.params[1].unit_expr == "m/s"

    def test_doppler_function_return_unit(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        fn = mod.functions[0]
        assert fn.return_unit_expr == "Hz"

    def test_doppler_where_clause_preserved(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        fn = mod.functions[0]
        assert len(fn.where_clauses) == 1
        assert fn.where_clauses[0].kind == "chain_order"

    def test_hz_exponents(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        hz = next(d for d in mod.unit_decls if d.name == "Hz")
        assert hz.base_exponents[2] == -1  # s^-1
        assert hz.scale == pytest.approx(1.0)

    def test_khz_exponents_and_scale(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        khz = next(d for d in mod.unit_decls if d.name == "kHz")
        assert khz.base_exponents[2] == -1
        assert khz.scale == pytest.approx(1000.0)

    def test_deg_scale(self):
        mod = parse_source(self.DOPPLER_SRC, "<spec>")
        deg = next(d for d in mod.unit_decls if d.name == "deg")
        assert deg.base_exponents[7] == 1  # rad^1
        assert deg.scale == pytest.approx(3.141592653589793 / 180.0)


# ── 4. Negative / rejection cases ─────────────────────────────────────


class TestRejectionCases:
    """Invalid unit syntax must raise ParseError."""

    def test_unit_rhs_function_call_rejected(self):
        """unit foo = bar(); -- function calls not allowed in unit RHS."""
        with pytest.raises(ParseError, match="(?i)unit"):
            _parse("unit foo = bar();")

    def test_unit_rhs_unknown_ident_rejected(self):
        """unit foo = m * x; -- unknown identifier x not allowed."""
        with pytest.raises(ParseError, match="(?i)unknown|undeclared|identifier"):
            _parse("unit foo = m * x;")

    def test_type_unit_additive_rejected(self):
        """Real[m + s] -- additive unit expressions are not unit algebra."""
        with pytest.raises(ParseError, match="(?i)unit"):
            _parse("fn f(x: Real[m + s]) -> Real { x }")

    def test_unit_rhs_string_literal_rejected(self):
        """unit foo = \"m\"; -- strings are not unit expressions."""
        with pytest.raises(ParseError):
            _parse('unit foo = "m";')

    def test_unit_rhs_no_bool_rejected(self):
        """unit foo = true; -- booleans are not unit expressions."""
        with pytest.raises(ParseError):
            _parse("unit foo = true;")


# ── 5. Backwards-compatibility round-trips ────────────────────────────


class TestBackwardsCompatibility:
    """Existing .eml files must still parse without change."""

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
    def test_existing_file_still_parses(self, path: Path):
        mod = parse_file(path, resolve=False)
        assert (mod.functions or mod.constants or mod.types), \
            f"{path.name}: parsed empty module"

    @pytest.mark.parametrize("path", [
        EXAMPLES_DIR / "pid_controller.eml",
        EXAMPLES_DIR / "sigmoid.eml",
        GRAMMAR_EXAMPLES_DIR / "motor_control.eml",
    ])
    def test_existing_file_no_unit_decls(self, path: Path):
        """Files without unit declarations should have empty unit_decls."""
        mod = parse_file(path, resolve=False)
        assert mod.unit_decls == []

    @pytest.mark.parametrize("path", [
        EXAMPLES_DIR / "pid_controller.eml",
        GRAMMAR_EXAMPLES_DIR / "arrhenius.eml",
    ])
    def test_existing_params_have_no_unit_expr(self, path: Path):
        """Existing params without [unit] annotations have unit_expr=None."""
        mod = parse_file(path, resolve=False)
        for fn in mod.functions:
            for p in fn.params:
                assert p.unit_expr is None, \
                    f"{path.name}: {fn.name}.{p.name} unexpectedly got unit_expr"

    def test_existing_const_no_unit_expr(self):
        """Existing consts without [unit] have unit_expr=None."""
        mod = parse_file(EXAMPLES_DIR / "pid_controller.eml", resolve=False)
        for c in mod.constants:
            assert c.unit_expr is None

    def test_existing_return_type_no_unit_expr(self):
        """Existing functions without return unit annotations are unchanged."""
        mod = parse_file(GRAMMAR_EXAMPLES_DIR / "motor_control.eml", resolve=False)
        for fn in mod.functions:
            assert fn.return_unit_expr is None


# ── 6. AST shape assertions ───────────────────────────────────────────


class TestASTShape:
    """Check the dataclass fields are correctly populated."""

    def test_emlunitdecl_is_dataclass(self):
        mod = _parse("unit Hz = 1/s;")
        decl = mod.unit_decls[0]
        assert isinstance(decl, EMLUnitDecl)

    def test_emlunitdecl_fields(self):
        mod = _parse("unit Hz = 1/s;")
        decl = mod.unit_decls[0]
        assert hasattr(decl, "name")
        assert hasattr(decl, "base_exponents")
        assert hasattr(decl, "scale")
        assert hasattr(decl, "line")
        assert hasattr(decl, "col")

    def test_base_exponents_length_8(self):
        """base_exponents must be a tuple/list of exactly 8 integers."""
        mod = _parse("unit Hz = 1/s;")
        decl = mod.unit_decls[0]
        assert len(decl.base_exponents) == 8

    def test_param_unit_expr_is_string_or_none(self):
        src = "fn f(x: Real[Hz]) -> Real { x }"
        mod = _parse(src)
        p = mod.functions[0].params[0]
        assert isinstance(p.unit_expr, str)

    def test_emlconstant_unit_expr_field(self):
        src = "const C: Real[m/s^2] = 9.81;"
        mod = _parse(src)
        c = mod.constants[0]
        assert hasattr(c, "unit_expr")
        assert c.unit_expr == "m/s^2"

    def test_emlfuction_return_unit_expr_field(self):
        src = "fn f() -> Real[m/s^2] { 9.81 }"
        mod = _parse(src)
        fn = mod.functions[0]
        assert hasattr(fn, "return_unit_expr")
        assert fn.return_unit_expr == "m/s^2"

    def test_emlmodule_unit_decls_field(self):
        """EMLModule must expose a unit_decls list."""
        mod = _parse("")
        assert hasattr(mod, "unit_decls")
        assert isinstance(mod.unit_decls, list)
