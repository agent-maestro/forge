"""Fast chain-order estimator using ``eml_genome.predict_pfaffian_r``.

98.6 % accurate vs ``eml_cost.analyze`` on the C-237 corpus,
3-13× faster (3× on real expressions, 13× on random EML trees).

Use as a *hint* or *pre-filter* where a rare 1.4 % wrong answer
is tolerable (e.g. abstain-on-high-chain-order in family routing,
short-circuit slow ``recommend_form`` calls).

For audit / cost-violation reporting, keep using
``eml_cost.analyze`` — that's the canonical path.

Provenance: closed-form formula derived in
``monogate-research/exploration/C258_pfaffian_closed_form/``.
Source of truth: the ``eml_genome`` package
(``exploration/eml-genome-pkg/`` in monogate-research).
"""

from __future__ import annotations

try:                                                  # eml_genome is optional
    from eml_genome import predict_pfaffian_r as _fast_estimator
    _AVAILABLE = True
except ImportError:                                   # graceful fallback
    _AVAILABLE = False
    _fast_estimator = None                            # type: ignore[assignment]


def estimate_chain_order(sympy_expr) -> int | None:
    """Estimate chain order in O(n) using ``eml_genome.predict_pfaffian_r``.

    Returns
    -------
    int | None
        The predicted Pfaffian chain order, or ``None`` if
        ``eml_genome`` is unavailable or the formula raises on the
        input. Callers should treat ``None`` as "no estimate; fall
        back to the slow path".

    Notes
    -----
    - Match rate vs ``eml_cost.analyze.pfaffian_r`` on the C-237
      corpus: **98.6 %** (8 of 553 rows disagree, all on
      eml_cost-internal constant-folding patterns).
    - Match rate on 1 000 random EML trees of depth ≤ 5: **86 %**.
    - Worst observed under-prediction on the corpus: ``truth - pred = 3``.
      For *safe* skip decisions, use a margin of 3 (i.e. skip iff
      ``estimate + 3 ≤ ceiling``); this gives 100 % guaranteed
      correctness on the corpus.
    """
    if not _AVAILABLE:
        return None
    try:
        return int(_fast_estimator(sympy_expr))
    except Exception:                                 # noqa: BLE001
        return None


def is_chain_order_definitely_below(sympy_expr, ceiling: int,
                                     safety_margin: int = 3) -> bool:
    """Return True if the chain order is guaranteed-below the ceiling.

    Used by SuperBEST and cost_aware to short-circuit slow
    ``eml_cost.analyze`` calls when the prediction is comfortably
    below the constraint. Defaults to ``safety_margin = 3`` which
    matches the worst observed under-prediction on the C-237 corpus.

    Returns
    -------
    bool
        ``True``  -> chain order is *guaranteed* ≤ ceiling; safe to
                     skip the slow analyze.
        ``False`` -> either no estimate, or the prediction is too
                     close to the ceiling; use the slow path.
    """
    pred = estimate_chain_order(sympy_expr)
    if pred is None:
        return False
    return pred + safety_margin <= ceiling
