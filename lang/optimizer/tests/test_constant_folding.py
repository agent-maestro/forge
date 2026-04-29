"""Tests for the constant-folding optimization pass."""

from __future__ import annotations

import math

import pytest

from lang.optimizer.constant_folding import fold_constants
from lang.parser.ast_nodes import ASTNode, NodeKind


# ── Builders for terse test ASTs ──────────────────────────────


def lit(v) -> ASTNode:
    return ASTNode(kind=NodeKind.LITERAL, value=v)


def var(name: str) -> ASTNode:
    return ASTNode(kind=NodeKind.VAR, value=name)


def bop(op: str, l: ASTNode, r: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BINOP, value=op, children=[l, r])


def uop(op: str, x: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.UNARYOP, value=op, children=[x])


def call_builtin(kind: NodeKind, *args: ASTNode) -> ASTNode:
    return ASTNode(kind=kind, value=kind.value, children=list(args))


# ── Numeric folding ──────────────────────────────────────────


@pytest.mark.parametrize("op,a,b,expected", [
    ("+", 1, 2, 3),
    ("+", 1.5, 2.5, 4.0),
    ("-", 10, 3, 7),
    ("*", 4, 5, 20),
    ("*", 2.0, 3.5, 7.0),
    ("/", 10.0, 4.0, 2.5),
    ("/", 9, 3, 3.0),
])
def test_binop_two_literals_folds(op, a, b, expected) -> None:
    out = fold_constants(bop(op, lit(a), lit(b)))
    assert out.kind == NodeKind.LITERAL
    assert out.value == expected


def test_div_by_zero_does_not_fold() -> None:
    """Folding div-by-zero would change semantics -- backends
    each define their own behaviour for runtime div-by-zero, and
    the compiler shouldn't preempt that."""
    src = bop("/", lit(1.0), lit(0.0))
    out = fold_constants(src)
    assert out.kind == NodeKind.BINOP
    assert out.value == "/"


@pytest.mark.parametrize("op,a,b,expected", [
    ("==", 3, 3, True),
    ("!=", 3, 3, False),
    ("<",  2, 3, True),
    ("<=", 3, 3, True),
    (">",  4, 3, True),
    (">=", 4, 3, True),
])
def test_comparison_folds_to_bool(op, a, b, expected) -> None:
    out = fold_constants(bop(op, lit(a), lit(b)))
    assert out.kind == NodeKind.LITERAL
    assert out.value is expected


@pytest.mark.parametrize("op,a,b,expected", [
    ("&&", True,  True,  True),
    ("&&", True,  False, False),
    ("||", False, False, False),
    ("||", True,  False, True),
])
def test_boolean_op_folds(op, a, b, expected) -> None:
    out = fold_constants(bop(op, lit(a), lit(b)))
    assert out.kind == NodeKind.LITERAL
    assert out.value is expected


# ── Unary folding ────────────────────────────────────────────


@pytest.mark.parametrize("v,expected", [
    (3, -3), (3.5, -3.5), (-2, 2),
])
def test_unary_minus_on_literal(v, expected) -> None:
    out = fold_constants(uop("-", lit(v)))
    assert out.kind == NodeKind.LITERAL
    assert out.value == expected


def test_unary_not_on_bool() -> None:
    assert fold_constants(uop("!", lit(True))).value is False
    assert fold_constants(uop("!", lit(False))).value is True


# ── Algebraic identities ─────────────────────────────────────


def test_x_plus_zero_drops_literal() -> None:
    out = fold_constants(bop("+", var("x"), lit(0)))
    assert out.kind == NodeKind.VAR and out.value == "x"


def test_zero_plus_x_drops_literal() -> None:
    out = fold_constants(bop("+", lit(0), var("x")))
    assert out.kind == NodeKind.VAR and out.value == "x"


def test_x_times_one_drops_literal() -> None:
    out = fold_constants(bop("*", var("x"), lit(1)))
    assert out.kind == NodeKind.VAR and out.value == "x"


def test_one_times_x_drops_literal() -> None:
    out = fold_constants(bop("*", lit(1), var("x")))
    assert out.kind == NodeKind.VAR and out.value == "x"


def test_x_times_zero_collapses_for_safe_x() -> None:
    out = fold_constants(bop("*", var("x"), lit(0)))
    assert out.kind == NodeKind.LITERAL and out.value == 0


def test_zero_times_x_collapses_for_safe_x() -> None:
    out = fold_constants(bop("*", lit(0), var("x")))
    assert out.kind == NodeKind.LITERAL and out.value == 0


def test_zero_times_unsafe_call_does_not_collapse() -> None:
    """We must NOT silently discard a CALL because it might have
    side effects (the backend's user function could throw)."""
    user_call = ASTNode(
        kind=NodeKind.CALL, value="userfn",
        children=[var("x")],
    )
    out = fold_constants(bop("*", lit(0), user_call))
    assert out.kind == NodeKind.BINOP


def test_x_minus_zero_drops_literal() -> None:
    out = fold_constants(bop("-", var("x"), lit(0)))
    assert out.kind == NodeKind.VAR and out.value == "x"


