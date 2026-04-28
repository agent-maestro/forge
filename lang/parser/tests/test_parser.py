"""Tests for `lang.parser.parser` -- recursive-descent + Pratt parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import (
    NodeKind,
    ParseError,
    parse_file,
    parse_source,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


# ── All demo files parse cleanly (the integration-level guarantee) ──

@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_demo_file_parses(filename: str) -> None:
    """Every .eml in lang/spec/grammar/examples/ must parse cleanly."""
    mod = parse_file(EXAMPLES_DIR / filename)
    # At least one declaration of some kind in every demo file.
    assert (mod.functions or mod.constants or mod.types), \
        f"{filename}: parsed empty module"


# ── Module-level shape ──────────────────────────────────────────────


def test_hello_module_shape():
    mod = parse_file(EXAMPLES_DIR / "hello.eml")
    assert mod.name == "hello"
    assert len(mod.functions) == 1
    assert mod.functions[0].name == "answer"
    assert mod.functions[0].return_type == "f64"


def test_pid_basic_shape():
    mod = parse_file(EXAMPLES_DIR / "pid_basic.eml")
    assert mod.name == "pid_basic"
    assert {c.name for c in mod.constants} == {"Kp", "Ki", "Kd"}
    assert {f.name for f in mod.functions} == {"pid"}
    pid = mod.functions[0]
    assert [p.name for p in pid.params] == ["error", "integral", "derivative"]


def test_motor_control_full_shape():
    """The comprehensive demo from the design doc -- spans every
    feature: type aliases, multi-clause where, @target, @verify,
    requires/ensures."""
    mod = parse_file(EXAMPLES_DIR / "motor_control.eml")
    assert len(mod.constants) == 11
    assert {t.name for t in mod.types} == {"StableSignal", "OscSignal"}
    assert len(mod.functions) == 6
    fn_names = {f.name for f in mod.functions}
    assert {"pid_output", "damped_response", "motor_torque",
            "unstable_gain", "realtime_control", "safe_pid"} == fn_names


def test_motor_foc_returns_tuple():
    mod = parse_file(EXAMPLES_DIR / "motor_foc.eml")
    park = mod.functions[0]
    assert park.return_type == ""
    assert park.return_tuple_types == ["f64", "f64"]


def test_orbit_uses_mut_and_while():
    """orbit.eml is the most syntax-heavy demo -- mut bindings,
    while loop, assignment to mut binding."""
    mod = parse_file(EXAMPLES_DIR / "orbit.eml")
    body = mod.functions[0].body
    # Walk the block looking for LET_MUT, ASSIGN, WHILE
    kinds = {c.kind for c in body.children}
    assert NodeKind.LET_MUT in kinds
    assert NodeKind.WHILE in kinds


# ── Type aliases + chain-order constraints ──────────────────────────


def test_type_alias_carries_chain_order_constraint():
    mod = parse_file(EXAMPLES_DIR / "motor_control.eml")
    stable = next(t for t in mod.types if t.name == "StableSignal")
    assert stable.base_type == "Real"
    assert stable.constraint == {"op": "<=", "value": 2}


def test_function_where_clauses_parsed():
    mod = parse_file(EXAMPLES_DIR / "arrhenius.eml")
    rate = mod.functions[0]
    kinds = [w.kind for w in rate.where_clauses]
    assert "chain_order" in kinds
    assert "domain" in kinds


def test_precision_where_clause():
    mod = parse_file(EXAMPLES_DIR / "sigmoid.eml")
    sig = next(f for f in mod.functions if f.name == "sigmoid")
    prec = next(w for w in sig.where_clauses if w.kind == "precision")
    assert prec.op == "<="
    assert prec.value == pytest.approx(1e-12)


# ── Annotations ─────────────────────────────────────────────────────


def test_target_annotation_args_parsed():
    mod = parse_file(EXAMPLES_DIR / "motor_control.eml")
    rc = next(f for f in mod.functions if f.name == "realtime_control")
    assert len(rc.annotations) == 1
    ann = rc.annotations[0]
    assert ann.kind == "target"
    assert ann.args[0] == "fpga"            # positional
    assert ann.args["clock_mhz"] == "100"   # keyword
    assert ann.args["precision"] == "float32"


def test_verify_annotation_with_requires_ensures():
    mod = parse_file(EXAMPLES_DIR / "motor_control.eml")
    sp = next(f for f in mod.functions if f.name == "safe_pid")
    assert sp.annotations[0].kind == "verify"
    assert sp.annotations[0].args["theorem"] == "pid_bounded"
    assert len(sp.requires) == 2
    assert len(sp.ensures) == 1


# ── Expression parsing ─────────────────────────────────────────────


def test_arithmetic_precedence_left_to_right():
    """1 + 2 * 3 should parse as 1 + (2 * 3)."""
    mod = parse_source("fn f() -> f64 { 1 + 2 * 3 }", "<test>")
    expr = mod.functions[0].body.children[-1]
    assert expr.kind == NodeKind.BINOP and expr.value == "+"
    assert expr.children[0].value == 1                      # left = 1
    right = expr.children[1]
    assert right.kind == NodeKind.BINOP and right.value == "*"


def test_unary_minus():
    mod = parse_source("fn f() -> f64 { -42.0 }", "<test>")
    expr = mod.functions[0].body.children[-1]
    assert expr.kind == NodeKind.UNARYOP and expr.value == "-"
    assert expr.children[0].value == 42.0


def test_builtin_dispatch():
    """sin(x) should produce NodeKind.SIN, not generic CALL."""
    mod = parse_source("fn f(x: f64) -> f64 { sin(x) }", "<test>")
    expr = mod.functions[0].body.children[-1]
    assert expr.kind == NodeKind.SIN
    assert expr.value == "sin"


def test_user_function_call_is_generic_call():
    mod = parse_source("fn f(x: f64) -> f64 { my_func(x) }", "<test>")
    expr = mod.functions[0].body.children[-1]
    assert expr.kind == NodeKind.CALL
    assert expr.value == "my_func"


def test_tuple_literal():
    mod = parse_source("fn f() -> (f64, f64) { (1.0, 2.0) }", "<test>")
    expr = mod.functions[0].body.children[-1]
    assert expr.kind == NodeKind.TUPLE
    assert len(expr.children) == 2


# ── Source-location tracking ────────────────────────────────────────


def test_node_carries_source_location():
    mod = parse_source(
        "// line 1 comment\nfn f() -> f64 { 42.0 }", "<test>")
    fn = mod.functions[0]
    assert fn.line == 2
    assert fn.col == 1


def test_parse_error_carries_location():
    with pytest.raises(ParseError) as exc:
        parse_source("fn f() -> f64 { let }", "bad.eml")
    msg = str(exc.value)
    assert "bad.eml:" in msg


# ── Source-file source attribute ────────────────────────────────────


def test_module_remembers_source_file():
    mod = parse_file(EXAMPLES_DIR / "hello.eml")
    assert mod.source_file.endswith("hello.eml")
