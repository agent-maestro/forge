"""Tests for the import tree-shaker pass."""

from __future__ import annotations

from lang.optimizer.tree_shaker import shake_imports
from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
    Param,
)
from lang.parser.parser import parse_source


# ── Builders ──────────────────────────────────────────────────


def lit(v) -> ASTNode:
    return ASTNode(kind=NodeKind.LITERAL, value=v)


def var(name: str) -> ASTNode:
    return ASTNode(kind=NodeKind.VAR, value=name)


def call(name: str, *args: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.CALL, value=name, children=list(args))


def block(*children: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BLOCK, children=list(children))


def make_fn(
    name: str, params: list[str], body: ASTNode,
    *, imported_from: str | None = None,
) -> EMLFunction:
    return EMLFunction(
        name=name,
        params=[Param(name=p, type_name="f64") for p in params],
        return_type="f64",
        body=body,
        imported_from=imported_from,
    )


# ── 1. Local functions are always preserved ──────────────────


def test_locals_kept_even_if_unreferenced() -> None:
    a = make_fn("a", ["x"], block(var("x")))
    b = make_fn("b", ["x"], block(var("x")))
    mod = EMLModule(name="t", functions=[a, b])
    out = shake_imports(mod)
    names = {f.name for f in out.functions}
    assert names == {"a", "b"}


# ── 2. Unreferenced imports get dropped ──────────────────────


def test_unreferenced_imports_dropped() -> None:
    local = make_fn("local", ["x"], block(var("x")))
    imp1 = make_fn("imp_used", ["x"], block(var("x")),
                   imported_from="stdlib::math")
    imp2 = make_fn("imp_unused", ["x"], block(var("x")),
                   imported_from="stdlib::math")
    # local body actually calls imp_used.
    local.body = block(call("imp_used", var("x")))
    mod = EMLModule(name="t", functions=[local, imp1, imp2])
    out = shake_imports(mod)
    names = {f.name for f in out.functions}
    assert names == {"local", "imp_used"}


def test_transitively_reached_imports_kept() -> None:
    """local -> imp_a -> imp_b. Both imports must survive."""
    local = make_fn("local", ["x"],
                    block(call("imp_a", var("x"))))
    imp_a = make_fn("imp_a", ["x"],
                    block(call("imp_b", var("x"))),
                    imported_from="stdlib::foo")
    imp_b = make_fn("imp_b", ["x"], block(var("x")),
                    imported_from="stdlib::foo")
    imp_dead = make_fn("imp_dead", ["x"], block(var("x")),
                       imported_from="stdlib::foo")
    mod = EMLModule(name="t", functions=[local, imp_a, imp_b, imp_dead])
    out = shake_imports(mod)
    names = {f.name for f in out.functions}
    assert names == {"local", "imp_a", "imp_b"}


# ── 3. Pure-library module: all functions survive ───────────


def test_pure_library_module_keeps_everything() -> None:
    """A module with NO local functions is treated as a library;
    every function is a root and the shaker is a no-op. This is
    what tests/stdlib/test_stdlib.py requires."""
    src = """\
fn lerp(a: f64, b: f64, t: f64) -> f64 { a + t * (b - a) }
fn sq(x: f64) -> f64 { x * x }
"""
    mod = parse_source(src)
    # Mark both as imported (no locals at all):
    for f in mod.functions:
        f.imported_from = "stdlib::math"
    out = shake_imports(mod)
    assert len(out.functions) == 2


# ── 4. Idempotence + non-mutation ────────────────────────────


def test_shaker_is_idempotent() -> None:
    local = make_fn("local", ["x"], block(call("imp_used", var("x"))))
    imp_used = make_fn("imp_used", ["x"], block(var("x")),
                       imported_from="stdlib::math")
    imp_dead = make_fn("imp_dead", ["x"], block(var("x")),
                       imported_from="stdlib::math")
    mod = EMLModule(name="t", functions=[local, imp_used, imp_dead])
    once = shake_imports(mod)
    twice = shake_imports(once)
    assert {f.name for f in once.functions} == \
           {f.name for f in twice.functions}


def test_shaker_does_not_mutate_input() -> None:
    local = make_fn("local", ["x"], block(var("x")))
    imp_dead = make_fn("imp_dead", ["x"], block(var("x")),
                       imported_from="stdlib::math")
    mod = EMLModule(name="t", functions=[local, imp_dead])
    _ = shake_imports(mod)
    # Input still has both functions.
    assert {f.name for f in mod.functions} == {"local", "imp_dead"}


# ── 5. End-to-end via parse + resolve_imports ────────────────


def test_unused_stdlib_imports_dropped_after_resolve() -> None:
    """Real-world flow: import stdlib::math, call only `lerp`.
    All 20 other math functions get dropped."""
    src = (
        "use stdlib::math;\n"
        "fn midpoint(a: f64, b: f64) -> f64 { lerp(a, b, 0.5) }\n"
    )
    mod = parse_source(src, resolve=True)
    # Before shaking: 1 local + 21 imported = 22
    assert len(mod.functions) == 22
    out = shake_imports(mod)
    names = {f.name for f in out.functions}
    # After shaking: just `midpoint` and `lerp`.
    assert names == {"midpoint", "lerp"}
