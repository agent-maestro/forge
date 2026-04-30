"""ML-routing optimizer pass — opt-in, off by default.

Recognizes the canonical activation patterns in inlined ASTs and
rewrites them to direct calls into libmonogate's overflow-safe
routing variants (Patent #01).

Patterns recognized
-------------------

  1.0 / (1.0 + exp(-x))     ->  mg_sigmoid_route(x)
  ln(1.0 + exp(x))          ->  mg_softplus_route(x)

The CALL nodes produced here are NOT user functions; they target
runtime symbols exposed by libmonogate (C) / monogate-sys (Rust).
Backends that compile against either runtime resolve them
naturally. Backends that don't (Python, LLVM, WASM) should NOT
enable this pass — call `optimize_module(mod)` without the
`ml_routing=True` flag.

Gated on `fn.profile["fp16_drift_risk"] == "HIGH"`. Functions
whose drift profile is already LOW skip the rewrite — the naive
form is fast and accurate enough.

Why opt-in
----------

The runtime symbols are NOT in the language's NodeKind enum:
they're emitted as opaque CALL nodes that the C / Rust backends
recognize by name. That keeps the AST type system unchanged.
Other backends would emit a `mg_sigmoid_route` *user-function*
call that resolves to nothing — hence the opt-in gate.
"""

from __future__ import annotations

from copy import deepcopy

from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind


# Runtime symbol names produced by this pass. The C and Rust
# backends understand these as direct calls into libmonogate /
# monogate-sys; Python / LLVM / WASM do NOT.
RUNTIME_SYMBOLS: frozenset[str] = frozenset({
    "mg_sigmoid_route",
    "mg_softplus_route",
})


def route_ml_activations(fn: EMLFunction) -> EMLFunction:
    """Rewrite recognized activation patterns to runtime CALLs.

    Returns a new function. Input is not mutated. No-op when:
      - drift risk is not HIGH
      - body is None or already lowered to runtime calls
    """
    drift = (fn.profile or {}).get("fp16_drift_risk", "LOW")
    if drift != "HIGH" or fn.body is None:
        return fn

    out = deepcopy(fn)
    out.body = _rewrite_node(out.body)
    return out


def route_ml_activations_module(mod: EMLModule) -> EMLModule:
    """Apply `route_ml_activations` to every function in the module."""
    out = deepcopy(mod)
    out.functions = [route_ml_activations(fn) for fn in out.functions]
    return out


# ── Pattern matchers ──────────────────────────────────────────────


def _is_one(node: ASTNode) -> bool:
    return (
        node.kind == NodeKind.LITERAL
        and isinstance(node.value, (int, float))
        and float(node.value) == 1.0
    )


def _is_neg(node: ASTNode) -> ASTNode | None:
    """Return the inner expr if `node` is `-x`, else None."""
    if node.kind == NodeKind.UNARYOP and node.value == "-":
        return node.children[0]
    return None


def _try_match_sigmoid(node: ASTNode) -> ASTNode | None:
    """Recognize `1.0 / (1.0 + exp(-x))`. Returns the `x` subtree on
    match, else None."""
    if node.kind != NodeKind.BINOP or node.value != "/":
        return None
    if len(node.children) != 2:
        return None
    num, den = node.children
    if not _is_one(num):
        return None
    # den should be `1.0 + exp(-x)`
    if den.kind != NodeKind.BINOP or den.value != "+":
        return None
    if len(den.children) != 2:
        return None
    a, b = den.children
    # Pattern is symmetric (1+e or e+1) but the typical form is `1 + exp`.
    one_side, exp_side = (a, b) if _is_one(a) else (b, a)
    if not _is_one(one_side):
        return None
    if exp_side.kind != NodeKind.EXP:
        return None
    if len(exp_side.children) != 1:
        return None
    inner = _is_neg(exp_side.children[0])
    if inner is None:
        return None
    return inner


def _try_match_softplus(node: ASTNode) -> ASTNode | None:
    """Recognize `ln(1.0 + exp(x))`. Returns `x` on match, else None."""
    if node.kind != NodeKind.LN:
        return None
    if len(node.children) != 1:
        return None
    add = node.children[0]
    if add.kind != NodeKind.BINOP or add.value != "+":
        return None
    if len(add.children) != 2:
        return None
    a, b = add.children
    one_side, exp_side = (a, b) if _is_one(a) else (b, a)
    if not _is_one(one_side):
        return None
    if exp_side.kind != NodeKind.EXP:
        return None
    if len(exp_side.children) != 1:
        return None
    return exp_side.children[0]


# ── Recursive rewrite ─────────────────────────────────────────────


def _rewrite_node(node: ASTNode) -> ASTNode:
    """Bottom-up rewrite: try each matcher; if none matches, recurse
    into children."""
    # Try patterns first (against the existing children).
    sig_arg = _try_match_sigmoid(node)
    if sig_arg is not None:
        return _make_call(node, "mg_sigmoid_route", [_rewrite_node(sig_arg)])

    sp_arg = _try_match_softplus(node)
    if sp_arg is not None:
        return _make_call(node, "mg_softplus_route", [_rewrite_node(sp_arg)])

    # No match -- recurse into children.
    new_children = [_rewrite_node(c) for c in node.children]
    if new_children == node.children:
        return node
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )


def _make_call(src: ASTNode, name: str, args: list[ASTNode]) -> ASTNode:
    """Build a CALL node carrying the source location of the matched
    expression (so error messages still point at user code)."""
    return ASTNode(
        kind=NodeKind.CALL,
        value=name,
        children=args,
        line=src.line,
        col=src.col,
    )
