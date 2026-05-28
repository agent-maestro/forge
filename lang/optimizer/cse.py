"""Common sub-expression elimination.

Walks each function body looking for non-trivial sub-expression
trees that appear more than once, and hoists them into a
`let _cse_<n> = <expr>;` binding inserted at the top of the body.
Each occurrence is then replaced with a reference to the binding.

What counts as "non-trivial":

  - More than `min_nodes` AST nodes (default 3) -- a single
    multiplication is not worth hoisting because the let-binding
    adds its own runtime cost.
  - Not already a LITERAL or VAR (atomic).
  - Not a CALL into a user function -- those may have side
    effects, so we never deduplicate them silently.

CSE runs AFTER constant folding (and IS run by `optimize_module`
in that order) so we don't hoist trees that the folder will
collapse to a literal.

Idempotence: `apply_cse(apply_cse(x))` produces the same shape as
`apply_cse(x)` -- a second pass finds no new candidates because
each hoisted expr appears exactly once at the rewrite point.
"""

from __future__ import annotations

from copy import deepcopy

from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
)


# Names we'll never hoist past -- side effects + control flow.
_NON_HOISTABLE_KINDS = frozenset({
    NodeKind.LITERAL,
    NodeKind.VAR,
    NodeKind.CALL,
    NodeKind.BLOCK,
    NodeKind.LET,
    NodeKind.LET_MUT,
    NodeKind.ASSIGN,
    NodeKind.WHILE,
    NodeKind.EXPR_STMT,
})


def apply_cse(
    func: EMLFunction,
    *,
    min_nodes: int = 3,
    min_occurrences: int = 2,
) -> EMLFunction:
    """Return a copy of `func` with repeated sub-expressions
    hoisted into `let _cse_N = ...` bindings at the top of the
    body. Only operates on functions whose body is a BLOCK and
    whose statements contain no mut / while / assignment (we
    leave those alone -- the analysis cost isn't worth it for
    today's small body sizes)."""
    if func.body is None or func.body.kind != NodeKind.BLOCK:
        return func
    if _has_complex_control(func.body):
        return func

    new_func = deepcopy(func)
    body = new_func.body
    counts = _count_subtrees(body, min_nodes=min_nodes)

    # Sort candidates by tree size descending so the largest
    # hoists run first; then by occurrence count descending.
    candidates = sorted(
        (
            (fp, occ, size)
            for fp, (occ, size) in counts.items()
            if occ >= min_occurrences and size >= min_nodes
        ),
        key=lambda t: (-t[2], -t[1]),
    )

    next_idx = 0
    new_lets: list[ASTNode] = []

    for fp, _occ, _size in candidates:
        # Re-count using the current (possibly partly-rewritten)
        # body -- earlier rewrites may have erased this candidate.
        live = _count_subtrees(body, min_nodes=min_nodes).get(fp)
        if live is None or live[0] < min_occurrences:
            continue
        name = f"_cse_{next_idx}"
        next_idx += 1
        # The "exemplar" tree to hoist: any matching subtree.
        exemplar = _find_first_with_fingerprint(body, fp)
        if exemplar is None:
            continue
        hoisted = deepcopy(exemplar)

        # Build the let binding.
        let_node = ASTNode(
            kind=NodeKind.LET, value=name,
            children=[hoisted],
        )
        new_lets.append(let_node)

        # Rewrite every matching occurrence in the body to a VAR.
        _rewrite_to_var(body, fp, name)

    if new_lets:
        # Insert each new let immediately before the first statement
        # in the body that references it. Prepending unconditionally
        # would be wrong: a hoisted expression may reference a name
        # bound by a LATER let in the original body, e.g. for
        #
        #     let f = pow(x, k);
        #     let a = alpha / f;
        #     let b = alpha / f;
        #
        # CSE would hoist `alpha / f`, but `alpha / f` references the
        # body-local `f` and so the new let must come AFTER `let f`.
        #
        # First-use insertion is correct because the hoisted exemplar
        # was originally built from a sub-tree that appeared at or
        # after the position where its dependencies were defined --
        # so its first remaining use (a VAR ref to the new name) is
        # also at or after those dependencies.
        body.children = _splice_lets_before_first_use(body.children, new_lets)

    return new_func


