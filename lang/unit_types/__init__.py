"""EML-lang dimensional type-checker (Phase B).

Public API
----------
    from lang.unit_types import check_module, UnitTypeError

`check_module(mod)` runs dimensional inference and type-checking on a
parsed `EMLModule`. Returns the module on success; raises `UnitTypeError`
on the first dimensional mismatch.

The module is returned unchanged -- backends see zero behavioral
difference. All unit information is a sibling layer, not a replacement
for the existing AST.
"""

from lang.unit_types.check import check_module
from lang.unit_types.diagnostics import UnitTypeError
from lang.unit_types.unit import Unit, UnitVar, DIMENSIONLESS

__all__ = [
    "check_module",
    "UnitTypeError",
    "Unit",
    "UnitVar",
    "DIMENSIONLESS",
]
