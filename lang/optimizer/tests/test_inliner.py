"""Tests for the user-call inliner pass."""

from __future__ import annotations

from lang.optimizer.inliner import inline_calls
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


def call(name: str, *args: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.CALL, value=name, children=list(args))


def block(*children: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BLOCK, children=list(children))


def make_fn(
    name: str, params: list[str], body: ASTNode,
    *, return_tuple: list[str] | None = None,
) -> EMLFunction:
    return EMLFunction(
        name=name,
        params=[Param(name=p, type_name="f64") for p in params],
        return_type="" if return_tuple else "f64",
        return_tuple_types=return_tuple or [],
        body=body,
    )


def _shape(n: ASTNode) -> tuple:
    return (
        n.kind.value, repr(n.value),
        tuple(_shape(c) for c in n.children),
    )


# ── 1. Eligible single-expression callee gets inlined ─────────


def test_inline_simple_callee() -> None:
    """add(x, y) = x + y, called as add(p, q) -> p + q after
    inlining."""
    add_fn = make_fn("add", ["x", "y"], block(bop("+", var("x"), var("y"))))
    caller = make_fn(
        "caller", ["p", "q"],
        block(call("add", var("p"), var("q"))),
    )
    mod = EMLModule(name="t", functions=[add_fn, caller])
    out = inline_calls(mod)
    new_caller = next(f for f in out.functions if f.name == "caller")
    body_expr = new_caller.body.children[0]
    # Body is now `p + q`, no CALL node.
    assert body_expr.kind == NodeKind.BINOP
    assert body_expr.value == "+"
    assert body_expr.children[0].value == "p"
    assert body_expr.children[1].value == "q"


def test_inline_substitutes_complex_args() -> None:
    """add(2*p, p+q) -> (2*p) + (p+q) after inlining."""
    add_fn = make_fn("add", ["x", "y"], block(bop("+", var("x"), var("y"))))
    caller = make_fn(
        "caller", ["p", "q"],
        block(call(
            "add",
            bop("*", lit(2.0), var("p")),
            bop("+", var("p"), var("q")),
        )),
    )
    mod = EMLModule(name="t", functions=[add_fn, caller])
    out = inline_calls(mod)
    body = out.functions[1].body.children[0]
    # Top-level: BINOP +. Left: BINOP *. Right: BINOP +.
    assert body.kind == NodeKind.BINOP and body.value == "+"
    assert body.children[0].value == "*"
    assert body.children[1].value == "+"


# ── 2. Ineligible callees are left alone ──────────────────────


def test_callee_with_let_binding_not_inlined() -> None:
    """Body has a LET stmt, so the inliner refuses to substitute
    (no scope handling)."""
    helper = EMLFunction(
        name="helper", params=[Param("x", "f64")], return_type="f64",
        body=block(
            ASTNode(kind=NodeKind.LET, value="t",
                    children=[bop("*", var("x"), var("x"))]),
            bop("+", var("t"), lit(1.0)),
        ),
    )
    caller = make_fn(
        "caller", ["p"],
        block(call("helper", var("p"))),
    )
    mod = EMLModule(name="t", functions=[helper, caller])
    out = inline_calls(mod)
    body = out.functions[1].body.children[0]
    # The CALL survives.
    assert body.kind == NodeKind.CALL
    assert body.value == "helper"


def test_tuple_returning_callee_not_inlined() -> None:
    pair = make_fn(
        "pair", ["x"],
        block(ASTNode(
            kind=NodeKind.TUPLE,
            children=[var("x"), bop("+", var("x"), lit(1.0))],
        )),
        return_tuple=["f64", "f64"],
    )
    caller = make_fn(
        "caller", ["p"],
        block(call("pair", var("p"))),
    )
    mod = EMLModule(name="t", functions=[pair, caller])
    out = inline_calls(mod)
    body = out.functions[1].body.children[0]
    assert body.kind == NodeKind.CALL
    assert body.value == "pair"


