"""Phase C: Refinement type system for EML-lang.

Public API
----------
    from lang.refinements import Refinement, entail, auto_splice_module, RefinementError

``Refinement``
    AST dataclass for a ``{binder | predicate}`` annotation.  Defined in
    ``lang.parser.ast_nodes``; re-exported here for convenience.

``entail(sub, sup) -> Decision``
    Syntactic entailment library.  Decides whether refinement ``sub`` is a
    subtype of ``sup`` using interval narrowing, the ``abs`` rewrite, and
    conjunction breakdown.  Returns ``Decision.YES / NO / UNKNOWN``.

``auto_splice_module(mod, strict_mode=False) -> EMLModule``
    Module walker that folds single-variable ``requires``/``ensures`` clauses
    into the corresponding parameter/return refinements.  Gated by
    ``strict_mode``; when False this is a no-op (byte-identical to pre-Phase-C).

``check_module(mod) -> EMLModule``
    Entry point for Phase C refinement checking.  Runs after
    ``lang.unit_types.check_module``.  Validates predicates and records
    deferred obligations on functions for Phase D.

``RefinementError``
    Raised on refinement validation failures; carries line:col.
"""

from lang.parser.ast_nodes import Refinement
from lang.refinements.entail import entail, Decision
from lang.refinements.auto_splice import auto_splice_module, expand_aliases_module
from lang.refinements.check import check_module
from lang.refinements.error import RefinementError

__all__ = [
    "Refinement",
    "entail",
    "Decision",
    "auto_splice_module",
    "expand_aliases_module",
    "check_module",
    "RefinementError",
]
