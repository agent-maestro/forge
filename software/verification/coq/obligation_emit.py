"""Phase E.4: Deferred obligation -> Coq lemma emitter.

Converts the ``deferred_obligations`` list on an ``EMLFunction`` into
``Admitted``-marked Coq lemmas.

Naming convention (stable per Phase D / E.4 spec):
  ``<fn_name>_obligation_<n>``
where ``n`` is the 1-based positional index in ``deferred_obligations``.
Names are stable across rebuilds because the list position only shifts
when the EML source changes.

Each lemma signature includes all function parameters (typed) plus
any parameter-refinement hypotheses that Phase E.4 has already emitted,
so the obligation can reference them.
"""

from __future__ import annotations

from lang.parser.ast_nodes import EMLFunction

from software.verification.coq.refinement_emit import (
    refinement_to_hypothesis,
    _emit_pred,
    _substitute_var,
)

# Map EML type names -> Coq type names (local mirror of CoqBackend._TYPE_TO_COQ)
_TYPE_TO_COQ: dict[str, str] = {
    "Real": "R", "f64": "R", "f32": "R", "f16": "R", "bf16": "R",
    "u8": "nat", "u16": "nat", "u32": "nat", "u64": "nat",
    "i8": "Z", "i16": "Z", "i32": "Z", "i64": "Z",
    "bool": "bool",
}


def _coq_type(eml_type: str) -> str:
    return _TYPE_TO_COQ.get(eml_type, "R")


def obligations_to_lemmas(fn: EMLFunction) -> list[str]:
    """Convert ``fn.deferred_obligations`` to Admitted-marked Coq lemma strings.

    Each returned string is a complete Coq lemma declaration.  An empty
    list is returned when ``fn.deferred_obligations`` is empty.

    Parameters
    ----------
    fn : EMLFunction
        The function whose deferred obligations should be lowered.

    Returns
    -------
    list[str]
        One Coq lemma string per deferred obligation, in list order.
        Names are ``<fn.name>_obligation_1``, ``<fn.name>_obligation_2``, …

    Notes
    -----
    The lemma signature includes:
      * All function parameters with their Coq types.
      * All parameter-refinement hypotheses (as Coq propositions).
      * The obligation predicate itself as the conclusion.

    Proof body: ``Proof. Admitted.`` — deferred to Phase F human/agent proofs.
    """
    if not fn.deferred_obligations:
        return []

    # Build parameter list: (safe_name : coq_type)
    param_sigs = [
        f"({p.name} : {_coq_type(p.type_name)})"
        for p in fn.params
    ]

    # Build refinement hypotheses for parameters that have them
    refinement_hyps: list[str] = []
    for p in fn.params:
        if p.refinement is not None:
            hyp = refinement_to_hypothesis(p.refinement, p.name)
            refinement_hyps.append(hyp)

    # Build a binder->param_name substitution map from all param refinements.
    binder_to_param: dict[str, str] = {}
    for p in fn.params:
        if p.refinement is not None:
            binder_to_param[p.refinement.binder] = p.name

    lemmas: list[str] = []
    for i, obligation in enumerate(fn.deferred_obligations, start=1):
        lemma_name = f"{fn.name}_obligation_{i}"
        # Substitute binders with their corresponding parameter names.
        renamed_obligation = obligation
        for binder, param_name in binder_to_param.items():
            renamed_obligation = _substitute_var(renamed_obligation, binder, param_name)
        # Render the obligation predicate as a Coq prop
        try:
            prop = _emit_pred(renamed_obligation)
        except (ValueError, AttributeError) as exc:
            prop = f"True  (* TODO: obligation unsupported ({exc}) *)"

        params_str = " ".join(param_sigs)
        if refinement_hyps:
            hyps_str = "\n    ".join(refinement_hyps)
            sig = (
                f"Lemma {lemma_name} {params_str}\n"
                f"    {hyps_str} :\n"
                f"    {prop}.\n"
                f"Proof. Admitted."
            )
        else:
            sig = (
                f"Lemma {lemma_name} {params_str} :\n"
                f"    {prop}.\n"
                f"Proof. Admitted."
            )

        lemmas.append(sig)

    return lemmas
