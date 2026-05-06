"""Phase C: Syntactic entailment library for refinement types.

Decides whether one refinement predicate is a subtype of another,
using syntactic interval narrowing and the `abs(x) <= k` rewrite.

Decision enum:
    YES     -- sub is provably a subtype of sup (interval narrowing succeeded)
    NO      -- sub is provably NOT a subtype of sup
    UNKNOWN -- non-decidable case; caller records a deferred obligation

No SMT solver is used. Only syntactic patterns are matched.

Supported patterns:
  - Simple bounds: `x <= c`, `x >= c`, `x < c`, `x > c`
  - Conjunction: `p && q`
  - abs rewrite: `abs(x) <= k`  -->  `-k <= x && x <= k`

All other predicates produce UNKNOWN.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from lang.parser.ast_nodes import ASTNode, NodeKind, Refinement


class Decision(Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


# ── Interval representation ───────────────────────────────────────────


class Interval:
    """A closed interval [lo, hi] or open variants.

    ``None`` means unbounded in that direction.
    ``strict_lo`` / ``strict_hi`` indicate strict inequality.
    """

    __slots__ = ("lo", "hi", "strict_lo", "strict_hi")

    def __init__(
        self,
        lo: Optional[float] = None,
        hi: Optional[float] = None,
        strict_lo: bool = False,
        strict_hi: bool = False,
    ) -> None:
        self.lo = lo
        self.hi = hi
        self.strict_lo = strict_lo
        self.strict_hi = strict_hi

    def intersect(self, other: "Interval") -> "Interval":
        """Return the intersection of two intervals."""
        # Lower bound: take the tighter one
        if self.lo is None:
            new_lo = other.lo
            new_strict_lo = other.strict_lo
        elif other.lo is None:
            new_lo = self.lo
            new_strict_lo = self.strict_lo
        elif self.lo > other.lo:
            new_lo = self.lo
            new_strict_lo = self.strict_lo
        elif other.lo > self.lo:
            new_lo = other.lo
            new_strict_lo = other.strict_lo
        else:
            new_lo = self.lo
            new_strict_lo = self.strict_lo or other.strict_lo

        # Upper bound: take the tighter one
        if self.hi is None:
            new_hi = other.hi
            new_strict_hi = other.strict_hi
        elif other.hi is None:
            new_hi = self.hi
            new_strict_hi = self.strict_hi
        elif self.hi < other.hi:
            new_hi = self.hi
            new_strict_hi = self.strict_hi
        elif other.hi < self.hi:
            new_hi = other.hi
            new_strict_hi = other.strict_hi
        else:
            new_hi = self.hi
            new_strict_hi = self.strict_hi or other.strict_hi

        return Interval(new_lo, new_hi, new_strict_lo, new_strict_hi)

    def is_subset_of(self, other: "Interval") -> Optional[bool]:
        """Return True if self ⊆ other, False if not, None if undecidable."""
        # Check lower bound: self.lo >= other.lo (or relaxed if strict)
        lo_ok: Optional[bool]
        if other.lo is None:
            lo_ok = True
        elif self.lo is None:
            lo_ok = False  # unbounded lo, but other has a lower bound
        else:
            if self.lo > other.lo:
                lo_ok = True
            elif self.lo == other.lo:
                # self.lo == other.lo: ok if other is non-strict OR self is strict
                lo_ok = (not other.strict_lo) or self.strict_lo
            else:
                # self.lo < other.lo: not a subset
                lo_ok = False

        # Check upper bound: self.hi <= other.hi
        hi_ok: Optional[bool]
        if other.hi is None:
            hi_ok = True
        elif self.hi is None:
            hi_ok = False  # unbounded hi, but other has an upper bound
        else:
            if self.hi < other.hi:
                hi_ok = True
            elif self.hi == other.hi:
                hi_ok = (not other.strict_hi) or self.strict_hi
            else:
                hi_ok = False

        if lo_ok is True and hi_ok is True:
            return True
        if lo_ok is False or hi_ok is False:
            return False
        return None

    def __repr__(self) -> str:
        lo_s = f"{'(' if self.strict_lo else '['}{self.lo!r}"
        hi_s = f"{self.hi!r}{')' if self.strict_hi else ']'}"
        return f"Interval({lo_s}, {hi_s})"


# ── Predicate -> interval extraction ─────────────────────────────────


def _extract_numeric(node: ASTNode) -> Optional[float]:
    """Extract a numeric constant from a node, handling unary minus."""
    if node.kind == NodeKind.LITERAL:
        val = node.value
        if isinstance(val, (int, float)):
            return float(val)
    if node.kind == NodeKind.UNARYOP and node.value == "-":
        inner = _extract_numeric(node.children[0])
        if inner is not None:
            return -inner
    return None


def _extract_var_name(node: ASTNode) -> Optional[str]:
    """Return the variable name if the node is a plain VAR, else None."""
    if node.kind == NodeKind.VAR:
        return node.value
    return None


def _abs_rewrite(node: ASTNode, binder: str) -> Optional[Interval]:
    """Match `abs(binder) <= k` or `abs(binder) < k` -> interval [-k, k]."""
    if node.kind not in (NodeKind.BINOP,):
        return None
    op = node.value
    if op not in ("<=", "<"):
        return None
    left, right = node.children[0], node.children[1]

    # abs(binder) OP k
    if (left.kind == NodeKind.ABS
            and len(left.children) == 1
            and _extract_var_name(left.children[0]) == binder):
        k = _extract_numeric(right)
        if k is not None:
            strict = (op == "<")
            return Interval(lo=-k, hi=k, strict_lo=strict, strict_hi=strict)
    return None


def _extract_interval(pred: ASTNode, binder: str) -> Optional[Interval]:
    """Extract a bounding interval for `binder` from a conjunction of comparisons.

    Supported forms:
      - `binder <op> k`
      - `k <op> binder`
      - `abs(binder) <= k`
      - conjunction `&&` of the above

    Returns None if the predicate can't be expressed as a simple interval.
    """
    if pred.kind == NodeKind.BINOP and pred.value == "&&":
        # Conjunction: intersect the intervals from each side
        left_iv = _extract_interval(pred.children[0], binder)
        right_iv = _extract_interval(pred.children[1], binder)
        if left_iv is None or right_iv is None:
            return None
        return left_iv.intersect(right_iv)

    # Try abs rewrite first
    abs_iv = _abs_rewrite(pred, binder)
    if abs_iv is not None:
        return abs_iv

    # Simple comparison
    if pred.kind != NodeKind.BINOP:
        return None
    op = pred.value
    if op not in ("<", "<=", ">", ">="):
        return None

    left, right = pred.children[0], pred.children[1]
    var_left = _extract_var_name(left)
    var_right = _extract_var_name(right)
    k_right = _extract_numeric(right)
    k_left = _extract_numeric(left)

    strict = op in ("<", ">")

    if var_left == binder and k_right is not None:
        # binder OP k
        if op in ("<", "<="):
            return Interval(hi=k_right, strict_hi=strict)
        else:  # >, >=
            return Interval(lo=k_right, strict_lo=strict)

    if var_right == binder and k_left is not None:
        # k OP binder  ->  binder OP' k
        if op in ("<", "<="):
            # k <= binder  ->  binder >= k
            return Interval(lo=k_left, strict_lo=strict)
        else:
            # k >= binder  ->  binder <= k
            return Interval(hi=k_left, strict_hi=strict)

    return None


# ── Public API ────────────────────────────────────────────────────────


def entail(sub: Refinement, sup: Refinement) -> Decision:
    """Decide whether `sub` is a subtype of `sup`.

    Uses the binder renaming convention: both refinements must name their
    binder (they may differ). The predicates are normalized by substituting
    the binder from each refinement.

    Parameters
    ----------
    sub : Refinement
        The proposed subtype refinement.
    sup : Refinement
        The required supertype refinement.

    Returns
    -------
    Decision
        YES if provably a subtype, NO if provably not, UNKNOWN otherwise.
    """
    # Extract intervals for each binder
    sub_iv = _extract_interval(sub.predicate, sub.binder)
    sup_iv = _extract_interval(sup.predicate, sup.binder)

    if sub_iv is None or sup_iv is None:
        return Decision.UNKNOWN

    result = sub_iv.is_subset_of(sup_iv)
    if result is True:
        return Decision.YES
    if result is False:
        return Decision.NO
    return Decision.UNKNOWN
