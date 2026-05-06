"""Unit datatype for EML-lang dimensional type-checking (Phase B).

A `Unit` is an immutable 8-tuple of integer exponents in SI base-unit
order plus a floating-point scale factor.

Base-unit index mapping (canonical order):
    0 = m    (metre)
    1 = kg   (kilogram)
    2 = s    (second)
    3 = A    (ampere)
    4 = K    (kelvin)
    5 = mol  (mole)
    6 = cd   (candela)
    7 = rad  (radian)

Design notes
-----------
- `equals_dimensionally` compares only the exponent tuple, ignoring
  scale.  This matches physics practice: Hz and kHz are
  dimensionally equal (both s^-1) even though their magnitudes differ.
- `__eq__` also uses exponent-only comparison for simplicity; scale is
  informational and preserved for potential future conversion support.
- `UnitVar` is the polymorphic placeholder for untagged numeric literals.
  It unifies with any concrete Unit at the point of first use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Canonical index for each base unit name.
BASE_UNIT_INDEX: dict[str, int] = {
    "m": 0, "kg": 1, "s": 2, "A": 3,
    "K": 4, "mol": 5, "cd": 6, "rad": 7,
}

_ZERO_BASE: tuple[int, ...] = (0, 0, 0, 0, 0, 0, 0, 0)


@dataclass(frozen=True)
class Unit:
    """Concrete physical unit: 8 exponents + scale."""

    base: tuple[int, ...]  # length-8 tuple of ints
    scale: float = 1.0
    name: str = ""          # human-readable label (best-effort, may be "")

    # ── Arithmetic ────────────────────────────────────────────

    def __mul__(self, other: "Unit") -> "Unit":
        new_base = tuple(a + b for a, b in zip(self.base, other.base))
        name = f"{self.name}*{other.name}" if self.name and other.name else (
            self.name or other.name
        )
        return Unit(base=new_base, scale=self.scale * other.scale, name=name)

    def __truediv__(self, other: "Unit") -> "Unit":
        new_base = tuple(a - b for a, b in zip(self.base, other.base))
        name = f"{self.name}/{other.name}" if self.name and other.name else (
            self.name or other.name
        )
        return Unit(base=new_base, scale=self.scale / other.scale, name=name)

    def __pow__(self, exp: int) -> "Unit":
        new_base = tuple(a * exp for a in self.base)
        name = f"{self.name}^{exp}" if self.name else ""
        return Unit(base=new_base, scale=self.scale ** exp, name=name)

    # ── Comparison ───────────────────────────────────────────

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Unit):
            return self.base == other.base
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.base)

    # ── Queries ───────────────────────────────────────────────

    def is_dimensionless(self) -> bool:
        """Return True iff all exponents are zero."""
        return self.base == _ZERO_BASE

    def equals_dimensionally(self, other: "Unit") -> bool:
        """Dimensional equality: same exponents, ignoring scale."""
        return self.base == other.base

    # ── Display ───────────────────────────────────────────────

    def __repr__(self) -> str:
        if self.name:
            return f"Unit({self.name!r})"
        return f"Unit(base={self.base}, scale={self.scale})"

    def display(self) -> str:
        """Human-readable name, or raw exponent tuple if unnamed."""
        if self.name:
            return self.name
        # Build m^a*kg^b*... notation
        names = ["m", "kg", "s", "A", "K", "mol", "cd", "rad"]
        parts = []
        for name, exp in zip(names, self.base):
            if exp == 1:
                parts.append(name)
            elif exp != 0:
                parts.append(f"{name}^{exp}")
        return "*".join(parts) if parts else "1"


# Sentinel: no unit constraint (untagged literal -- can unify with anything).
class UnitVar:
    """Polymorphic unit variable for untagged numeric literals.

    Two free UnitVars in the same expression stay polymorphic until
    something concrete pins them.
    """
    __slots__ = ()

    def __repr__(self) -> str:
        return "UnitVar()"


# Module-level singleton.
DIMENSIONLESS = Unit(base=_ZERO_BASE, scale=1.0, name="1")

# Convenient type alias used throughout infer.py / check.py.
UnitOrVar = Unit | UnitVar
