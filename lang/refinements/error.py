"""Phase C: RefinementError diagnostic.

Mirrors UnitTypeError's shape: carries a human-readable message
and source location (line, col).
"""

from __future__ import annotations


class RefinementError(Exception):
    """A refinement type-checking failure.

    Attributes
    ----------
    message : str
        Human-readable description of the failure.
    line : int
        1-indexed source line of the offending expression.
    col : int
        1-indexed source column.
    source_file : str
        Path (or placeholder) of the EML source file.
    """

    def __init__(
        self,
        message: str,
        line: int = 0,
        col: int = 0,
        source_file: str = "<unknown>",
    ) -> None:
        self.message = message
        self.line = line
        self.col = col
        self.source_file = source_file
        location = f"{source_file}:{line}:{col}"
        super().__init__(f"RefinementError at {location}: {message}")
