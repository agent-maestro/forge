"""EML-lang parser -- recursive-descent over the EMLLang grammar.

SCAFFOLD. The full implementation lands in Phase 1.2; this file
is a skeleton showing the public API that backends + the type
checker depend on.

See `lang/spec/EML_LANG_DESIGN.md` section 1.2 for the design.
"""

from __future__ import annotations

from pathlib import Path

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLTypeAlias,
)


class ParseError(Exception):
    """Raised on any syntax error. Carries source location."""
    def __init__(self, msg: str, line: int, col: int, source_file: str = ""):
        self.line = line
        self.col = col
        self.source_file = source_file
        super().__init__(f"{source_file}:{line}:{col}: {msg}")


class Parser:
    """Recursive-descent parser for EML-lang."""

    def __init__(self, source: str, source_file: str = "<string>"):
        self.source = source
        self.source_file = source_file
        self.tokens: list[tuple] = self._tokenize(source)
        self.pos = 0

    # ── Public API ────────────────────────────────────────────

    def parse(self) -> dict:
        """Parse source into a dict with keys:
            'functions': list[EMLFunction]
            'constants': list[EMLConstant]
            'types':     list[EMLTypeAlias]
        """
        raise NotImplementedError("parser body lands in Phase 1.2")

    # ── Internal helpers ──────────────────────────────────────

    def _tokenize(self, src: str) -> list[tuple]:
        """Tokenize source into (kind, value, line, col) tuples."""
        raise NotImplementedError("lexer body lands in Phase 1.2")

    def _parse_function(self) -> EMLFunction:
        raise NotImplementedError

    def _parse_constant(self) -> EMLConstant:
        raise NotImplementedError

    def _parse_type_decl(self) -> EMLTypeAlias:
        raise NotImplementedError

    def _parse_expr(self, min_prec: int = 0) -> ASTNode:
        """Parse expression with precedence climbing."""
        raise NotImplementedError


# ── Convenience entrypoints ───────────────────────────────────

def parse_file(path: Path | str) -> dict:
    """Parse a .eml file into the program dict."""
    p = Path(path)
    return Parser(p.read_text(encoding="utf-8"), str(p)).parse()


def parse_source(text: str, source_file: str = "<string>") -> dict:
    """Parse a string of .eml source."""
    return Parser(text, source_file).parse()
