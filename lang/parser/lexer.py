"""EML-lang lexer.

Tokenizes a `.eml` source string into a list of (kind, value, line, col)
tokens consumed by the parser.

Usage:
    from lang.parser.lexer import tokenize
    tokens = tokenize(source_text)
    # tokens is list[Token]; the parser walks them sequentially.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Keyword classification. Anything not in this set that matches the
# identifier regex is emitted as an IDENT token.
KEYWORDS: frozenset[str] = frozenset({
    "module", "import", "use", "as",
    "const", "type", "fn", "extern", "let", "mut", "while", "where",
    "domain", "precision", "chain_order", "requires", "ensures",
    "return", "if", "else",
    "true", "false",
    # Phase A: unit-of-measure declarations
    "unit",
    # Type keywords (parser distinguishes by context)
    "Real", "f64", "f32", "f16", "bf16",
    "u8", "u16", "u32", "u64", "i8", "i16", "i32", "i64",
    "bool", "void", "fixed",
    # Built-in functions are NOT keywords -- they're lexed as IDENT
    # and the parser dispatches on the name. Keeps the keyword set
    # small + lets users shadow builtins if they want.
})


# Multi-character operators -- matched longest-first.
MULTI_CHAR_OPS: tuple[tuple[str, str], ...] = (
    ("->", "ARROW"),
    ("<=", "LE"),
    (">=", "GE"),
    ("==", "EQ"),
    ("!=", "NE"),
    ("&&", "AND"),
    ("||", "OR"),
    ("::", "DCOLON"),  # path separator: stdlib::math
)

SINGLE_CHAR_OPS: dict[str, str] = {
    "+": "PLUS", "-": "MINUS", "*": "STAR", "/": "SLASH",
    "<": "LT", ">": "GT", "=": "ASSIGN",
    "(": "LPAREN", ")": "RPAREN",
    "{": "LBRACE", "}": "RBRACE",
    "[": "LBRACK", "]": "RBRACK",
    ":": "COLON", ";": "SEMI", ",": "COMMA", ".": "DOT",
    "!": "BANG", "@": "AT",
    # Phase A: caret is used for unit-expression exponentiation (e.g. s^2).
    # It has no meaning in normal EML expressions; the parser only
    # consumes it inside a [unit_expr] suffix.
    "^": "CARET",
}


@dataclass(frozen=True)
class Token:
    kind: str       # one of: IDENT, KEYWORD, INT, FLOAT, STRING,
                    #         ARROW, LE, GE, EQ, NE, AND, OR,
                    #         PLUS, MINUS, STAR, SLASH, LT, GT, ASSIGN,
                    #         LPAREN, RPAREN, LBRACE, RBRACE, LBRACK, RBRACK,
                    #         COLON, SEMI, COMMA, DOT, BANG, AT, EOF
    value: str      # the source-text spelling (or normalized number string)
    line: int
    col: int


class LexError(Exception):
    """Lexer-level error -- unrecognized character at line:col."""
    def __init__(self, msg: str, line: int, col: int):
        self.line = line
        self.col = col
        super().__init__(f"line {line}:{col}: {msg}")


# Pre-compiled patterns
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_FLOAT_RE = re.compile(
    r"[0-9]+\.[0-9]+(?:[eE][+\-]?[0-9]+)?"
    r"|[0-9]+[eE][+\-]?[0-9]+"
)
_INT_RE = re.compile(r"[0-9]+")
_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def tokenize(source: str) -> list[Token]:
    """Tokenize `source` into a list of Tokens. The final token is
    always EOF."""
    tokens: list[Token] = []
    pos = 0
    line = 1
    col = 1
    n = len(source)

    while pos < n:
        ch = source[pos]

        # ── Whitespace + newlines ──────────────────────────────
        if ch == "\n":
            line += 1
            col = 1
            pos += 1
            continue
        if ch in " \t\r":
            col += 1
            pos += 1
            continue

        # ── Comments ───────────────────────────────────────────
        # Line comment // ... \n
        if source.startswith("//", pos):
            end = source.find("\n", pos)
            if end == -1:
                pos = n
            else:
                pos = end  # leave \n for the newline branch
            continue
        # Block comment /* ... */
        if source.startswith("/*", pos):
            end = source.find("*/", pos + 2)
            if end == -1:
                raise LexError("unterminated block comment", line, col)
            consumed = source[pos:end + 2]
            line += consumed.count("\n")
            last_nl = consumed.rfind("\n")
            if last_nl >= 0:
                col = len(consumed) - last_nl
            else:
                col += len(consumed)
            pos = end + 2
            continue

        # ── String literal "..." ───────────────────────────────
        if ch == '"':
            m = _STRING_RE.match(source, pos)
            if m is None:
                raise LexError("unterminated string literal", line, col)
            tokens.append(Token("STRING", m.group(1), line, col))
            consumed = m.group(0)
            pos += len(consumed)
            col += len(consumed)
            continue

        # ── Numbers (float first, then int) ────────────────────
        if ch.isdigit():
            m = _FLOAT_RE.match(source, pos)
            if m is not None:
                tokens.append(Token("FLOAT", m.group(0), line, col))
                pos += len(m.group(0))
                col += len(m.group(0))
                continue
            m = _INT_RE.match(source, pos)
            if m is not None:
                tokens.append(Token("INT", m.group(0), line, col))
                pos += len(m.group(0))
                col += len(m.group(0))
                continue

        # ── Identifiers + keywords ─────────────────────────────
        if ch.isalpha() or ch == "_":
            m = _IDENT_RE.match(source, pos)
            assert m is not None  # the leading-char check guarantees a match
            text = m.group(0)
            kind = "KEYWORD" if text in KEYWORDS else "IDENT"
            tokens.append(Token(kind, text, line, col))
            pos += len(text)
            col += len(text)
            continue

        # ── Multi-char operators (longest first) ───────────────
        matched_multi = False
        for op_text, op_kind in MULTI_CHAR_OPS:
            if source.startswith(op_text, pos):
                tokens.append(Token(op_kind, op_text, line, col))
                pos += len(op_text)
                col += len(op_text)
                matched_multi = True
                break
        if matched_multi:
            continue

        # ── Single-char operators ──────────────────────────────
        if ch in SINGLE_CHAR_OPS:
            tokens.append(Token(SINGLE_CHAR_OPS[ch], ch, line, col))
            pos += 1
            col += 1
            continue

        raise LexError(f"unexpected character {ch!r}", line, col)

    tokens.append(Token("EOF", "", line, col))
    return tokens
