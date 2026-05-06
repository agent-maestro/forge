"""Phase D: Deferred obligation -> Lean lemma emitter.

Converts the ``deferred_obligations`` list on an ``EMLFunction`` into
``sorry``-marked Lean lemmas.

Naming convention (stable per Phase D spec):
  ``<fn_name>_obligation_<n>``
where ``n`` is the 1-based positional index in ``deferred_obligations``.
Names are stable across rebuilds because the list position only shifts
when the EML source changes.

Each lemma signature includes all function parameters (typed) plus
any parameter-refinement hypotheses that Phase D has already emitted,
so the obligation can reference them.
"""

from __future__ import annotations

from lang.parser.ast_nodes import EMLFunction

from software.verification.lean.refinement_emit import (
    refinement_to_hypothesis,
    _emit_pred,
    _substitute_var,
)

# Map EML type names -> Lean type names (local mirror of LeanBackend._TYPE_TO_LEAN)
_TYPE_TO_LEAN: dict[str, str] = {
    "Real": "Real", "f64": "Real", "f32": "Real", "f16": "Real", "bf16": "Real",
    "Int": "Int", "Nat": "Nat", "Byte": "Nat",
    "u8": "Nat", "u16": "Nat", "u32": "Nat", "u64": "Nat",
    "i8": "Int", "i16": "Int", "i32": "Int", "i64": "Int",
    "bool": "Bool", "Bool": "Bool",
}

_LEAN_RESERVED: frozenset[str] = frozenset({
    "abbrev", "as", "attribute", "axiom", "begin", "by", "class",
    "constant", "decreasing_by", "def", "deriving", "do", "else",
    "end", "example", "export", "extends", "extern", "final", "for",
    "from", "fun", "have", "if", "import", "in", "inductive",
    "infix", "infixl", "infixr", "instance", "lemma", "let",
    "macro", "macro_rules", "match", "mut", "mutual", "namespace",
    "noncomputable", "notation", "open", "opaque", "partial",
    "postfix", "prefix", "private", "protected", "public", "rec",
    "return", "scoped", "section", "set_option", "show",
    "structure", "suffices", "syntax", "term", "then", "theorem",
    "this", "true", "false", "try", "universe", "unsafe",
    "variable", "where", "while", "with",
})


def _lean_type(eml_type: str) -> str:
    return _TYPE_TO_LEAN.get(eml_type, "Real")


def _safe_id(name: str) -> str:
    return f"{name}_" if name in _LEAN_RESERVED else name


def obligations_to_lemmas(fn: EMLFunction) -> list[str]:
    """Convert ``fn.deferred_obligations`` to sorry-marked Lean lemma strings.

    Each returned string is a complete Lean lemma declaration.  An empty
    list is returned when ``fn.deferred_obligations`` is empty.

    Parameters
    ----------
    fn : EMLFunction
        The function whose deferred obligations should be lowered.

    Returns
    -------
    list[str]
        One Lean lemma string per deferred obligation, in list order.
        Names are ``<fn.name>_obligation_1``, ``<fn.name>_obligation_2``, …

    Notes
    -----
    The lemma signature includes:
      * All function parameters with their Lean types.
      * All parameter-refinement hypotheses (as Lean propositions).
      * The obligation predicate itself as the conclusion.

    Proof body: ``by sorry`` — deferred to Phase F human/agent proofs.
    """
    if not fn.deferred_obligations:
        return []

    # Build parameter list: (safe_name : lean_type)
    param_sigs = [
        f"({_safe_id(p.name)} : {_lean_type(p.type_name)})"
        for p in fn.params
    ]

    # Build refinement hypotheses for parameters that have them
    refinement_hyps: list[str] = []
    for p in fn.params:
        if p.refinement is not None:
            hyp = refinement_to_hypothesis(p.refinement, p.name)
            refinement_hyps.append(hyp)

    # Build a binder->param_name substitution map from all param refinements.
    # Phase C records obligation predicates using the binder name (e.g., ``x``
    # from ``Real{x | x > a}``). We substitute each binder with its
    # corresponding param name so the obligation lemma is expressed in terms
    # of the function's Lean parameter names.
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
        # Render the obligation predicate as a Lean prop
        try:
            prop = _emit_pred(renamed_obligation)
        except (ValueError, AttributeError) as exc:
            prop = f"True  -- TODO: obligation unsupported ({exc})"

        # Build signature
        params_str = " ".join(param_sigs)
        if refinement_hyps:
            hyps_str = " ".join(refinement_hyps)
            sig = f"lemma {lemma_name} {params_str}\n    {hyps_str} :\n    {prop} := by sorry"
        else:
            sig = f"lemma {lemma_name} {params_str} :\n    {prop} := by sorry"

        lemmas.append(sig)

    return lemmas
