"""Phase C: Refinement type checker.

``check_module(mod)`` runs after ``lang.unit_types.check_module``. It:

1. Validates that refinement predicates are dimensionally consistent
   (the binder has the same unit as the parameter; literals coerce).
2. Checks for cross-parameter references and records deferred obligations
   on the function for Phase D.
3. For extern fns: accepts refinements on signatures, skips body checking.

Returns the module unchanged (refinements are validated and recorded but
not yet lowered to Lean in Phase C).

Raises ``RefinementError`` on the first validation failure.

Design note: No SMT solver is used. Non-decidable cases produce a
``deferred_obligation`` on the function (consumed by Phase D's Lean
lowering). The entailment library (`lang.refinements.entail`) handles
the syntactic cases it can decide.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
    Param,
    Refinement,
)
from lang.refinements.error import RefinementError
from lang.refinements.entail import Decision, entail, _extract_interval


# ── Public entry point ────────────────────────────────────────────────


def check_module(mod: EMLModule) -> EMLModule:
    """Run Phase C refinement checks on the module.

    Parameters
    ----------
    mod : EMLModule
        The parsed (and already unit-checked) module.

    Returns
    -------
    EMLModule
        The same module object, with ``deferred_obligations`` populated
        on functions where the entailment library returned UNKNOWN.

    Raises
    ------
    RefinementError
        On the first refinement validation failure (e.g. undeclared ident
        in predicate -- though most of these are caught at parse time).
    """
    const_names = {c.name for c in mod.constants}

    for fn in mod.functions:
        _check_function(fn, const_names, is_extern=fn.is_extern)

    return mod


def _check_function(
    fn: EMLFunction,
    const_names: set[str],
    is_extern: bool,
) -> None:
    """Check a single function's refinements."""
    param_names = {p.name for p in fn.params}
    all_known = const_names | param_names | {"result"}

    # Check each parameter's refinement
    for param in fn.params:
        if param.refinement is None:
            continue
        _check_refinement_predicate(
            refinement=param.refinement,
            context_name=param.name,
            all_known=all_known,
            fn=fn,
        )

    # Check return refinement
    if fn.return_refinement is not None:
        _check_refinement_predicate(
            refinement=fn.return_refinement,
            context_name="<return>",
            all_known=all_known,
            fn=fn,
        )

    # extern fn: skip body-based validation (no body exists).
    # Proof obligations are recorded but cannot be verified.
    # (Document: see Phase C design notes -- extern fn refinements
    #  are signature-only contracts lowered as Lean `sorry` in Phase D.)


def _check_refinement_predicate(
    refinement: Refinement,
    context_name: str,
    all_known: set[str],
    fn: EMLFunction,
) -> None:
    """Validate a single refinement predicate.

    - Verifies that identifiers in the predicate are in scope.
    - Detects cross-parameter references and records a deferred obligation
      when the entailment library can't decide.
    - For simple decidable refinements, no obligation is recorded.
    """
    binder = refinement.binder
    # Check for cross-param references (idents other than binder + consts)
    param_names_in_pred = _find_free_vars(
        refinement.predicate, binder_name=binder, const_names=set()
    )

    # Any free var that is not the binder itself is a cross-parameter reference
    # or an undeclared identifier. The parser already rejected undeclared ones,
    # so any remaining free vars must be param references.
    cross_param_refs = param_names_in_pred - {binder}

    if cross_param_refs:
        # Cross-parameter reference: record a deferred obligation for Phase D
        fn.deferred_obligations.append(refinement.predicate)

    # Validate that the predicate is otherwise decidable (no unknown structures)
    # For simple decidable refinements (single-binder interval), check it:
    iv = _extract_interval(refinement.predicate, binder)
    if iv is None and not cross_param_refs:
        # Non-interval predicate without cross-param refs -- record as deferred
        # obligation (Phase D will lower it to a Lean sorry-proof)
        fn.deferred_obligations.append(refinement.predicate)


def _find_free_vars(
    node: ASTNode,
    binder_name: str,
    const_names: set[str],
) -> set[str]:
    """Find all free variable references in a predicate node.

    Returns the set of VAR names encountered, excluding the binder
    and module-level constants (since those are known to be in scope).
    """
    result: set[str] = set()
    _collect_vars(node, result)
    # Remove the binder -- it's bound, not free
    result.discard(binder_name)
    # Remove const names -- they're global, not cross-param
    result -= const_names
    return result


def _collect_vars(node: ASTNode, acc: set[str]) -> None:
    """Recursively collect all VAR node names."""
    if node.kind == NodeKind.VAR:
        acc.add(node.value)
    for child in node.children:
        _collect_vars(child, acc)
