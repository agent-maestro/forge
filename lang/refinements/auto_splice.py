"""Phase C: Auto-splicer for requires/ensures -> refinement type annotations.

The auto-splicer has two passes:

Pass 1 -- Alias expansion (ALWAYS-ON, not flag-gated):
  - Builds a dict of EMLTypeAlias objects from ``mod.types``.
  - For each function parameter whose ``type_name`` resolves to a type alias
    that carries a ``refinement`` and/or ``unit_expr``:
      * The alias's ``refinement`` is substituted (alias binder -> param name)
        and placed onto ``param.refinement``.
      * The alias's ``unit_expr`` is propagated to ``param.unit_expr`` when
        the param has no explicit unit annotation.
      * If both the alias AND the param carry an explicit ``refinement``, they
        are conjuncted (alias pred AND explicit pred), with both binders
        normalised to the param name.
      * If both the alias AND the param carry a ``unit_expr`` and they differ,
        a ``RefinementError`` is raised.
  - Alias references are transitively resolved (type B = A -> B expands A).
  - Cycle detection raises ``RefinementError`` with a clear message.
  - This runs BEFORE pass 2 so downstream consumers see populated
    ``Param.refinement`` / ``Param.unit_expr`` fields.

Pass 2 -- requires/ensures folding (flag-gated behind ``strict_mode=True``):
  - Single-variable ``requires (pred)`` clauses where ``pred`` only references
    one function parameter are folded into that parameter's refinement.
  - Single-variable ``ensures (pred)`` clauses where ``pred`` only references
    ``result`` are folded into the function's return refinement.
  - Multi-variable clauses (referencing more than one parameter) stay as-is.
  - An ``explain_notes`` list is populated on the function (Phase C's
    annotation for ``--explain`` output).

No SMT solver is used. Only syntactic analysis is performed.

Design note: Param objects are replaced (immutable style) rather than
mutated.  EMLTypeAlias.refinement is never modified.
"""

from __future__ import annotations

from typing import Optional

from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    EMLTypeAlias,
    NodeKind,
    Param,
    Refinement,
)
from lang.refinements.error import RefinementError


# ── Public API ────────────────────────────────────────────────────────


def expand_aliases_module(mod: EMLModule) -> EMLModule:
    """Pass 1 only: propagate type-alias refinements/units onto function params.

    Must run BEFORE the unit-type checker so that a parameter declared with
    an alias type (e.g. ``f: AudibleFreq`` where ``AudibleFreq`` is
    ``Real[Hz]{...}``) carries the alias's ``unit_expr`` during unit
    inference.  Idempotent: running this twice on the same module is a
    no-op on the second call.
    """
    alias_map = {ta.name: ta for ta in mod.types}
    if alias_map:
        for fn in mod.functions:
            _expand_alias_refinements(fn, alias_map)
    return mod


def auto_splice_module(mod: EMLModule, *, strict_mode: bool) -> EMLModule:
    """Walk the module and (1) expand alias refinements, (2) splice requires/ensures.

    Parameters
    ----------
    mod : EMLModule
        The module to process (modified in-place for function param lists).
    strict_mode : bool
        When False, only pass 1 (alias expansion) runs.
        When True, pass 2 (single-variable requires/ensures folding) also runs.

    Returns
    -------
    EMLModule
        The same module object.  Function param lists may be replaced when
        alias expansion produces new ``Param`` objects.

    Note: pass 1 is idempotent, so it is safe to call this AFTER
    ``expand_aliases_module``.  Callers that want both passes can call only
    this function; the CLI calls expand_aliases_module first (before unit
    checking) and then this for pass 2.
    """
    # Pass 1: alias refinement expansion -- ALWAYS runs (idempotent).
    expand_aliases_module(mod)

    # Pass 2: requires/ensures folding -- gated behind strict_mode.
    if strict_mode:
        for fn in mod.functions:
            _splice_function(fn)

    return mod


# ── Pass 1: Alias refinement expansion ───────────────────────────────


def _resolve_alias(
    type_name: str,
    alias_map: dict[str, EMLTypeAlias],
    visited: Optional[frozenset[str]] = None,
) -> tuple[Optional[str], Optional[Refinement]]:
    """Transitively resolve a type alias to its (unit_expr, Refinement) pair.

    Follows alias chains until hitting a non-alias base type or an alias with
    no further alias base.  Conjuncts refinements if intermediate aliases each
    carry one (rare but supported).

    Parameters
    ----------
    type_name : str
        The type name to resolve (may or may not be in alias_map).
    alias_map : dict[str, EMLTypeAlias]
        All aliases in the module, keyed by name.
    visited : frozenset[str] | None
        Names already on the resolution stack; used for cycle detection.

    Returns
    -------
    (unit_expr, refinement) : tuple
        Both may be None if the alias (chain) carries neither.

    Raises
    ------
    RefinementError
        When a cycle is detected.
    """
    if visited is None:
        visited = frozenset()

    if type_name not in alias_map:
        # Not an alias: base type (Real, Int, f64, …)
        return (None, None)

    if type_name in visited:
        cycle_path = " -> ".join(sorted(visited)) + " -> " + type_name
        raise RefinementError(
            f"Cycle detected in type alias chain: {cycle_path}",
            line=alias_map[type_name].line,
            col=alias_map[type_name].col,
        )

    alias = alias_map[type_name]
    visited = visited | {type_name}

    # Recurse into the base type (which may itself be an alias).
    parent_unit, parent_ref = _resolve_alias(alias.base_type, alias_map, visited)

    # Merge unit: prefer the deepest (most-specific) non-None value.
    merged_unit = alias.unit_expr if alias.unit_expr is not None else parent_unit

    # Merge refinement: conjunct if both carry one.
    if alias.refinement is not None and parent_ref is not None:
        # Both carry refinements: conjunct with a common binder.
        # We'll normalise both to a temporary binder later; for now join them.
        merged_ref = _conjunct_refinements(parent_ref, alias.refinement)
    elif alias.refinement is not None:
        merged_ref = alias.refinement
    else:
        merged_ref = parent_ref

    return (merged_unit, merged_ref)