def _splice_lets_before_first_use(
    body_children: list[ASTNode],
    new_lets: list[ASTNode],
) -> list[ASTNode]:
    """Return a new children list with each `new_lets` entry inserted
    immediately before the first existing statement that references
    its bound name. Lets whose name has no occurrence (defensive
    fallback) are prepended."""
    pending: dict[str, ASTNode] = {let.value: let for let in new_lets}
    out: list[ASTNode] = []
    for stmt in body_children:
        used_here = [
            name for name in list(pending)
            if _references_var(stmt, name)
        ]
        for name in used_here:
            out.append(pending.pop(name))
        out.append(stmt)
    # Fallback: any remaining (unused) lets land at the front so the
    # rewrite is structurally identical to the pre-fix shape.
    if pending:
        out = list(pending.values()) + out
    return out


def _references_var(node: ASTNode, name: str) -> bool:
    if node.kind == NodeKind.VAR and node.value == name:
        return True
    return any(_references_var(c, name) for c in node.children)


def apply_cse_module(mod: EMLModule, **kwargs) -> EMLModule:
    """Return a new EMLModule with CSE applied to every function."""
    out = deepcopy(mod)
    out.functions = [apply_cse(fn, **kwargs) for fn in mod.functions]
    return out


# ── Internal helpers ──────────────────────────────────────────


def _has_complex_control(block: ASTNode) -> bool:
    bad = {NodeKind.LET_MUT, NodeKind.WHILE, NodeKind.ASSIGN}
    seen_let_names: set[str] = set()
    for stmt in block.children:
        if stmt.kind in bad:
            return True
        if stmt.kind == NodeKind.LET:
            if stmt.value in seen_let_names:
                return True
            seen_let_names.add(str(stmt.value))
    return False


def _fingerprint(node: ASTNode) -> tuple:
    """Structural fingerprint of an AST sub-tree. Two trees with
    the same fingerprint are semantically interchangeable -- they
    have identical kind, value, and children. Source location is
    deliberately ignored."""
    return (
        node.kind.value,
        repr(node.value),
        tuple(_fingerprint(c) for c in node.children),
    )


def _node_size(node: ASTNode) -> int:
    return 1 + sum(_node_size(c) for c in node.children)


def _count_subtrees(
    node: ASTNode,
    *,
    min_nodes: int,
) -> dict[tuple, tuple[int, int]]:
    """Return {fingerprint: (occurrence_count, size)} over every
    sub-tree of `node` whose root is hoistable and whose size
    is >= min_nodes."""
    counts: dict[tuple, tuple[int, int]] = {}

    def visit(n: ASTNode) -> None:
        if n.kind not in _NON_HOISTABLE_KINDS:
            size = _node_size(n)
            if size >= min_nodes:
                fp = _fingerprint(n)
                occ_size = counts.get(fp)
                if occ_size is None:
                    counts[fp] = (1, size)
                else:
                    counts[fp] = (occ_size[0] + 1, occ_size[1])
        for c in n.children:
            visit(c)

    visit(node)
    return counts


def _find_first_with_fingerprint(
    node: ASTNode, fp: tuple,
) -> ASTNode | None:
    """DFS for the first sub-tree whose fingerprint matches `fp`."""
    if (
        node.kind not in _NON_HOISTABLE_KINDS
        and _fingerprint(node) == fp
    ):
        return node
    for c in node.children:
        found = _find_first_with_fingerprint(c, fp)
        if found is not None:
            return found
    return None


def _rewrite_to_var(node: ASTNode, fp: tuple, var_name: str) -> None:
    """Mutate `node`'s children: any child whose fingerprint matches
    `fp` is replaced by VAR(var_name). Recurses into non-replaced
    children."""
    for i, child in enumerate(node.children):
        if (
            child.kind not in _NON_HOISTABLE_KINDS
            and _fingerprint(child) == fp
        ):
            node.children[i] = ASTNode(
                kind=NodeKind.VAR, value=var_name,
            )
        else:
            _rewrite_to_var(child, fp, var_name)
