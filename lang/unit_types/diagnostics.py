"""Dimensional type-check diagnostics for EML-lang.

`UnitTypeError` mirrors ParseError's shape: carries a human-readable
message, and the source location (line, col) where the error was
detected.  Backends and the CLI catch this to print structured output.
"""

from __future__ import annotations


class UnitTypeError(Exception):
    """A dimensional type-checking failure.

    Attributes
    ----------
    message : str
        Human-readable description of the dimensional mismatch.
    line : int
        1-indexed source line of the offending expression.
    col : int
        1-indexed source column of the offending expression.
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
        super().__init__(f"TypeError at {location}: {message}")
