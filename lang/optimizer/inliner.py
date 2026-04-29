"""User-function inliner pass.

Replaces every `CALL fn_name(arg1, arg2, ...)` node whose callee is
a same-module function with a single-expression body, by the
callee's body with parameters substituted.

Why we need it:

  - The SymPy lambdify path in `tools/equivalence/python_runner.py`
    can't evaluate user CALLs (they're rendered as opaque sp.Function).
    Inlining lets the equivalence harness check `motor_foc.eml`'s
    `pi_step` after we point it at `stdlib::control::pid`.
  - Downstream optimizer passes (constant_folding, CSE) can fire
    on inlined sub-trees; e.g. `pid(e, i, 0.0, Kp, Ki, 0.0)`
    becomes `Kp*e + Ki*i + 0.0*0.0` -> folds to `Kp*e + Ki*i`.

What we DON'T inline:

  - Functions with `let` bindings in the body. Hoisting those into
    the caller is non-trivial because of name collisions; the
    next pass can take that on if/when it becomes load-bearing.
  - Functions with `let mut` / `while` / `assign` (complex bodies).
  - Functions whose body returns a tuple. Tuple destructuring at
    the call site isn't supported by the current AST.
  - Builtin CALLs (EXP / LN / SIN / ...) -- those have dedicated
    NodeKinds and aren't user functions.
  - Recursive calls -- the inliner refuses to inline a function
    into itself (direct recursion). Indirect recursion is detected
    via a per-call "currently inlining" set.

Idempotence: a second pass finds no eligible CALLs because every
inlinable one was already substituted.
"""

from __future__ import annotations

from copy import deepcopy

from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
)


def inline_calls(
    mod: EMLModule,
    *,
    max_iterations: int = 4,
) -> EMLModule:
    """Return a new module with every inline-eligible CALL node
    inside every function body replaced by the substituted callee
    body.

    `max_iterations` bounds how many fixed-point passes we make,
    so a chain `A -> B -> C` of inlinable wrappers all unfolds in
    a single optimize_module() invocation."""
    out = deepcopy(mod)
    fn_table: dict[str, EMLFunction] = {f.name: f for f in out.functions}

    for _ in range(max_iterations):
        changed_any = False
        for fn in out.functions:
            if fn.body is None:
                continue
            new_body, changed = _inline_in_node(
                fn.body, fn_table,
                currently_inlining={fn.name},
            )
            if changed:
                fn.body = new_body
                changed_any = True
        if not changed_any:
            break

    return out


# ── Implementation ──────────────────────────────────────────


def _inline_in_node(
    node: ASTNode,
    fn_table: dict[str, EMLFunction],
    currently_inlining: set[str],
) -> tuple[ASTNode, bool]:
    """Recursively walk `node`, inlining eligible CALLs. Returns
    (possibly-replaced node, whether any change was made)."""
    changed = False
    new_children: list[ASTNode] = []
    for child in node.children:
        new_child, child_changed = _inline_in_node(
            child, fn_table, currently_inlining,
        )
        new_children.append(new_child)
        changed = changed or child_changed
    node.children = new_children

    if node.kind != NodeKind.CALL:
        return node, changed

    callee_name = node.value
    callee = fn_table.get(callee_name)
    if callee is None:
        return node, changed

    if callee_name in currently_inlining:
        # Skip recursive call to avoid unbounded inlining.
        return node, changed

    expr = _eligible_body_expression(callee)
    if expr is None:
        return node, changed

    if len(node.children) != len(callee.params):
        # Arity mismatch: leave the call alone, it'll surface as
        # an error elsewhere (the C/Rust backend will reject it).
        return node, changed

    # Build the substitution map: param_name -> caller's argument.
    subs: dict[str, ASTNode] = {
        p.name: arg
        for p, arg in zip(callee.params, node.children)
    }
    inlined = _substitute_vars(deepcopy(expr), subs)

    # The inlined expression itself may contain further CALLs we
    # could expand. Recurse again with the callee added to the
    # inlining set so we don't loop on mutual recursion.
    inlined, _ = _inline_in_node(
        inlined, fn_table,
        currently_inlining | {callee_name},
    )
    return inlined, True


def _eligible_body_expression(fn: EMLFunction) -> ASTNode | None:
    """Return the single-expression body of `fn` if it qualifies
    for inlining. None if the body has lets / mutation / tuple
    return / complex flow."""
    body = fn.body
    if body is None or body.kind != NodeKind.BLOCK:
        return None
    if fn.return_tuple_types:
        return None
    # Body must consist of exactly one statement that is the final
    # expression (no let bindings preceding it, no expr-statements).
    if len(body.children) != 1:
        return None
    stmt = body.children[0]
    if stmt.kind in (
        NodeKind.LET, NodeKind.LET_MUT, NodeKind.WHILE,
        NodeKind.ASSIGN, NodeKind.EXPR_STMT, NodeKind.BLOCK,
    ):
        return None
    # The lone child IS the return expression.
    return stmt


def _substitute_vars(
    node: ASTNode, subs: dict[str, ASTNode],
) -> ASTNode:
    """Walk `node` replacing every VAR whose name is in `subs`
    with a deep copy of the substitution. Mutates `node`."""
    if node.kind == NodeKind.VAR and node.value in subs:
        # Replace this node entirely.
        replacement = deepcopy(subs[node.value])
        node.kind = replacement.kind
        node.value = replacement.value
        node.children = replacement.children
        node.type_annotation = replacement.type_annotation
        node.chain_constraint = replacement.chain_constraint
        return node
    node.children = [_substitute_vars(c, subs) for c in node.children]
    return node
