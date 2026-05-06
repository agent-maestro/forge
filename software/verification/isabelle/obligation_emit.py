"""Phase E.4: Deferred obligation -> Isabelle/HOL lemma emitter.

Converts the ``deferred_obligations`` list on an ``EMLFunction`` into
``sorry``-marked Isabelle lemmas.

Naming convention (stable per Phase D / E.4 spec):
  ``<fn_name>_obligation_<n>``
where ``n`` is the 1-based positional index in ``deferred_obligations``.
Names are stable across rebuilds because the list position only shifts
when the EML source changes.

Each lemma signature includes all function parameters (typed via ``fixes``)
plus any parameter-refinement hypotheses (as ``assumes`` clauses), so the
obligation can reference them.
"""

from __future__ import annotations

from lang.parser.ast_nodes import EMLFunction

from software.verification.isabelle.refinement_emit import (
    refinement_to_hypothesis,
    _emit_pred,
    _substitute_var,
)

# Map EML type names -> Isabelle/HOL type names
_TYPE_TO_ISA: dict[str, str] = {
    "Real": "real", "f64": "real", "f32": "real", "f16": "real", "bf16": "real",
    "u8": "nat", "u16": "nat", "u32": "nat", "u64": "nat",
    "i8": "int", "i16": "int", "i32": "int", "i64": "int",
    "bool": "bool",
}


def _isa_type(eml_type: str) -> str:
    return _TYPE_TO_ISA.get(eml_type, "real")


def obligations_to_lemmas(fn: EMLFunction) -> list[str]:
    """Convert ``fn.deferred_obligations`` to sorry-marked Isabelle lemma strings.

    Each returned string is a complete Isabelle lemma declaration.  An empty
    list is returned when ``fn.deferred_obligations`` is empty.

    Parameters
    ----------
    fn : EMLFunction
        The function whose deferred obligations should be lowered.

    Returns
    -------
    list[str]
        One Isabelle lemma string per deferred obligation, in list order.
        Names are ``<fn.name>_obligation_1``, ``<fn.name>_obligation_2``, …

    Notes
    -----
    The lemma signature includes:
      * All function parameters with their Isabelle types (under ``fixes``).
      * All parameter-refinement hypotheses (as ``assumes`` clauses).
      * The obligation predicate itself as the ``shows`` conclusion.

    Proof body: ``sorry`` — deferred to Phase F human/agent proofs.
    """
    if not fn.deferred_obligations:
        return []

    # Build binder->param substitution map from all param refinements.
    binder_to_param: dict[str, str] = {}
    for p in fn.params:
        if p.refinement is not None:
            binder_to_param[p.refinement.binder] = p.name

    # Build fixes clause: fixes x :: real and y :: real ...
    fixes_parts = [f"{p.name} :: {_isa_type(p.type_name)}" for p in fn.params]

    # Build refinement assumption labels and propositions
    refinement_assumes: list[tuple[str, str]] = []
    for p in fn.params:
        if p.refinement is not None:
            renamed = _substitute_var(
                p.refinement.predicate, p.refinement.binder, p.name
            )
            try:
                prop = _emit_pred(renamed)
            except (ValueError, AttributeError) as exc:
                prop = f"True (* TODO: refinement unsupported ({exc}) *)"
            refinement_assumes.append((f"h_{p.name}", prop))

    lemmas: list[str] = []
    for i, obligation in enumerate(fn.deferred_obligations, start=1):
        lemma_name = f"{fn.name}_obligation_{i}"
        # Substitute binders with their corresponding parameter names.
        renamed_obligation = obligation
        for binder, param_name in binder_to_param.items():
            renamed_obligation = _substitute_var(renamed_obligation, binder, param_name)
        # Render the obligation predicate as an Isabelle prop
        try:
            prop = _emit_pred(renamed_obligation)
        except (ValueError, AttributeError) as exc:
            prop = f"True (* TODO: obligation unsupported ({exc}) *)"

        lines: list[str] = [f"lemma {lemma_name}:"]
        if fixes_parts:
            lines.append(f"  fixes {' and '.join(fixes_parts)}")
        for label, assume_prop in refinement_assumes:
            lines.append(f'  assumes {label}: "{assume_prop}"')
        lines.append(f'  shows "{prop}"')
        lines.append("  sorry")

        lemmas.append("\n".join(lines))

    return lemmas
