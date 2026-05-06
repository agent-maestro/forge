"""Unit-expression resolver for EML-lang Phase B.

Turns raw `unit_expr` strings (as stored by the Phase A parser on
`Param.unit_expr`, `EMLConstant.unit_expr`, and
`EMLFunction.return_unit_expr`) into `Unit` objects using the
module's `unit_decls` registry.

Grammar of unit_expr strings produced by Phase A:
    unit_expr  ::= unit_factor ('*' | '/') unit_factor)*
    unit_factor ::= unit_atom ('^' INT)?
    unit_atom   ::= IDENT | INT_OR_FLOAT

The resolver re-implements the same small grammar as a hand-rolled
recursive-descent parser over the character sequence, because the
Phase A parser stores the raw source text and we need to resolve it
afresh with the module's registry.

Only characters that can appear in a unit suffix are processed:
identifiers, integers, '*', '/', '^', and whitespace.
"""

from __future__ import annotations

import re
from typing import Optional

from lang.unit_types.unit import (
    BASE_UNIT_INDEX,
    DIMENSIONLESS,
    Unit,
    _ZERO_BASE,
)
from lang.unit_types.diagnostics import UnitTypeError


# ── Tokeniser for unit expression strings ────────────────────────────

_TOKEN_RE = re.compile(
    r"(?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<INT>-?\d+)"
    r"|(?P<STAR>\*)"
    r"|(?P<SLASH>/)"
    r"|(?P<CARET>\^)"
    r"|(?P<WS>\s+)"
)


def _tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if m is None:
            raise ValueError(f"unexpected character {expr[pos]!r} in unit expression {expr!r}")
        if m.lastgroup != "WS":
            tokens.append((m.lastgroup, m.group()))
        pos = m.end()
    return tokens


# ── Recursive-descent over the token list ────────────────────────────


class _UnitParser:
    """Mini recursive-descent parser for unit_expr strings."""

    def __init__(
        self,
        tokens: list[tuple[str, str]],
        registry: dict[str, Unit],
        expr: str,
        line: int,
        col: int,
    ) -> None:
        self._tokens = tokens
        self._pos = 0
        self._registry = registry
        self._expr = expr
        self._line = line
        self._col = col

    def _peek(self) -> Optional[tuple[str, str]]:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _advance(self) -> tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _error(self, msg: str) -> UnitTypeError:
        return UnitTypeError(msg, self._line, self._col)

    def parse(self) -> Unit:
        result = self._parse_expr()
        if self._peek() is not None:
            kind, val = self._peek()
            raise self._error(
                f"unexpected token {val!r} in unit expression {self._expr!r}"
            )
        return result

    def _parse_expr(self) -> Unit:
        result = self._parse_factor()
        while True:
            tok = self._peek()
            if tok is None:
                break
            kind, val = tok
            if kind == "STAR":
                self._advance()
                rhs = self._parse_factor()
                result = result * rhs
            elif kind == "SLASH":
                self._advance()
                rhs = self._parse_factor()
                result = result / rhs
            else:
                break
        return result

    def _parse_factor(self) -> Unit:
        base = self._parse_atom()
        tok = self._peek()
        if tok is not None and tok[0] == "CARET":
            self._advance()
            exp_tok = self._peek()
            if exp_tok is None or exp_tok[0] != "INT":
                raise self._error(
                    f"expected integer exponent after '^' in unit expression {self._expr!r}"
                )
            self._advance()
            exp = int(exp_tok[1])
            return base ** exp
        return base

    def _parse_atom(self) -> Unit:
        tok = self._peek()
        if tok is None:
            raise self._error(f"unexpected end of unit expression {self._expr!r}")
        kind, val = tok
        if kind == "IDENT":
            self._advance()
            if val in self._registry:
                return self._registry[val]
            raise self._error(
                f"undeclared unit {val!r} in unit expression {self._expr!r}; "
                f"declare it with `unit {val} = ...;` before use, or use a base unit "
                f"(m, kg, s, A, K, mol, cd, rad)"
            )
        if kind == "INT":
            self._advance()
            num = int(val)
            if num == 1:
                return DIMENSIONLESS
            # A bare number is a dimensionless scale factor.
            return Unit(base=_ZERO_BASE, scale=float(num), name=str(num))
        raise self._error(
            f"unexpected token {val!r} in unit expression {self._expr!r}"
        )


# ── Public entry point ────────────────────────────────────────────────


def resolve_unit_expr(
    expr: str,
    registry: dict[str, Unit],
    *,
    line: int = 0,
    col: int = 0,
) -> Unit:
    """Resolve a raw unit_expr string to a Unit.

    Parameters
    ----------
    expr : str
        The unit expression string, e.g. "Hz", "m/s^2", "1".
    registry : dict[str, Unit]
        Mapping of declared unit names to Unit objects.  Pre-populated
        with the 8 SI base units by `build_registry`.
    line, col : int
        Source location for error messages.

    Returns
    -------
    Unit
        The resolved dimensional unit.

    Raises
    ------
    UnitTypeError
        If `expr` references an undeclared unit name.
    """
    try:
        tokens = _tokenize(expr)
    except ValueError as e:
        raise UnitTypeError(str(e), line, col) from e

    if not tokens:
        return DIMENSIONLESS

    parser = _UnitParser(tokens, registry, expr, line, col)
    return parser.parse()


def build_registry(unit_decls: list) -> dict[str, Unit]:
    """Build a name->Unit registry from a module's unit_decls.

    Pre-seeds with all 8 SI base units (each with scale=1.0) and
    the dimensionless pseudo-unit "1".  Then adds each declared unit
    in declaration order (Phase A already enforced forward-reference
    ordering, so this is safe).

    Parameters
    ----------
    unit_decls : list[EMLUnitDecl]
        The `EMLModule.unit_decls` list.

    Returns
    -------
    dict[str, Unit]
        Mapping of unit name -> Unit for all known units.
    """
    registry: dict[str, Unit] = {}

    # 8 SI base units
    for name, idx in BASE_UNIT_INDEX.items():
        base = tuple(1 if i == idx else 0 for i in range(8))
        registry[name] = Unit(base=base, scale=1.0, name=name)

    # Dimensionless pseudo-unit
    registry["1"] = DIMENSIONLESS

    # Declared units (already flattened by Phase A parser)
    for decl in unit_decls:
        registry[decl.name] = Unit(
            base=tuple(decl.base_exponents),
            scale=decl.scale,
            name=decl.name,
        )

    return registry
