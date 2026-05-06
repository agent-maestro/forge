"""Phase C: Auto-splicer for requires/ensures -> refinement type annotations.

The auto-splicer is gated behind the ``--strict-refinements`` CLI flag
(default OFF). With the flag OFF, this module is a no-op and behavior is
byte-identical to pre-Phase-C.

With the flag ON (``strict_mode=True``):
  - Single-variable ``requires (pred)`` clauses where ``pred`` only references
    one function parameter are folded into that parameter's refinement.
  - Single-variable ``ensures (pred)`` clauses where ``pred`` only references
    `result` are folded into the function's return refinement.
  - Multi-variable clauses (referencing more than one parameter) stay as-is.
  - An ``explain_notes`` list is populated on the function (Phase C's
    annotation for ``--explain`` output).

No SMT solver is used. Only syntactic analysis is performed.

Design note: The splicer modifies the AST in-place (the module is the
same object; EMLFunction fields are updated). The modifications are:
  - ``fn.requires`` list items are removed when spliced.
  - ``fn.ensures`` list items are removed when spliced.
  - ``param.refinement`` is set (or extended) with the spliced predicate.
  - ``fn.return_refinement`` is set with the spliced ensures predicate.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
    Refinement,
)


# ── Public API ────────────────────────────────────────────────────────


def auto_splice_module(mod: EMLModule, *, strict_mode: bool) -> EMLModule:
    """Walk the module and splice single-variable requires/ensures into refinements.

    Parameters
    ----------
    mod : EMLModule
        The module to process (modified in-place).
    strict_mode : bool
        When False (default), this function is a no-op.
        When True, single-variable clauses are spliced.

    Returns
    -------
    EMLModule
        The same module, modified in-place when strict_mode is True.
    """
    if not strict_mode:
        return mod

    for fn in mod.functions:
        _splice_function(fn)

    return mod


def _splice_function(fn: EMLFunction) -> None:
    """Splice single-variable requires/ensures clauses for one function."""
    param_names = {p.name for p in fn.params}

    # Process requires clauses
    remaining_requires: list[ASTNode] = []
    for pred_node in fn.requires:
        free_vars = _free_vars(pred_node)
        # Single-variable: only references one param (possibly after removing consts)
        param_refs = free_vars & param_names
        result_refs = free_vars & {"result"}
        other_refs = free_vars - param_names - {"result"}

        if len(param_refs) == 1 and not result_refs:
            # Single-param reference: splice into that param's refinement
            (param_name,) = param_refs
            param = next(p for p in fn.params if p.name == param_name)
            new_refinement = _make_or_extend_refinement(
                existing=param.refinement,
                binder=param_name,
                pred_node=pred_node,
                param_name_in_pred=param_name,
            )
            # Splice: update param refinement; don't add to remaining_requires
            param.refinement = new_refinement
            # Record splice note (Phase C --explain annotation)
            _record_splice_note(fn, f"requires ({_pred_text(pred_node)}) -> {param_name} refinement")
        else:
            # Multi-variable or non-param-only: keep as-is
            remaining_requires.append(pred_node)

    fn.requires = remaining_requires

    # Process ensures clauses
    remaining_ensures: list[ASTNode] = []
    for pred_node in fn.ensures:
        free_vars = _free_vars(pred_node)
        result_refs = free_vars & {"result"}
        param_refs = free_vars & param_names

        if result_refs and not param_refs:
            # Single `result` reference: splice into return refinement
            new_refinement = _make_or_extend_refinement(
                existing=fn.return_refinement,
                binder="result",
                pred_node=pred_node,
                param_name_in_pred="result",
            )
            fn.return_refinement = new_refinement
            _record_splice_note(fn, f"ensures ({_pred_text(pred_node)}) -> return refinement")
        else:
            remaining_ensures.append(pred_node)

    fn.ensures = remaining_ensures


def _make_or_extend_refinement(
    existing: "Refinement | None",
    binder: str,
    pred_node: ASTNode,
    param_name_in_pred: str,
) -> "Refinement":
    """Create a new Refinement or extend an existing one with an additional predicate.

    When the param name used in the predicate differs from the binder,
    we substitute the binder for the param name in the predicate.
    """
    # Substitute param_name_in_pred -> binder in pred_node
    substituted = _substitute_var(pred_node, param_name_in_pred, binder)

    if existing is None:
        return Refinement(
            binder=binder,
            predicate=substituted,
            line=pred_node.line,
            col=pred_node.col,
        )
    # Extend with conjunction
    combined = ASTNode(
        kind=NodeKind.BINOP,
        value="&&",
        children=[existing.predicate, substituted],
        line=pred_node.line,
        col=pred_node.col,
    )
    return Refinement(
        binder=existing.binder,
        predicate=combined,
        line=existing.line,
        col=existing.col,
    )


def _substitute_var(node: ASTNode, old_name: str, new_name: str) -> ASTNode:
    """Substitute all VAR nodes with name `old_name` -> `new_name`.

    Returns a new ASTNode tree (immutable-style replacement).
    """
    if node.kind == NodeKind.VAR and node.value == old_name:
        return ASTNode(
            kind=NodeKind.VAR, value=new_name,
            line=node.line, col=node.col,
        )
    new_children = [_substitute_var(c, old_name, new_name) for c in node.children]
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )


def _free_vars(node: ASTNode) -> set[str]:
    """Collect all VAR names referenced in a predicate node."""
    result: set[str] = set()
    _collect_vars(node, result)
    return result


def _collect_vars(node: ASTNode, acc: set[str]) -> None:
    """Recursively collect VAR names."""
    if node.kind == NodeKind.VAR:
        acc.add(node.value)
    for child in node.children:
        _collect_vars(child, acc)


def _pred_text(node: ASTNode) -> str:
    """Produce a compact text representation of a predicate node."""
    if node.kind == NodeKind.LITERAL:
        return repr(node.value)
    if node.kind == NodeKind.VAR:
        return node.value
    if node.kind == NodeKind.BINOP:
        left = _pred_text(node.children[0])
        right = _pred_text(node.children[1])
        return f"{left} {node.value} {right}"
    if node.kind == NodeKind.UNARYOP:
        return f"{node.value}{_pred_text(node.children[0])}"
    if node.kind == NodeKind.ABS:
        inner = _pred_text(node.children[0]) if node.children else "?"
        return f"abs({inner})"
    if node.kind == NodeKind.CALL:
        args = ", ".join(_pred_text(c) for c in node.children)
        return f"{node.value}({args})"
    return "..."


def _record_splice_note(fn: EMLFunction, note: str) -> None:
    """Record a splice note on the function for --explain output."""
    if not hasattr(fn, "_splice_notes"):
        fn._splice_notes = []  # type: ignore[attr-defined]
    fn._splice_notes.append(note)  # type: ignore[attr-defined]
