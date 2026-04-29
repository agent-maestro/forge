"""Tests for the SuperBEST routing pass."""

from __future__ import annotations

import pytest

from lang.optimizer.superbest import (
    superbest_function,
    superbest_module,
    route_superbest,
)
from lang.parser.parser import parse_source
from lang.parser.ast_nodes import ASTNode, NodeKind
from lang.profiler.profiler import Profiler


# ── 1. Backwards-compat: route_superbest is identity ──────────


def test_route_superbest_is_identity_on_node() -> None:
    n = ASTNode(kind=NodeKind.LITERAL, value=1.0)
    out = route_superbest(n)
    assert out is n


# ── 2. Sigmoid family rewrite ────────────────────────────────


def test_alt_sigmoid_rewrites_to_canonical() -> None:
    """`tanh(x/2)/2 + 1/2` is the alternative sigmoid form;
    SuperBEST should rewrite it to `1/(1 + exp(-x))`."""
    src = (
        "fn alt(x: f64) -> f64 { tanh(x / 2.0) / 2.0 + 0.5 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = superbest_module(mod)
    fn = out.functions[0]
    assert fn.profile.get("superbest_family") == "sigmoid"
    assert fn.profile.get("superbest_digits_saved", 0) > 0.5
    # Body now has an `exp` with a unary-minus argument and a
    # `1 / (1 + ...)` shape -- not a tanh.
    assert not _has_kind(fn.body, NodeKind.TANH)
    assert _has_kind(fn.body, NodeKind.EXP)


# ── 3. No-op cases ───────────────────────────────────────────


def test_already_canonical_is_no_op() -> None:
    """A body already in canonical sigmoid form (saves 0 digits)
    must NOT be rewritten -- no point and the warning would be
    misleading."""
    src = (
        "fn s(x: f64) -> f64 { 1.0 / (1.0 + exp(-x)) }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = superbest_module(mod)
    fn = out.functions[0]
    # No SuperBEST family annotation since digits_saved was 0.
    assert "superbest_family" not in (fn.profile or {})


def test_unsupported_family_left_alone() -> None:
    """Most expressions don't match any of the 4 supported families;
    superbest passes them through unchanged."""
    src = (
        "fn t(x: f64, y: f64) -> f64 { x * y + sin(x) }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = superbest_module(mod)
    fn = out.functions[0]
    assert "superbest_family" not in (fn.profile or {})


def test_complex_body_skipped() -> None:
    """Bodies with let / mut / while are skipped -- the SymPy
    bridge can't lambdify them."""
    src = (
        "fn t(x: f64) -> f64 {\n"
        "    let y = x * x;\n"
        "    y + 1.0\n"
        "}\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = superbest_module(mod)
    # Body unchanged: 2 children (LET + final expr).
    assert len(out.functions[0].body.children) == 2


def test_tuple_return_skipped() -> None:
    src = (
        "fn t(x: f64) -> (f64, f64) { (x, x * x) }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = superbest_module(mod)
    assert "superbest_family" not in (out.functions[0].profile or {})


# ── 4. Idempotence + non-mutation ────────────────────────────


def test_superbest_is_idempotent() -> None:
    src = (
        "fn alt(x: f64) -> f64 { tanh(x / 2.0) / 2.0 + 0.5 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    once = superbest_module(mod)
    twice = superbest_module(once)
    a_body = once.functions[0].body
    b_body = twice.functions[0].body
    assert _shape(a_body) == _shape(b_body)


def test_superbest_does_not_mutate_input() -> None:
    src = (
        "fn alt(x: f64) -> f64 { tanh(x / 2.0) / 2.0 + 0.5 }\n"
    )
    mod = parse_source(src)
    Profiler().profile_module(mod)
    before = _shape(mod.functions[0].body)
    _ = superbest_module(mod)
    assert _shape(mod.functions[0].body) == before


# ── Helpers ──────────────────────────────────────────────────


def _has_kind(n: ASTNode, kind: NodeKind) -> bool:
    if n.kind == kind:
        return True
    return any(_has_kind(c, kind) for c in n.children)


def _shape(n: ASTNode) -> tuple:
    return (
        n.kind.value, repr(n.value),
        tuple(_shape(c) for c in n.children),
    )