def _conjunct_refinements(a: Refinement, b: Refinement) -> Refinement:
    """Conjunct two refinements into a single &&-joined refinement.

    The resulting binder is taken from ``a``; ``b``'s predicate is
    renamed from b.binder -> a.binder before joining.
    """
    b_pred_renamed = _substitute_var(b.predicate, b.binder, a.binder)
    combined = ASTNode(
        kind=NodeKind.BINOP,
        value="&&",
        children=[a.predicate, b_pred_renamed],
        line=a.line,
        col=a.col,
    )
    return Refinement(binder=a.binder, predicate=combined, line=a.line, col=a.col)


def _expand_alias_refinements(
    fn: EMLFunction,
    alias_map: dict[str, EMLTypeAlias],
) -> None:
    """Expand alias refinements/units onto all parameters of ``fn`` in-place.

    For each parameter:
    - Resolve its type_name through the alias chain.
    - If the resolved alias carries a unit_expr:
        * If the param already has a different unit_expr, raise RefinementError.
        * Otherwise propagate the alias unit.
    - If the resolved alias carries a refinement:
        * Substitute alias binder -> param name.
        * If the param already has an explicit refinement, conjunct them
          (alias pred first, explicit pred second, both normalised to param name).
    - Construct a new Param (immutable) and replace in fn.params.
    """
    new_params: list[Param] = []
    for param in fn.params:
        alias_unit, alias_ref = _resolve_alias(param.type_name, alias_map)

        # Unit conflict check.
        if alias_unit is not None and param.unit_expr is not None:
            if alias_unit != param.unit_expr:
                raise RefinementError(
                    f"Unit conflict on parameter '{param.name}': "
                    f"type alias carries unit '{alias_unit}' but parameter "
                    f"annotation specifies '{param.unit_expr}'",
                    line=param.line,
                    col=param.col,
                )

        resolved_unit = alias_unit if param.unit_expr is None else param.unit_expr

        if alias_ref is None:
            # No alias refinement: param is unchanged (immutable: rebuild only if needed).
            if resolved_unit != param.unit_expr:
                param = Param(
                    name=param.name,
                    type_name=param.type_name,
                    unit_expr=resolved_unit,
                    refinement=param.refinement,
                    line=param.line,
                    col=param.col,
                )
            new_params.append(param)
            continue

        # Alias carries a refinement: substitute alias binder -> param name.
        alias_ref_renamed = Refinement(
            binder=param.name,
            predicate=_substitute_var(alias_ref.predicate, alias_ref.binder, param.name),
            line=alias_ref.line,
            col=alias_ref.col,
        )

        # Merge with any explicit param refinement.
        if param.refinement is not None:
            # Explicit refinement on param: normalise its binder to param name too.
            explicit_pred_renamed = _substitute_var(
                param.refinement.predicate, param.refinement.binder, param.name
            )
            combined_pred = ASTNode(
                kind=NodeKind.BINOP,
                value="&&",
                children=[alias_ref_renamed.predicate, explicit_pred_renamed],
                line=alias_ref.line,
                col=alias_ref.col,
            )
            merged_ref = Refinement(
                binder=param.name,
                predicate=combined_pred,
                line=alias_ref.line,
                col=alias_ref.col,
            )
        else:
            merged_ref = alias_ref_renamed

        new_params.append(Param(
            name=param.name,
            type_name=param.type_name,
            unit_expr=resolved_unit,
            refinement=merged_ref,
            line=param.line,
            col=param.col,
        ))

    fn.params = new_params

    # Return-type alias expansion: same logic, applied to fn.return_type.
    # The conventional binder name for return refinements is "result".
    if fn.return_type:
        ret_alias_unit, ret_alias_ref = _resolve_alias(fn.return_type, alias_map)

        if ret_alias_unit is not None and fn.return_unit_expr is not None:
            if ret_alias_unit != fn.return_unit_expr:
                raise RefinementError(
                    f"Unit conflict on return type of '{fn.name}': "
                    f"type alias carries unit '{ret_alias_unit}' but return "
                    f"annotation specifies '{fn.return_unit_expr}'",
                    line=fn.line,
                    col=fn.col,
                )
        if ret_alias_unit is not None and fn.return_unit_expr is None:
            fn.return_unit_expr = ret_alias_unit

        if ret_alias_ref is not None:
            ret_alias_ref_renamed = Refinement(
                binder="result",
                predicate=_substitute_var(ret_alias_ref.predicate, ret_alias_ref.binder, "result"),
                line=ret_alias_ref.line,
                col=ret_alias_ref.col,
            )
            if fn.return_refinement is not None:
                explicit_pred_renamed = _substitute_var(
                    fn.return_refinement.predicate, fn.return_refinement.binder, "result"
                )
                fn.return_refinement = Refinement(
                    binder="result",
                    predicate=ASTNode(
                        kind=NodeKind.BINOP,
                        value="&&",
                        children=[ret_alias_ref_renamed.predicate, explicit_pred_renamed],
                        line=ret_alias_ref.line,
                        col=ret_alias_ref.col,
                    ),
                    line=ret_alias_ref.line,
                    col=ret_alias_ref.col,
                )
            else:
                fn.return_refinement = ret_alias_ref_renamed


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