def test_unknown_callee_left_alone() -> None:
    """If a CALL refers to a function not in the module, leave it
    alone -- the backend will (correctly) reject it later."""
    caller = make_fn(
        "caller", ["p"],
        block(call("missing_function", var("p"))),
    )
    mod = EMLModule(name="t", functions=[caller])
    out = inline_calls(mod)
    body = out.functions[0].body.children[0]
    assert body.kind == NodeKind.CALL


def test_recursive_call_not_inlined() -> None:
    """A function calling itself must NOT be inlined (would loop)."""
    rec = make_fn(
        "rec", ["x"],
        block(bop("+", var("x"), call("rec", var("x")))),
    )
    mod = EMLModule(name="t", functions=[rec])
    # Should not infinite-loop.
    out = inline_calls(mod, max_iterations=4)
    body = out.functions[0].body.children[0]
    # The CALL survives.
    assert _has_kind(body, NodeKind.CALL)


# ── 3. Chain of inlinable wrappers unfolds in one call ────────


def test_chain_a_calls_b_calls_c_unfolds() -> None:
    """A(p) -> B(p) -> C(p) -> p+1 -- after inline_calls, A's body
    is just `p + 1`."""
    c_fn = make_fn("c", ["x"], block(bop("+", var("x"), lit(1.0))))
    b_fn = make_fn("b", ["y"], block(call("c", var("y"))))
    a_fn = make_fn("a", ["z"], block(call("b", var("z"))))
    mod = EMLModule(name="t", functions=[c_fn, b_fn, a_fn])
    out = inline_calls(mod, max_iterations=5)
    a_body = out.functions[2].body.children[0]
    # Top-level expression is BINOP + with z + 1.0
    assert a_body.kind == NodeKind.BINOP
    assert a_body.value == "+"
    assert a_body.children[0].value == "z"
    assert a_body.children[1].value == 1.0


# ── 4. Idempotence + non-mutation ────────────────────────────


def test_inliner_is_idempotent() -> None:
    add_fn = make_fn("add", ["x", "y"], block(bop("+", var("x"), var("y"))))
    caller = make_fn(
        "caller", ["p", "q"],
        block(call("add", var("p"), var("q"))),
    )
    mod = EMLModule(name="t", functions=[add_fn, caller])
    once = inline_calls(mod)
    twice = inline_calls(once)
    a_body = once.functions[1].body
    b_body = twice.functions[1].body
    assert _shape(a_body) == _shape(b_body)


def test_inliner_does_not_mutate_input() -> None:
    add_fn = make_fn("add", ["x", "y"], block(bop("+", var("x"), var("y"))))
    caller = make_fn(
        "caller", ["p", "q"],
        block(call("add", var("p"), var("q"))),
    )
    mod = EMLModule(name="t", functions=[add_fn, caller])
    before_caller = _shape(caller.body)
    _ = inline_calls(mod)
    assert _shape(mod.functions[1].body) == before_caller


# ── 5. Parsed source + import roundtrip ──────────────────────


def test_inline_after_stdlib_import() -> None:
    """Real-world flow: `use stdlib::math;` brings in `lerp`, then
    a local function calling `lerp(a, b, 0.5)` gets inlined."""
    src = (
        "use stdlib::math;\n"
        "fn midpoint(a: f64, b: f64) -> f64 { lerp(a, b, 0.5) }\n"
    )
    mod = parse_source(src, resolve=True)
    out = inline_calls(mod)
    midpoint = next(f for f in out.functions if f.name == "midpoint")
    body = midpoint.body.children[0]
    # No CALL to lerp; body is the inlined `a + 0.5 * (b - a)`.
    assert not _has_kind(body, NodeKind.CALL)


# ── Helpers ──────────────────────────────────────────────────


def _has_kind(node: ASTNode, kind: NodeKind) -> bool:
    if node.kind == kind:
        return True
    return any(_has_kind(c, kind) for c in node.children)
