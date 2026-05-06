"""EML-lang parser -- recursive-descent over the Token stream.

Pratt parser for expressions; standard recursive descent for
declarations and statements. Produces an EMLModule populated with
constants, type aliases, and functions.

See `lang/spec/EML_LANG_DESIGN.md` section 1.2 + 1.3 for the spec
this implements.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import math

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    BUILTIN_TO_KIND,
    EMLConstant,
    EMLFunction,
    EMLImport,
    EMLModule,
    EMLTypeAlias,
    EMLUnitDecl,
    NodeKind,
    Param,
    WhereClause,
)
from lang.parser.lexer import Token, tokenize


# ── Unit-of-measure support ───────────────────────────────────────────

# The 8 SI base units in canonical order.
# Index: 0=m, 1=kg, 2=s, 3=A, 4=K, 5=mol, 6=cd, 7=rad
_BASE_UNIT_INDEX: dict[str, int] = {
    "m": 0, "kg": 1, "s": 2, "A": 3,
    "K": 4, "mol": 5, "cd": 6, "rad": 7,
}
_ZERO_EXPONENTS: tuple = (0, 0, 0, 0, 0, 0, 0, 0)

# Scaling constants permitted inside unit RHS expressions.
_UNIT_SCALE_CONSTANTS: dict[str, float] = {
    "PI":    math.pi,
    "TAU":   2.0 * math.pi,
    "EULER": math.e,
}


def _unit_basis(idx: int) -> tuple:
    """Return the 8-exponent base vector for the base unit at index `idx`."""
    exps = [0] * 8
    exps[idx] = 1
    return tuple(exps)


def _unit_multiply(
    a: tuple[tuple, float], b: tuple[tuple, float],
) -> tuple[tuple, float]:
    """Multiply two unit vectors: (exps_a, scale_a) * (exps_b, scale_b)."""
    exps_a, scale_a = a
    exps_b, scale_b = b
    return (
        tuple(ea + eb for ea, eb in zip(exps_a, exps_b)),
        scale_a * scale_b,
    )


def _unit_divide(
    a: tuple[tuple, float], b: tuple[tuple, float],
) -> tuple[tuple, float]:
    """Divide two unit vectors: (exps_a, scale_a) / (exps_b, scale_b)."""
    exps_a, scale_a = a
    exps_b, scale_b = b
    return (
        tuple(ea - eb for ea, eb in zip(exps_a, exps_b)),
        scale_a / scale_b,
    )


def _unit_power(a: tuple[tuple, float], exp: int) -> tuple[tuple, float]:
    """Raise a unit vector to an integer power."""
    exps_a, scale_a = a
    return (
        tuple(e * exp for e in exps_a),
        scale_a ** exp,
    )


class ParseError(Exception):
    """Parser-level error -- carries source location for nice messages."""
    def __init__(self, msg: str, token: Token, source_file: str = "<string>"):
        self.token = token
        self.source_file = source_file
        super().__init__(
            f"{source_file}:{token.line}:{token.col}: {msg} "
            f"(at {token.kind!r} {token.value!r})"
        )


# Operator precedence for the Pratt expression parser.
# Higher number = tighter binding. All EML-lang binops are
# left-associative; right-associative ones would set right_assoc=True.
_BINOP_PRECEDENCE: dict[str, int] = {
    "OR":  1,   # ||
    "AND": 2,   # &&
    "EQ":  3, "NE": 3, "LT": 3, "GT": 3, "LE": 3, "GE": 3,
    "PLUS": 4, "MINUS": 4,
    "STAR": 5, "SLASH": 5,
}

_BINOP_TEXT: dict[str, str] = {
    "OR": "||", "AND": "&&",
    "EQ": "==", "NE": "!=", "LT": "<", "GT": ">", "LE": "<=", "GE": ">=",
    "PLUS": "+", "MINUS": "-",
    "STAR": "*", "SLASH": "/",
}


class Parser:
    """Recursive-descent + Pratt expression parser."""

    def __init__(self, source: str, source_file: str = "<string>"):
        self.source_file = source_file
        self.tokens: list[Token] = tokenize(source)
        self.pos = 0
        # Session-local unit registry: name -> (base_exponents, scale)
        # Pre-populated with the 8 SI base units (all have scale=1.0).
        self._unit_registry: dict[str, tuple[tuple, float]] = {
            name: (_unit_basis(idx), 1.0)
            for name, idx in _BASE_UNIT_INDEX.items()
        }
        # Dimensionless "1" pseudo-unit.
        self._unit_registry["1"] = (_ZERO_EXPONENTS, 1.0)

    # ── Token-stream helpers ──────────────────────────────────

    def _peek(self, offset: int = 0) -> Token:
        i = self.pos + offset
        if i >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[i]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def _eat(self, kind: str, value: Optional[str] = None) -> Token:
        """Consume a token of the given kind (and optional value).
        Raise if it doesn't match."""
        tok = self._peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            expected = kind if value is None else f"{kind} {value!r}"
            raise ParseError(f"expected {expected}", tok, self.source_file)
        return self._advance()

    def _check(self, kind: str, value: Optional[str] = None) -> bool:
        """Return True iff the next token matches (without consuming)."""
        tok = self._peek()
        if tok.kind != kind:
            return False
        if value is not None and tok.value != value:
            return False
        return True

    def _accept(self, kind: str, value: Optional[str] = None) -> Optional[Token]:
        """Consume + return the token if it matches; else None."""
        if self._check(kind, value):
            return self._advance()
        return None

    # ── Public entry ──────────────────────────────────────────

    def parse(self) -> EMLModule:
        module_name = ""
        # Optional `module IDENT;` at the top.
        if self._check("KEYWORD", "module"):
            self._advance()
            name_tok = self._eat("IDENT")
            module_name = name_tok.value
            self._eat("SEMI")

        mod = EMLModule(name=module_name, source_file=self.source_file)

        # `use stdlib::name;` declarations come right after `module`
        # and before any other top-level item.
        while self._check("KEYWORD", "use"):
            mod.imports.append(self._parse_use())

        while not self._check("EOF"):
            tok = self._peek()
            if self._check("KEYWORD", "unit"):
                decl = self._parse_unit_decl()
                mod.unit_decls.append(decl)
                # Register so later unit decls can reference this one.
                self._unit_registry[decl.name] = (decl.base_exponents, decl.scale)
            elif self._check("KEYWORD", "const"):
                mod.constants.append(self._parse_const())
            elif self._check("KEYWORD", "type"):
                mod.types.append(self._parse_type_alias())
            elif self._check("AT") or self._check("KEYWORD", "fn"):
                mod.functions.append(self._parse_function())
            elif self._check("KEYWORD", "extern"):
                mod.functions.append(self._parse_extern_function())
            elif self._check("KEYWORD", "use"):
                # Late-arriving use is also legal but discouraged.
                mod.imports.append(self._parse_use())
            else:
                raise ParseError(
                    "expected `use`, `unit`, `const`, `type`, `fn`, "
                    "`extern fn`, or `@`-annotation",
                    tok, self.source_file,
                )
        return mod

    def _parse_use(self) -> EMLImport:
        """Parse `use IDENT (:: IDENT)+ (:: { NAMES })? ;`.

        Path forms accepted:
          use stdlib::math;                       // import all
          use stdlib::math::{lerp, hypot2};       // selective
          use stdlib::math::{lerp as interp};     // selective + alias
          use local::helpers;                     // local sibling

        Selective-import names list must contain at least one name
        and use commas (trailing comma allowed). Each name may
        optionally have an `as <alias>` rename.
        """
        kw = self._eat("KEYWORD", "use")
        first = self._eat("IDENT")
        path: list[str] = [first.value]
        only: list[str] | None = None
        aliases: dict[str, str] | None = None
        while self._accept("DCOLON"):
            # `::{` opens the selective-import block.
            if self._check("LBRACE"):
                self._advance()
                only, aliases = self._parse_selective_names()
                self._eat("RBRACE")
                break
            seg = self._eat("IDENT")
            path.append(seg.value)
        if len(path) < 2:
            raise ParseError(
                "use path must be at least 2 segments "
                "(e.g. `use stdlib::math;`)",
                kw, self.source_file,
            )
        self._eat("SEMI")
        return EMLImport(
            path=path, only=only, aliases=aliases,
            line=kw.line, col=kw.col,
        )

    def _parse_selective_names(
        self,
    ) -> tuple[list[str], dict[str, str] | None]:
        """Parse `{name (as alias)?, ...}`. Returns the (only, aliases)
        pair. `aliases` is None when no `as` was used."""
        names: list[str] = []
        aliases: dict[str, str] = {}
        if self._check("RBRACE"):
            raise ParseError(
                "selective import block must contain at least one name",
                self._peek(), self.source_file,
            )
        while True:
            name_tok = self._eat("IDENT")
            name = name_tok.value
            names.append(name)
            # Optional `as <alias>`.
            if self._accept("KEYWORD", "as"):
                alias_tok = self._eat("IDENT")
                aliases[name] = alias_tok.value
            if not self._accept("COMMA"):
                break
            # Allow trailing comma.
            if self._check("RBRACE"):
                break
        return names, (aliases or None)

    # ── Declarations ──────────────────────────────────────────

    def _parse_const(self) -> EMLConstant:
        kw = self._eat("KEYWORD", "const")
        name_tok = self._eat("IDENT")
        self._eat("COLON")
        type_name, unit_expr = self._parse_type_name_with_unit()
        self._eat("ASSIGN")
        expr = self._parse_expr()
        # Optional trailing semicolon (some demo files include it,
        # others don't).
        self._accept("SEMI")
        return EMLConstant(
            name=name_tok.value,
            type_name=type_name,
            value=expr,
            unit_expr=unit_expr,
            line=kw.line,
            col=kw.col,
        )

    def _parse_type_alias(self) -> EMLTypeAlias:
        kw = self._eat("KEYWORD", "type")
        name_tok = self._eat("IDENT")
        self._eat("ASSIGN")
        base_type = self._parse_type_name()
        constraint: Optional[dict] = None
        if self._check("KEYWORD", "where"):
            self._advance()
            constraint = self._parse_chain_order_constraint()
        self._accept("SEMI")
        return EMLTypeAlias(
            name=name_tok.value,
            base_type=base_type,
            constraint=constraint,
            line=kw.line,
            col=kw.col,
        )

    def _parse_function(self) -> EMLFunction:
        # Optional annotations: @target(...) @verify(...) ...
        annotations: list[Annotation] = []
        while self._check("AT"):
            annotations.append(self._parse_annotation())

        kw = self._eat("KEYWORD", "fn")
        name_tok = self._eat("IDENT")
        self._eat("LPAREN")
        params = self._parse_params()
        self._eat("RPAREN")
        self._eat("ARROW")
        return_type, return_tuple_types, return_unit_expr = self._parse_return_type()
        # Optional `where` clauses (comma-separated).
        where_clauses: list[WhereClause] = []
        if self._check("KEYWORD", "where"):
            self._advance()
            where_clauses = self._parse_where_clauses()
        # Optional `requires` / `ensures` (zero or more, in any order).
        requires: list[ASTNode] = []
        ensures: list[ASTNode] = []
        while self._check("KEYWORD", "requires") or self._check("KEYWORD", "ensures"):
            kw_clause = self._advance()
            expr = self._parse_expr()
            (requires if kw_clause.value == "requires" else ensures).append(expr)
        # Body
        body = self._parse_block()
        return EMLFunction(
            name=name_tok.value,
            params=params,
            return_type=return_type,
            return_tuple_types=return_tuple_types,
            return_unit_expr=return_unit_expr,
            where_clauses=where_clauses,
            body=body,
            annotations=annotations,
            requires=requires,
            ensures=ensures,
            line=kw.line,
            col=kw.col,
        )

    def _parse_extern_function(self) -> EMLFunction:
        """Parse `extern fn NAME(params) -> RET_TYPE;`.

        An extern declaration has no body and no `requires` / `ensures` /
        `where` clauses -- just the signature. Used to declare primitives
        whose implementation is provided by a backend or runtime
        (e.g. crypto's montgomery_ladder_p256_x). Profiler treats them
        as opaque leaves; backends emit either a forward declaration
        (C / Rust) or a `sorry`-marked opaque def (Lean).
        """
        kw = self._eat("KEYWORD", "extern")
        self._eat("KEYWORD", "fn")
        name_tok = self._eat("IDENT")
        self._eat("LPAREN")
        params = self._parse_params()
        self._eat("RPAREN")
        self._eat("ARROW")
        return_type, return_tuple_types, return_unit_expr = self._parse_return_type()
        # Optional trailing semicolon (consistent with const/type).
        self._accept("SEMI")
        return EMLFunction(
            name=name_tok.value,
            params=params,
            return_type=return_type,
            return_tuple_types=return_tuple_types,
            return_unit_expr=return_unit_expr,
            body=None,
            line=kw.line,
            col=kw.col,
            is_extern=True,
        )

    # ── Unit declarations ─────────────────────────────────────────────

    def _parse_unit_decl(self) -> EMLUnitDecl:
        """Parse `unit NAME = <unit_rhs_expr> ;`.

        The RHS is a unit-algebra expression: products / quotients /
        integer powers of base-unit names, previously-declared unit
        names, integer literals, and (optionally) a multiplicative
        scaling factor using one of the permitted constants
        (PI, TAU, EULER) or a numeric literal.

        Examples:
            unit Hz  = 1/s;
            unit N   = kg*m/s^2;
            unit km  = m * 1000;
            unit deg = rad * (PI/180);
        """
        kw = self._eat("KEYWORD", "unit")
        name_tok = self._eat("IDENT")
        self._eat("ASSIGN")
        exps, scale = self._parse_unit_rhs()
        self._eat("SEMI")
        return EMLUnitDecl(
            name=name_tok.value,
            base_exponents=tuple(exps),
            scale=scale,
            line=kw.line,
            col=kw.col,
        )

    def _parse_unit_rhs(self) -> tuple[tuple, float]:
        """Parse the RHS of a unit declaration and return (base_exponents, scale).

        Grammar (informally):
            unit_rhs  ::= unit_factor ( ('*' | '/') unit_factor )*
            unit_factor ::= unit_atom ('^' INT)?
            unit_atom   ::= IDENT | INT | '(' unit_rhs ')'

        Where IDENT must be a known base-unit or previously-declared unit,
        or one of the permitted scaling constants (PI, TAU, EULER).
        """
        result = self._parse_unit_factor()
        while self._check("STAR") or self._check("SLASH"):
            op = self._advance()
            right = self._parse_unit_factor()
            if op.kind == "STAR":
                result = _unit_multiply(result, right)
            else:
                result = _unit_divide(result, right)
        return result

    def _parse_unit_factor(self) -> tuple[tuple, float]:
        """Parse `unit_atom ('^' INT)?`."""
        base = self._parse_unit_atom()
        if self._check("CARET"):
            self._advance()
            exp_tok = self._peek()
            # Support negative exponents: ^-2
            neg = False
            if exp_tok.kind == "MINUS":
                neg = True
                self._advance()
                exp_tok = self._peek()
            if exp_tok.kind != "INT":
                raise ParseError(
                    "expected integer exponent after '^'",
                    exp_tok, self.source_file,
                )
            exp = int(self._advance().value)
            if neg:
                exp = -exp
            return _unit_power(base, exp)
        return base

    def _parse_unit_atom(self) -> tuple[tuple, float]:
        """Parse the atomic unit: an identifier, a numeric literal, or a
        parenthesised unit_rhs.

        Rules:
          - An identifier must be a base unit (m, kg, s, A, K, mol, cd, rad),
            a previously-declared unit name, or a permitted scaling constant
            (PI, TAU, EULER).  Any other identifier is a ParseError.
          - A numeric literal (INT or FLOAT) is treated as a dimensionless
            scale factor (base_exponents all zero).
          - '1' as an identifier is the dimensionless unit (already in registry).
        """
        tok = self._peek()

        # Parenthesised sub-expression
        if tok.kind == "LPAREN":
            self._advance()
            result = self._parse_unit_rhs()
            self._eat("RPAREN")
            return result

        # Numeric literals -- dimensionless scale
        if tok.kind in ("INT", "FLOAT"):
            val = float(self._advance().value)
            return (_ZERO_EXPONENTS, val)

        # Boolean literal -- reject
        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            raise ParseError(
                f"unit expression: boolean literal {tok.value!r} is not "
                "a valid unit; expected a unit name or numeric literal",
                tok, self.source_file,
            )

        # String literal -- reject
        if tok.kind == "STRING":
            raise ParseError(
                "unit expression: string literals are not valid in unit "
                "declarations",
                tok, self.source_file,
            )

        # Identifier: base unit, declared unit, or permitted constant
        if tok.kind in ("IDENT", "KEYWORD"):
            name = tok.value
            # Reject function calls immediately
            if self._peek(1).kind == "LPAREN":
                raise ParseError(
                    f"unit expression: function call '{name}(...)' is not "
                    "permitted in a unit declaration",
                    tok, self.source_file,
                )
            # Permitted scaling constants
            if name in _UNIT_SCALE_CONSTANTS:
                self._advance()
                return (_ZERO_EXPONENTS, _UNIT_SCALE_CONSTANTS[name])
            # Known unit (base or previously declared)
            if name in self._unit_registry:
                self._advance()
                exps, scale = self._unit_registry[name]
                return (exps, scale)
            # Unknown identifier -- reject
            raise ParseError(
                f"unit expression: unknown unit or identifier {name!r}; "
                "only base units (m, kg, s, A, K, mol, cd, rad), "
                "previously declared units, PI, TAU, and EULER are allowed",
                tok, self.source_file,
            )

        raise ParseError(
            "unit expression: expected a unit name, numeric literal, "
            "or parenthesised expression",
            tok, self.source_file,
        )

    def _parse_annotation(self) -> Annotation:
        at = self._eat("AT")
        kind_tok = self._eat("IDENT") if self._check("IDENT") else self._eat("KEYWORD")
        self._eat("LPAREN")
        args: dict = {}
        pos_idx = 0
        while not self._check("RPAREN"):
            # Look ahead: <ident> = <expr>  vs  <expr>
            if (self._check("IDENT") or self._check("KEYWORD")) \
                    and self._peek(1).kind == "ASSIGN":
                key_tok = self._advance()
                self._eat("ASSIGN")
                val_tok = self._advance()  # accept any single token as the value
                args[key_tok.value] = val_tok.value
            else:
                tok = self._advance()
                args[pos_idx] = tok.value
                pos_idx += 1
            if not self._accept("COMMA"):
                break
        self._eat("RPAREN")
        return Annotation(
            kind=kind_tok.value, args=args, line=at.line, col=at.col,
        )

    def _parse_params(self) -> list[Param]:
        params: list[Param] = []
        while not self._check("RPAREN"):
            name_tok = self._eat("IDENT")
            self._eat("COLON")
            type_name, unit_expr = self._parse_type_name_with_unit()
            params.append(Param(
                name=name_tok.value,
                type_name=type_name,
                unit_expr=unit_expr,
                line=name_tok.line,
                col=name_tok.col,
            ))
            if not self._accept("COMMA"):
                break
        return params

    def _parse_return_type(self) -> tuple[str, list[str], Optional[str]]:
        """Return (single_type_name, tuple_types, unit_expr).

        For tuple returns like `(f64, f64)`, single_type_name is empty
        and tuple_types is the list; unit_expr is None for tuples.
        For single return types, unit_expr captures the [unit] annotation.
        """
        if self._check("LPAREN"):
            self._advance()
            tuple_types: list[str] = []
            while not self._check("RPAREN"):
                # Tuple element types may also carry unit annotations
                # (deferred to Phase B; consume them without error).
                t, _ = self._parse_type_name_with_unit()
                tuple_types.append(t)
                if not self._accept("COMMA"):
                    break
            self._eat("RPAREN")
            return ("", tuple_types, None)
        type_name, unit_expr = self._parse_type_name_with_unit()
        return (type_name, [], unit_expr)

    def _parse_type_name(self) -> str:
        """A type is a single keyword (Real, f64, ...), an identifier
        (a user-declared alias), or `fixed<W,F>`.

        This shim drops the optional unit annotation when callers
        (e.g. `_parse_type_alias`, `_parse_let`) don't need it.
        Use `_parse_type_name_with_unit` where the unit must be captured.
        """
        type_name, _ = self._parse_type_name_with_unit()
        return type_name

    def _parse_type_name_with_unit(self) -> tuple[str, Optional[str]]:
        """Parse a type name, optionally followed by a [unit_expr] suffix.

        Returns (type_name, unit_expr_text | None).

        The unit suffix is only consumed when the next token after the
        type name is LBRACK -- this is unambiguous in EML because the
        language has no array-indexing expression syntax, so `[` after
        a type keyword can only mean a unit annotation.

        Design decision (Phase A): literal-suffix form `9.81 [m/s^2]`
        (a unit annotation attached to a numeric literal in an *expression*
        context) is NOT parsed here; it is deferred to Phase B.
        Rationale: expressions are already tokenized before this path
        is called, and distinguishing `foo[x]` (indexing) from
        `foo [unit]` (future annotated literal) would require lookahead
        that is unnecessary for Phase A's scope of type-position
        annotations only.
        """
        tok = self._peek()
        if tok.kind == "KEYWORD" and tok.value == "fixed":
            self._advance()
            self._eat("LT")
            w = self._eat("INT").value
            self._eat("COMMA")
            f = self._eat("INT").value
            self._eat("GT")
            type_name = f"fixed<{w},{f}>"
            # fixed<W,F> does not support unit annotations in Phase A.
            return type_name, None
        if tok.kind in ("IDENT", "KEYWORD"):
            type_name = self._advance().value
            unit_expr = self._try_parse_unit_suffix()
            return type_name, unit_expr
        raise ParseError("expected a type name", tok, self.source_file)

    def _try_parse_unit_suffix(self) -> Optional[str]:
        """If the next token is LBRACK, consume a `[unit_expr]` suffix and
        return its source text.  Returns None if no bracket follows.

        A unit expression is a product/quotient/power of unit identifiers
        and integer literals, e.g.:
            [Hz]   [m/s^2]   [kg*m/s^2]   [1]   [m/s]
        Additive operators (+, -) are rejected -- they are not unit algebra.
        """
        if not self._check("LBRACK"):
            return None
        lbrack = self._advance()  # consume '['
        parts: list[str] = []
        # Collect the raw tokens until ']', building up a source-text
        # representation. Validate that only unit-algebra tokens appear.
        while not self._check("RBRACK") and not self._check("EOF"):
            tok = self._peek()
            if tok.kind == "PLUS" or tok.kind == "MINUS":
                raise ParseError(
                    "unit expression does not support additive operators; "
                    "use only *, /, ^ and unit identifiers",
                    tok, self.source_file,
                )
            if tok.kind in ("IDENT", "KEYWORD", "INT", "STAR", "SLASH"):
                parts.append(tok.value)
                self._advance()
            elif tok.kind == "CARET":
                parts.append("^")
                self._advance()
            else:
                raise ParseError(
                    f"unexpected token in unit expression",
                    tok, self.source_file,
                )
        self._eat("RBRACK")
        return "".join(parts) if parts else None

    def _parse_chain_order_constraint(self) -> dict:
        """Just the `chain_order <op> N` form -- used by type aliases."""
        self._eat("KEYWORD", "chain_order")
        op_tok = self._peek()
        if op_tok.kind not in ("LE", "LT", "GE", "GT", "EQ", "NE"):
            raise ParseError(
                "expected a comparison operator", op_tok, self.source_file,
            )
        self._advance()
        op_text = {"LE": "<=", "LT": "<", "GE": ">=", "GT": ">",
                   "EQ": "==", "NE": "!="}[op_tok.kind]
        n_tok = self._eat("INT")
        return {"op": op_text, "value": int(n_tok.value)}

    def _parse_where_clauses(self) -> list[WhereClause]:
        """Multiple comma-separated where clauses for functions."""
        clauses: list[WhereClause] = []
        while True:
            tok = self._peek()
            if self._check("KEYWORD", "chain_order"):
                start = self._advance()
                op_tok = self._peek()
                if op_tok.kind not in ("LE", "LT", "GE", "GT", "EQ", "NE"):
                    raise ParseError(
                        "expected comparison operator after `chain_order`",
                        op_tok, self.source_file,
                    )
                self._advance()
                op_text = {"LE": "<=", "LT": "<", "GE": ">=", "GT": ">",
                           "EQ": "==", "NE": "!="}[op_tok.kind]
                n_tok = self._eat("INT")
                clauses.append(WhereClause(
                    kind="chain_order",
                    op=op_text,
                    value=int(n_tok.value),
                    line=start.line, col=start.col,
                ))
            elif self._check("KEYWORD", "domain"):
                start = self._advance()
                self._eat("COLON")
                pred = self._parse_expr()
                clauses.append(WhereClause(
                    kind="domain", value=pred,
                    line=start.line, col=start.col,
                ))
            elif self._check("KEYWORD", "precision"):
                start = self._advance()
                op_tok = self._peek()
                if op_tok.kind not in ("LE", "LT"):
                    raise ParseError(
                        "expected `<=` or `<` after `precision`",
                        op_tok, self.source_file,
                    )
                self._advance()
                op_text = {"LE": "<=", "LT": "<"}[op_tok.kind]
                # The value can be a number literal (int or float).
                val_tok = self._peek()
                if val_tok.kind not in ("FLOAT", "INT"):
                    raise ParseError(
                        "expected a numeric literal for `precision`",
                        val_tok, self.source_file,
                    )
                self._advance()
                clauses.append(WhereClause(
                    kind="precision",
                    op=op_text,
                    value=float(val_tok.value),
                    line=start.line, col=start.col,
                ))
            else:
                raise ParseError(
                    "expected `chain_order`, `domain`, or `precision`",
                    tok, self.source_file,
                )
            if not self._accept("COMMA"):
                break
        return clauses

    # ── Statements + blocks ───────────────────────────────────

    def _parse_block(self) -> ASTNode:
        lb = self._eat("LBRACE")
        block = ASTNode(kind=NodeKind.BLOCK, line=lb.line, col=lb.col)
        while not self._check("RBRACE"):
            if self._check("KEYWORD", "let"):
                stmt = self._parse_let()
                self._accept("SEMI")
                block.children.append(stmt)
            elif self._check("KEYWORD", "while"):
                stmt = self._parse_while()
                self._accept("SEMI")
                block.children.append(stmt)
            elif (self._check("IDENT") and self._peek(1).kind == "ASSIGN"):
                # Bare `x = expr;` assignment to a mut binding.
                name_tok = self._advance()
                self._eat("ASSIGN")
                rhs = self._parse_expr()
                self._eat("SEMI")
                block.children.append(ASTNode(
                    kind=NodeKind.ASSIGN,
                    value=name_tok.value,
                    children=[rhs],
                    line=name_tok.line, col=name_tok.col,
                ))
            else:
                # An expression. If terminated by `;`, it's an
                # expr-statement; otherwise it's the final expression
                # of the block.
                expr = self._parse_expr()
                if self._accept("SEMI"):
                    block.children.append(ASTNode(
                        kind=NodeKind.EXPR_STMT,
                        children=[expr],
                        line=expr.line, col=expr.col,
                    ))
                else:
                    block.children.append(expr)
                    break
        self._eat("RBRACE")
        return block

    def _parse_let(self) -> ASTNode:
        kw = self._eat("KEYWORD", "let")
        is_mut = bool(self._accept("KEYWORD", "mut"))
        name_tok = self._eat("IDENT")
        # Optional `: type` annotation
        type_annot: Optional[str] = None
        if self._accept("COLON"):
            type_annot = self._parse_type_name()
        self._eat("ASSIGN")
        rhs = self._parse_expr()
        node = ASTNode(
            kind=NodeKind.LET_MUT if is_mut else NodeKind.LET,
            value=name_tok.value,
            children=[rhs],
            type_annotation=type_annot,
            line=kw.line, col=kw.col,
        )
        return node

    def _parse_while(self) -> ASTNode:
        kw = self._eat("KEYWORD", "while")
        cond = self._parse_expr()
        body = self._parse_block()
        return ASTNode(
            kind=NodeKind.WHILE,
            children=[cond, body],
            line=kw.line, col=kw.col,
        )

    # ── Expressions (Pratt) ───────────────────────────────────

    def _parse_expr(self, min_prec: int = 0) -> ASTNode:
        left = self._parse_unary()
        while True:
            tok = self._peek()
            prec = _BINOP_PRECEDENCE.get(tok.kind)
            if prec is None or prec < min_prec:
                break
            op_tok = self._advance()
            # Left-associative -- recurse with prec + 1.
            right = self._parse_expr(prec + 1)
            left = ASTNode(
                kind=NodeKind.BINOP,
                value=_BINOP_TEXT[op_tok.kind],
                children=[left, right],
                line=op_tok.line, col=op_tok.col,
            )
        return left

    def _parse_unary(self) -> ASTNode:
        tok = self._peek()
        if tok.kind == "MINUS":
            self._advance()
            sub = self._parse_unary()
            return ASTNode(
                kind=NodeKind.UNARYOP, value="-",
                children=[sub], line=tok.line, col=tok.col,
            )
        if tok.kind == "BANG":
            self._advance()
            sub = self._parse_unary()
            return ASTNode(
                kind=NodeKind.UNARYOP, value="!",
                children=[sub], line=tok.line, col=tok.col,
            )
        return self._parse_primary()

    def _parse_primary(self) -> ASTNode:
        tok = self._peek()

        # Parenthesized expression OR tuple literal
        if tok.kind == "LPAREN":
            self._advance()
            first = self._parse_expr()
            if self._accept("COMMA"):
                # Tuple literal
                elems = [first]
                while True:
                    elems.append(self._parse_expr())
                    if not self._accept("COMMA"):
                        break
                self._eat("RPAREN")
                return ASTNode(
                    kind=NodeKind.TUPLE, children=elems,
                    line=tok.line, col=tok.col,
                )
            self._eat("RPAREN")
            return first

        # Numeric literals
        if tok.kind == "FLOAT":
            self._advance()
            return ASTNode(
                kind=NodeKind.LITERAL, value=float(tok.value),
                line=tok.line, col=tok.col,
            )
        if tok.kind == "INT":
            self._advance()
            return ASTNode(
                kind=NodeKind.LITERAL, value=int(tok.value),
                line=tok.line, col=tok.col,
            )

        # Bool literals (lexed as KEYWORD)
        if tok.kind == "KEYWORD" and tok.value in ("true", "false"):
            self._advance()
            return ASTNode(
                kind=NodeKind.LITERAL, value=(tok.value == "true"),
                line=tok.line, col=tok.col,
            )

        # Identifier -- variable reference OR function call
        if tok.kind == "IDENT":
            name_tok = self._advance()
            if self._accept("LPAREN"):
                args = self._parse_call_args()
                self._eat("RPAREN")
                # Built-in dispatch: known builtin names get a
                # specialized NodeKind so backends can specialize.
                kind = BUILTIN_TO_KIND.get(name_tok.value, NodeKind.CALL)
                return ASTNode(
                    kind=kind, value=name_tok.value, children=args,
                    line=name_tok.line, col=name_tok.col,
                )
            return ASTNode(
                kind=NodeKind.VAR, value=name_tok.value,
                line=name_tok.line, col=name_tok.col,
            )

        raise ParseError(
            "expected an expression", tok, self.source_file,
        )

    def _parse_call_args(self) -> list[ASTNode]:
        """Parse a comma-separated argument list. Trailing commas
        are tolerated (Rust / modern-language convention)."""
        args: list[ASTNode] = []
        if self._check("RPAREN"):
            return args
        while True:
            args.append(self._parse_expr())
            if not self._accept("COMMA"):
                break
            # Allow trailing comma: `f(a, b,)` parses the same as `f(a, b)`.
            if self._check("RPAREN"):
                break
        return args


# ── Convenience entrypoints ───────────────────────────────────

def parse_source(
    text: str,
    source_file: str = "<string>",
    *,
    resolve: bool = False,
) -> EMLModule:
    """Parse a string of .eml source into an EMLModule.

    When `resolve=True`, any `use ...;` declarations are also
    resolved -- the imported module's constants/types/functions
    are merged into the returned module's namespace. Default
    `resolve=False` returns the raw module so callers that don't
    care about imports (e.g. the formatter) don't pay the
    filesystem-IO cost."""
    mod = Parser(text, source_file).parse()
    if resolve and mod.imports:
        # Local import to keep parser <-> loader cycle off the
        # cold path.
        from lang.loader import resolve_imports
        mod = resolve_imports(mod)
    return mod


def parse_file(
    path: str | Path,
    *,
    resolve: bool = True,
) -> EMLModule:
    """Parse a .eml file into an EMLModule.

    Default `resolve=True` since file-based callers (CLI,
    profiler-from-disk, equivalence harness) almost always want
    imports merged. Pass `resolve=False` to skip resolution
    (useful for the formatter, which only needs the raw AST)."""
    p = Path(path)
    return parse_source(
        p.read_text(encoding="utf-8"),
        str(p),
        resolve=resolve,
    )
