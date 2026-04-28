"""Compiler error formatting -- shared by parser, type checker,
and backends.

The aim is a `rustc`-style format with source pointers + a
suggested fix line.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    """One compiler diagnostic (error or warning)."""
    severity: str   # "error" | "warning" | "note"
    code: str       # "E001" | "W003" | etc.
    message: str
    source_file: str
    line: int
    col: int
    excerpt: str = ""
    suggestion: str = ""

    def render(self) -> str:
        """Format like rustc: code, location, excerpt, hint."""
        marker = {"error": "error", "warning": "warning", "note": "note"}[
            self.severity]
        out = [f"{marker}[{self.code}]: {self.message}",
               f"   --> {self.source_file}:{self.line}:{self.col}"]
        if self.excerpt:
            out.append(f"    |")
            out.append(f"  {self.line:>2} | {self.excerpt}")
            out.append(f"    | {' ' * self.col}^")
        if self.suggestion:
            out.append(f"   = help: {self.suggestion}")
        return "\n".join(out)
