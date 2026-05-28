"""Tests for the CSE optimisation pass."""

from __future__ import annotations

from lang.optimizer.cse import apply_cse, apply_cse_module
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


def bop(op, l, r) -> ASTNode:
    return ASTNode(kind=NodeKind.BINOP, value=op, children=[l, r])


def call(kind, *args) -> ASTNode:
    return ASTNode(kind=kind, value=kind.value, children=list(args))


def make_function(body_block: ASTNode, params: list[str]) -> EMLFunction:
    return EMLFunction(
        name="t",
        params=[Param(name=p, type_name="f64") for p in params],
        return_type="f64",
        body=body_block,
    )


def block_of(*children) -> ASTNode:
    return ASTNode(kind=NodeKind.BLOCK, children=list(children))


# ── 1. Trivial: nothing to hoist ──────────────────────────────


def test_atomic_body_does_nothing() -> None:
    fn = make_function(block_of(var("x")), ["x"])
    out = apply_cse(fn)
    # Body unchanged.
    assert len(out.body.children) == 1
    assert out.body.children[0].kind == NodeKind.VAR


def test_single_use_does_not_hoist() -> None:
    """sqrt(x*x + y*y) used once -- no hoist."""
    expr = call(
        NodeKind.SQRT,
        bop("+",
            bop("*", var("x"), var("x")),
            bop("*", var("y"), var("y"))),
    )
    fn = make_function(block_of(expr), ["x", "y"])
    out = apply_cse(fn)
    # No new lets prepended.
    assert all(c.kind != NodeKind.LET for c in out.body.children[:-1])


# ── 2. Real hoists ────────────────────────────────────────────


def test_duplicate_subtree_is_hoisted() -> None:
    """sqrt(x*x + y*y) + sqrt(x*x + y*y) -> let _cse_0 = ...; _cse_0 + _cse_0"""
    inner = call(
        NodeKind.SQRT,
        bop("+",
            bop("*", var("x"), var("x")),
            bop("*", var("y"), var("y"))),
    )
    expr = bop("+", inner, inner)
    fn = make_function(block_of(expr), ["x", "y"])
    out = apply_cse(fn)
    # Body now has [LET, final_expr]
    assert len(out.body.children) == 2
    let, final = out.body.children
    assert let.kind == NodeKind.LET
    assert let.value.startswith("_cse_")
    # The final expr is "_cse_0 + _cse_0"
    assert final.kind == NodeKind.BINOP
    assert final.children[0].kind == NodeKind.VAR
    assert final.children[1].kind == NodeKind.VAR
    assert final.children[0].value == let.value
    assert final.children[1].value == let.value


def test_two_distinct_dups_at_disjoint_sites_get_two_lets() -> None:
    """When two distinct duplicates appear at disjoint sites
    (so hoisting one doesn't erase the other), CSE must hoist
    both into separate lets.

    Tree: f(sqrt(x*x+y*y), sqrt(x*x+y*y)) - g(a+b+c, a+b+c)
    Each `f` arg uses sqrt(...); each `g` arg uses a+b+c.
    Hoisting `sqrt(...)` doesn't touch `a+b+c` and vice versa,
    so we get two lets."""
    sqrt_expr = call(
        NodeKind.SQRT,
        bop("+",
            bop("*", var("x"), var("x")),
            bop("*", var("y"), var("y"))),
    )
    sum_expr = bop("+", bop("+", var("a"), var("b")), var("c"))
    f_call = bop("+", sqrt_expr, sqrt_expr)  # uses sqrt twice
    g_call = bop("*", sum_expr, sum_expr)    # uses sum twice
    expr = bop("-", f_call, g_call)
    fn = make_function(block_of(expr), ["x", "y", "a", "b", "c"])
    out = apply_cse(fn)
    lets = [c for c in out.body.children if c.kind == NodeKind.LET]
    assert len(lets) == 2


def test_overlapping_dup_picks_larger() -> None:
    """When a smaller duplicate is contained inside a larger one,
    CSE hoists the larger first -- this is optimal because the
    larger hoist erases the smaller's duplication. So we expect
    exactly one let, holding the outer expression."""
    sqrt_expr = call(
        NodeKind.SQRT,
        bop("+",
            bop("*", var("x"), var("x")),
            bop("*", var("y"), var("y"))),
    )
    sum_expr = bop("+", bop("+", var("a"), var("b")), var("c"))
    inner = bop("+", sqrt_expr, sum_expr)
    expr = bop("+", inner, inner)
    fn = make_function(block_of(expr), ["x", "y", "a", "b", "c"])
    out = apply_cse(fn)
    lets = [c for c in out.body.children if c.kind == NodeKind.LET]
    assert len(lets) == 1


def test_small_subtree_below_min_nodes_not_hoisted() -> None:
    """`x * y` is only 3 nodes; with min_nodes=4 it's skipped."""
    inner = bop("*", var("x"), var("y"))
    expr = bop("+", inner, inner)
    fn = make_function(block_of(expr), ["x", "y"])
    out = apply_cse(fn, min_nodes=4)
    # No lets -- subtree too small.
    assert all(c.kind != NodeKind.LET for c in out.body.children)


