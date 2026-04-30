"""Tests for the ML-routing optimizer pass (lang/optimizer/ml_routing.py).

The pass is opt-in (off by default). It rewrites canonical activation
patterns to direct CALL nodes targeting libmonogate runtime symbols
on functions whose profile says drift_risk == HIGH.
"""

from __future__ import annotations

import pytest

from lang.optimizer import optimize_module, route_ml_activations_module
from lang.optimizer.ml_routing import (
    RUNTIME_SYMBOLS,
    route_ml_activations,
    _try_match_sigmoid,
    _try_match_softplus,
)
from lang.parser import parse_source
from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind
from lang.profiler import Profiler


# ── Pattern matchers ───────────────────────────────────────────────


def _lit(v: float) -> ASTNode:
    return ASTNode(kind=NodeKind.LITERAL, value=v)


def _var(n: str) -> ASTNode:
    return ASTNode(kind=NodeKind.VAR, value=n)


def _binop(op: str, a: ASTNode, b: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BINOP, value=op, children=[a, b])


def _exp(x: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.EXP, children=[x])


def _ln(x: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.LN, children=[x])


def _neg(x: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.UNARYOP, value="-", children=[x])


def test_sigmoid_pattern_matches():
    # 1 / (1 + exp(-x))
    pattern = _binop("/",
                     _lit(1.0),
                     _binop("+", _lit(1.0), _exp(_neg(_var("x")))))
    assert _try_match_sigmoid(pattern) is not None


def test_sigmoid_pattern_matches_swapped_addition():
    # 1 / (exp(-x) + 1)
    pattern = _binop("/",
                     _lit(1.0),
                     _binop("+", _exp(_neg(_var("x"))), _lit(1.0)))
    assert _try_match_sigmoid(pattern) is not None


def test_sigmoid_pattern_rejects_non_unit_numerator():
    # 2 / (1 + exp(-x)) — not sigmoid
    pattern = _binop("/",
                     _lit(2.0),
                     _binop("+", _lit(1.0), _exp(_neg(_var("x")))))
    assert _try_match_sigmoid(pattern) is None


def test_sigmoid_pattern_rejects_positive_arg():
    # 1 / (1 + exp(x)) — that's `expit(-x)`, not sigmoid
    pattern = _binop("/",
                     _lit(1.0),
                     _binop("+", _lit(1.0), _exp(_var("x"))))
    assert _try_match_sigmoid(pattern) is None


def test_softplus_pattern_matches():
    # ln(1 + exp(x))
    pattern = _ln(_binop("+", _lit(1.0), _exp(_var("x"))))
    assert _try_match_softplus(pattern) is not None


def test_softplus_pattern_rejects_non_unit_offset():
    pattern = _ln(_binop("+", _lit(2.0), _exp(_var("x"))))
    assert _try_match_softplus(pattern) is None


# ── End-to-end via the public optimizer entry ──────────────────────


def _drift_high_sigmoid_module():
    src = """module t;
fn f(x: f64) -> f64 {
    1.0 / (1.0 + exp(-x))
}
"""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    # Force HIGH drift so the gate fires.
    fn = mod.functions[0]
    fn.profile = dict(fn.profile or {})
    fn.profile["fp16_drift_risk"] = "HIGH"
    return mod


def test_high_drift_sigmoid_rewrites_to_runtime_call():
    mod = _drift_high_sigmoid_module()
    out = route_ml_activations_module(mod)
    body = out.functions[0].body
    # The body's final expression is now CALL("mg_sigmoid_route", x).
    final = body.children[-1]
    assert final.kind == NodeKind.CALL
    assert final.value == "mg_sigmoid_route"
    assert final.value in RUNTIME_SYMBOLS


def test_low_drift_sigmoid_unchanged():
    src = """module t;
fn f(x: f64) -> f64 {
    1.0 / (1.0 + exp(-x))
}
"""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    # Default drift is LOW -- pass should be a no-op.
    out = route_ml_activations_module(mod)
    final = out.functions[0].body.children[-1]
    # Still a BINOP `/` (the sigmoid pattern).
    assert final.kind == NodeKind.BINOP
    assert final.value == "/"


def test_optimize_module_default_does_not_route():
    """Without `ml_routing=True`, optimize_module must not produce
    runtime-symbol CALLs (preserves backwards-compatible default)."""
    mod = _drift_high_sigmoid_module()
    out = optimize_module(mod)
    final = out.functions[0].body.children[-1]
    assert final.kind != NodeKind.CALL or \
        final.value not in RUNTIME_SYMBOLS


def test_optimize_module_with_flag_routes():
    mod = _drift_high_sigmoid_module()
    out = optimize_module(mod, ml_routing=True)
    # Find a CALL("mg_sigmoid_route", ...) anywhere in the function body.
    fn = out.functions[0]

    def has_runtime_call(node: ASTNode) -> bool:
        if node.kind == NodeKind.CALL and node.value in RUNTIME_SYMBOLS:
            return True
        return any(has_runtime_call(c) for c in node.children)

    assert has_runtime_call(fn.body)


def test_softplus_high_drift_rewrites():
    src = """module t;
fn f(x: f64) -> f64 {
    ln(1.0 + exp(x))
}
"""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    fn = mod.functions[0]
    fn.profile = dict(fn.profile or {})
    fn.profile["fp16_drift_risk"] = "HIGH"
    out = route_ml_activations_module(mod)
    final = out.functions[0].body.children[-1]
    assert final.kind == NodeKind.CALL
    assert final.value == "mg_softplus_route"