def test_zero_minus_x_becomes_unary_minus() -> None:
    out = fold_constants(bop("-", lit(0), var("x")))
    assert out.kind == NodeKind.UNARYOP
    assert out.value == "-"
    assert out.children[0].kind == NodeKind.VAR


def test_x_div_one_drops_literal() -> None:
    out = fold_constants(bop("/", var("x"), lit(1)))
    assert out.kind == NodeKind.VAR and out.value == "x"


# ── Builtin folding ──────────────────────────────────────────


@pytest.mark.parametrize("kind,arg,expected", [
    (NodeKind.EXP,  0.0, 1.0),
    (NodeKind.LN,   1.0, 0.0),
    (NodeKind.SIN,  0.0, 0.0),
    (NodeKind.COS,  0.0, 1.0),
    (NodeKind.SQRT, 9.0, 3.0),
    (NodeKind.SQRT, 0.0, 0.0),
    (NodeKind.ABS,  -5.0, 5.0),
    (NodeKind.TANH, 0.0, 0.0),
])
def test_builtin_on_literal_folds(kind, arg, expected) -> None:
    out = fold_constants(call_builtin(kind, lit(arg)))
    assert out.kind == NodeKind.LITERAL
    assert math.isclose(out.value, expected, abs_tol=1e-12)


def test_ln_of_negative_does_not_fold() -> None:
    """ln(-1) raises ValueError; the optimizer must keep the node."""
    out = fold_constants(call_builtin(NodeKind.LN, lit(-1.0)))
    assert out.kind == NodeKind.LN


def test_pow_of_two_literals_folds() -> None:
    out = fold_constants(call_builtin(
        NodeKind.POW, lit(2.0), lit(10.0),
    ))
    assert out.kind == NodeKind.LITERAL
    assert out.value == 1024.0


def test_clamp_all_literal_folds() -> None:
    out = fold_constants(call_builtin(
        NodeKind.CLAMP, lit(5.0), lit(0.0), lit(3.0),
    ))
    assert out.kind == NodeKind.LITERAL
    assert out.value == 3.0


def test_clamp_with_var_does_not_fold() -> None:
    out = fold_constants(call_builtin(
        NodeKind.CLAMP, var("x"), lit(0.0), lit(3.0),
    ))
    assert out.kind == NodeKind.CLAMP


def test_eml_two_literals_folds() -> None:
    """eml(0, 1) = exp(0) - ln(1) = 1.0 - 0.0 = 1.0"""
    out = fold_constants(call_builtin(
        NodeKind.EML, lit(0.0), lit(1.0),
    ))
    assert out.kind == NodeKind.LITERAL
    assert out.value == 1.0


# ── Recursive folding ────────────────────────────────────────


def test_nested_literal_arithmetic_folds_completely() -> None:
    """((1+2) * (3+4)) -> 21 in one pass."""
    expr = bop(
        "*",
        bop("+", lit(1), lit(2)),
        bop("+", lit(3), lit(4)),
    )
    out = fold_constants(expr)
    assert out.kind == NodeKind.LITERAL
    assert out.value == 21


def test_partial_folding_keeps_var() -> None:
    """((1+2) * x) -> (3 * x)"""
    expr = bop("*", bop("+", lit(1), lit(2)), var("x"))
    out = fold_constants(expr)
    assert out.kind == NodeKind.BINOP
    assert out.children[0].kind == NodeKind.LITERAL
    assert out.children[0].value == 3
    assert out.children[1].kind == NodeKind.VAR


# ── Idempotence + non-mutation ───────────────────────────────


def test_fold_is_idempotent() -> None:
    expr = bop(
        "+",
        bop("*", lit(2), lit(3)),
        var("y"),
    )
    once = fold_constants(expr)
    twice = fold_constants(once)
    assert _shape(once) == _shape(twice)


def test_fold_does_not_mutate_input() -> None:
    expr = bop("+", lit(1), lit(2))
    original_kind = expr.kind
    _ = fold_constants(expr)
    assert expr.kind == original_kind  # still BINOP


def _shape(n: ASTNode) -> tuple:
    return (
        n.kind.value, repr(n.value),
        tuple(_shape(c) for c in n.children),
    )


# ── Real-world stdlib smoke ──────────────────────────────────


def test_folds_constants_in_lerp_at_t_zero() -> None:
    """Constructing the body of lerp(a, b, t) symbolically and
    plugging t = 0 should fold to just `a`."""
    # Body of lerp: a + t * (b - a). With t = 0:
    body = bop(
        "+",
        var("a"),
        bop("*", lit(0.0), bop("-", var("b"), var("a"))),
    )
    out = fold_constants(body)
    # 0 * (b - a)  -> 0   (since b - a is "safe")
    # a + 0        -> a
    assert out.kind == NodeKind.VAR
    assert out.value == "a"


def test_folds_zero_times_b_minus_a_safely() -> None:
    """`b - a` is safe to drop (vars + binop of vars only)."""
    expr = bop("*", lit(0.0), bop("-", var("b"), var("a")))
    out = fold_constants(expr)
    assert out.kind == NodeKind.LITERAL
    assert out.value == 0.0