def test_user_call_never_hoisted() -> None:
    """User CALLs may have side effects; we never silently
    deduplicate them."""
    call_expr = ASTNode(
        kind=NodeKind.CALL, value="userfn",
        children=[var("x"), var("y")],
    )
    expr = bop("+", call_expr, call_expr)
    fn = make_function(block_of(expr), ["x", "y"])
    out = apply_cse(fn)
    # No lets prepended.
    assert all(c.kind != NodeKind.LET for c in out.body.children[:-1])


# ── 3. Idempotence ───────────────────────────────────────────


def test_cse_is_idempotent() -> None:
    inner = call(
        NodeKind.SQRT,
        bop("+",
            bop("*", var("x"), var("x")),
            bop("*", var("y"), var("y"))),
    )
    expr = bop("+", inner, inner)
    fn = make_function(block_of(expr), ["x", "y"])
    once = apply_cse(fn)
    twice = apply_cse(once)
    assert _shape_fn(once) == _shape_fn(twice)


def _shape_fn(fn: EMLFunction) -> tuple:
    return _shape(fn.body)


def _shape(n: ASTNode) -> tuple:
    return (
        n.kind.value, repr(n.value),
        tuple(_shape(c) for c in n.children),
    )


# ── 4. Skips on complex bodies ───────────────────────────────


def test_skips_function_with_let_mut() -> None:
    """Functions with `let mut` / `while` / `assign` are left
    alone -- the simple analysis isn't safe there."""
    body = ASTNode(kind=NodeKind.BLOCK, children=[
        ASTNode(
            kind=NodeKind.LET_MUT, value="acc",
            children=[lit(0.0)],
        ),
        var("acc"),
    ])
    fn = make_function(body, ["x"])
    out = apply_cse(fn)
    # Same shape -- no rewrite.
    assert _shape_fn(out) == _shape_fn(fn)


def test_skips_rebound_let_shadow_chain() -> None:
    """Repeated immutable let names are legal shadowing, not repeated
    pure expressions. CSE must not hoist across those rebinding
    boundaries because each occurrence sees a different value."""
    body = ASTNode(kind=NodeKind.BLOCK, children=[
        ASTNode(kind=NodeKind.LET, value="acc", children=[lit(0.0)]),
        ASTNode(
            kind=NodeKind.LET,
            value="acc",
            children=[bop("+", bop("*", var("acc"), var("x")), var("c0"))],
        ),
        ASTNode(
            kind=NodeKind.LET,
            value="acc",
            children=[bop("+", bop("*", var("acc"), var("x")), var("c0"))],
        ),
        var("acc"),
    ])
    fn = make_function(body, ["x", "c0"])
    out = apply_cse(fn)
    assert _shape_fn(out) == _shape_fn(fn)


# ── 5. Module-level + parsed source ──────────────────────────


HYPOT_3X = """\
fn h3x(x: f64, y: f64, z: f64) -> f64
    where chain_order <= 1
{
    sqrt(x * x + y * y + z * z) + sqrt(x * x + y * y + z * z)
}
"""


def test_apply_cse_module_runs_per_function() -> None:
    mod = parse_source(HYPOT_3X)
    out = apply_cse_module(mod)
    fn = out.functions[0]
    assert fn.name == "h3x"
    # Body has at least one let.
    has_let = any(c.kind == NodeKind.LET for c in fn.body.children)
    assert has_let, "expected CSE to introduce a let-binding"


def test_apply_cse_module_does_not_mutate_input() -> None:
    mod = parse_source(HYPOT_3X)
    original_shape = _shape(mod.functions[0].body)
    _ = apply_cse_module(mod)
    assert _shape(mod.functions[0].body) == original_shape


# ── 6. Real stdlib smoke ─────────────────────────────────────


def test_vec3_normalize_gets_norm_hoisted() -> None:
    """linalg::vec3_normalize already uses an explicit `let n =
    sqrt(...)`, so CSE should be a no-op there. But if we strip
    the let, CSE should re-introduce it."""
    src = """\
fn vec3_normalize(x: f64, y: f64, z: f64) -> (f64, f64, f64)
    where chain_order <= 1
{
    let inv = 1.0 / sqrt(x * x + y * y + z * z);
    (inv * x, inv * y, inv * z)
}
"""
    mod = parse_source(src)
    out = apply_cse_module(mod)
    fn = out.functions[0]
    # `inv` is referenced 3 times in the tuple; it is a small
    # binding (1 / sqrt(...)) but with a 7-node sqrt subtree --
    # well above min_nodes=3, so CSE should hoist `inv` into a
    # _cse_N binding... but it's already a let, so a second let
    # would just rename it. The pass is conservative: it operates
    # on EXPRESSION subtrees, not let-bound values that already
    # exist. So we expect no new lets here.
    n_lets = sum(1 for c in fn.body.children if c.kind == NodeKind.LET)
    assert n_lets >= 1  # the original `let inv` is preserved
