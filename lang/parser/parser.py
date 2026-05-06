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
    Refinement,
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


# ── Phase C: refinement predicate sub-language ───────────────────────

# Functions allowed inside a refinement predicate body.
# Transcendentals (sin, cos, tan, exp, ln, sqrt, floor, ceil, round,
# asin, acos, atan, sinh, cosh, tanh) are explicitly banned.
_REFINEMENT_ALLOWED_CALLS: frozenset[str] = frozenset({"abs", "min", "max"})

# Transcendentals that are banned in predicate bodies -- named here so
# the error message can say exactly which function was rejected.
_REFINEMENT_BANNED_CALLS: frozenset[str] = frozenset({
    "sin", "cos", "tan", "exp", "ln", "sqrt",
    "floor", "ceil", "round",
    "asin", "acos", "atan",
    "sinh", "cosh", "tanh",
    "eml", "clamp", "pow",
})

# Numeric type keywords that may carry a refinement.
_REFINABLE_TYPE_KEYWORDS: frozenset[str] = frozenset({
    "Real", "f64", "f32", "f16", "bf16",
    "u8", "u16", "u32", "u64",
    "i8", "i16", "i32", "i64",
    "Int",
})


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
        # Phase C: set of module-level const names accumulated during parsing.
        # Used to validate refinement predicate identifiers against consts.
        self._const_names: set[str] = set()

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
        # Phase C: record const name so refinement predicates can reference it.
        self._const_names.add(name_tok.value)
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
        # Phase C: type aliases may carry [unit]{refinement} suffixes.
        # The binder is the only allowed ident in the predicate (no params context).
        # We call _parse_type_name_with_unit_and_refinement with a placeholder
        # that gets replaced by the actual binder once we know it.
        # Strategy: parse with empty allowed_idents set; the binder extends it.
        base_type, unit_expr, refinement = (
            self._parse_type_name_with_unit_and_refinement(
                allowed_idents=set(),  # binder added inside _parse_refinement_body
            )
        )
        constraint: Optional[dict] = None
        if self._check("KEYWORD", "where"):
            self._advance()
            constraint = self._parse_chain_order_constraint()
        self._accept("SEMI")
        return EMLTypeAlias(
            name=name_tok.value,
            base_type=base_type,
            constraint=constraint,
            unit_expr=unit_expr,
            refinement=refinement,
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
        # Phase C: pass accumulated const names so refinement predicates
        # can reference module-level constants.
        params = self._parse_params(const_names=self._const_names)
        self._eat("RPAREN")
        self._eat("ARROW")
        # Build allowed_idents for the return type: all param names + consts.
        param_names = {p.name for p in params}
        ret_allowed = self._const_names | param_names
        return_type, return_tuple_types, return_unit_expr, return_refinement = (
            self._parse_return_type(allowed_idents=ret_allowed)
        )
        # Optional `where` clauses (comma-separated).
        where_clauses: list[WhereClause] = []
        if self._check("KEYWORD", "where"):
            self._advance()
            where_clauses = self._parse_where_clauses()
        # Optional `requires` / `ensures` / `assume` (zero or more, in any order).
        # Phase C: requires/ensures predicates are also validated against the
        # restricted predicate sub-language (no transcendentals).
        # Phase G: `assume (P)` is a new keyword that behaves like `requires`
        # at the proof level but emits NO runtime guard.  It parses with the
        # FULL expression language (transcendentals allowed), same as requires.
        # Clauses are collected in source order; each clause type goes to its
        # own list (fn.requires, fn.ensures, fn.assumes).
        requires: list[ASTNode] = []
        ensures: list[ASTNode] = []
        assumes: list[ASTNode] = []
        while (
            self._check("KEYWORD", "requires")
            or self._check("KEYWORD", "ensures")
            or self._check("KEYWORD", "assume")
        ):
            kw_clause = self._advance()
            # All three clause types parse with the FULL expression language.
            # The predicate sub-language restriction (no transcendentals) applies
            # ONLY inside `{binder | predicate}` refinement type bodies.
            expr = self._parse_expr()
            if kw_clause.value == "requires":
                requires.append(expr)
            elif kw_clause.value == "ensures":
                ensures.append(expr)
            else:  # "assume"
                assumes.append(expr)
        # Body
        body = self._parse_block()
        return EMLFunction(
            name=name_tok.value,
            params=params,
            return_type=return_type,
            return_tuple_types=return_tuple_types,
            return_unit_expr=return_unit_expr,
            return_refinement=return_refinement,
            where_clauses=where_clauses,
            body=body,
            annotations=annotations,
            requires=requires,
            ensures=ensures,
            assumes=assumes,
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

        Phase C: refinements on extern fn signatures are accepted but not
        body-checked (there is no body to check). Proof obligations are
        recorded for Phase D but cannot be verified within EML.
        """
        kw = self._eat("KEYWORD", "extern")
        self._eat("KEYWORD", "fn")
        name_tok = self._eat("IDENT")
        self._eat("LPAREN")
        params = self._parse_params(const_names=self._const_names)
        self._eat("RPAREN")
        self._eat("ARROW")
        param_names = {p.name for p in params}
        ret_allowed = self._const_names | param_names
        return_type, return_tuple_types, return_unit_expr, return_refinement = (
            self._parse_return_type(allowed_idents=ret_allowed)
        )
        # Optional trailing semicolon (consistent with const/type).
        self._accept("SEMI")
        return EMLFunction(
            name=name_tok.value,
            params=params,
            return_type=return_type,
            return_tuple_types=return_tuple_types,
            return_unit_expr=return_unit_expr,
            return_refinement=return_refinement,
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

    def _parse_params(
        self,
        const_names: Optional[set[str]] = None,
    ) -> list[Param]:
        """Parse a comma-separated parameter list.

        Phase C: ``const_names`` is the set of module-level constant names
        known at the point of parsing.  The parameter list is parsed in two
        passes so that cross-parameter references (e.g. ``b: Real{x | x > a}``
        where ``a`` is the previous parameter) are syntactically accepted.
        Pass None to use an empty const_names set.
        """
        if const_names is None:
            const_names = set()

        # First pass: collect all param names (so refinements can reference
        # later params -- cross-param references are syntactically allowed).
        # We need a lookahead scan to collect them without consuming.
        # Strategy: collect names as we parse, build up the allowed set.
        params: list[Param] = []
        # We'll collect names from previously parsed params on each iteration.
        parsed_names: set[str] = set()

        while not self._check("RPAREN"):
            name_tok = self._eat("IDENT")
            param_name = name_tok.value
            self._eat("COLON")

            # The predicate can reference: binder, all param names (including
            # this param and others already seen), and module-level consts.
            # We use all param names seen so far PLUS module consts.
            allowed_idents = const_names | parsed_names | {param_name}

            type_name, unit_expr, refinement = (
                self._parse_type_name_with_unit_and_refinement(
                    allowed_idents=allowed_idents,
                )
            )
            # If type is not a refinable type, ignore any refinement attempt.
            # (For non-numeric type aliases, refinement is carried via the alias.)

            parsed_names.add(param_name)
            params.append(Param(
                name=param_name,
                type_name=type_name,
                unit_expr=unit_expr,
                refinement=refinement,
                line=name_tok.line,
                col=name_tok.col,
            ))
            if not self._accept("COMMA"):
                break
        return params

    def _parse_return_type(
        self,
        allowed_idents: Optional[set[str]] = None,
    ) -> tuple[str, list[str], Optional[str], Optional[Refinement]]:
        """Return (single_type_name, tuple_types, unit_expr, return_refinement).

        For tuple returns like `(f64, f64)`, single_type_name is empty
        and tuple_types is the list; unit_expr and return_refinement are None for tuples.
        For single return types, unit_expr captures the [unit] annotation and
        return_refinement captures any {binder | predicate} suffix.

        Phase C: pass ``allowed_idents`` so the return type's refinement can
        reference parameter names and module consts.
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
            return ("", tuple_types, None, None)
        type_name, unit_expr, refinement = (
            self._parse_type_name_with_unit_and_refinement(
                allowed_idents=allowed_idents,
            )
        )
        return (type_name, [], unit_expr, refinement)

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

        Phase C note: use `_parse_type_name_with_unit_and_refinement` when
        a ``{binder | predicate}`` suffix may also follow.  This shim keeps
        the Phase A interface for callers that don't need refinements.
        """
        type_name, unit_expr, _ref = self._parse_type_name_with_unit_and_refinement(
            allowed_idents=None  # no refinement context -- refinement silently ignored
        )
        return type_name, unit_expr

    def _parse_type_name_with_unit_and_refinement(
        self,
        allowed_idents: Optional[set[str]],
    ) -> tuple[str, Optional[str], Optional[Refinement]]:
        """Parse a type name, optional [unit_expr] suffix, and optional {binder | predicate}.

        Returns (type_name, unit_expr_text | None, Refinement | None).

        ``allowed_idents`` is the set of identifiers permitted in the predicate
        body (binder + enclosing function param names + module-level const names).
        Pass None to suppress refinement parsing entirely (for callers that don't
        support it, e.g. tuple element types).

        Order: ``Real[unit]{refinement}`` -- unit must come before refinement.
        Both are optional: ``Real``, ``Real[Hz]``, ``Real{p | ...}``, and
        ``Real[Hz]{p | ...}`` are all valid forms.
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
            # fixed<W,F> does not support unit or refinement annotations.
            return type_name, None, None
        if tok.kind in ("IDENT", "KEYWORD"):
            type_name = self._advance().value
            unit_expr = self._try_parse_unit_suffix()
            # Phase C: optionally consume a {binder | predicate} suffix.
            # Disambiguate from a function body `{ stmts }`:
            # A refinement starts with `{ IDENT PIPE`, e.g. `{p | ...}`.
            # A function body starts with `{ KEYWORD ...`, `{ IDENT ASSIGN`, etc.
            # We use 2-token lookahead: LBRACE + IDENT + PIPE is a refinement.
            refinement: Optional[Refinement] = None
            if (allowed_idents is not None
                    and self._check("LBRACE")
                    and self._is_refinement_not_block()):
                refinement = self._parse_refinement_body(
                    type_name=type_name, allowed_idents=allowed_idents
                )
            return type_name, unit_expr, refinement
        raise ParseError("expected a type name", tok, self.source_file)

    def _is_refinement_not_block(self) -> bool:
        """Lookahead: is the upcoming LBRACE a refinement annotation or a block?

        A refinement looks like ``{IDENT PIPE ...}``.
        A function body looks like ``{...}`` with any other content.

        Returns True if the next three tokens are: LBRACE, IDENT, PIPE.
        This is unambiguous: no EML statement starts with ``ident |``.
        """
        # self._peek(0) == LBRACE (already checked by caller)
        t1 = self._peek(1)   # should be IDENT (the binder)
        t2 = self._peek(2)   # should be PIPE
        return t1.kind == "IDENT" and t2.kind == "PIPE"

    def _parse_refinement_body(
        self,
        type_name: str,
        allowed_idents: set[str],
    ) -> Refinement:
        """Parse a ``{binder | predicate}`` refinement body.

        Grammar:
            refinement ::= '{' IDENT '|' pred_expr '}'
            pred_expr  ::= pred_and ('||' pred_and)*
            pred_and   ::= pred_cmp ('&&' pred_cmp)*
            pred_cmp   ::= pred_arith (CMP pred_arith)?
            pred_arith ::= pred_term (('+' | '-') pred_term)*
            pred_term  ::= pred_unary (('*' | '/') pred_unary)*
            pred_unary ::= ('-' | '!') pred_unary | pred_primary
            pred_primary ::= IDENT | IDENT '(' args ')' | NUMBER | '(' pred_expr ')'

        Restrictions:
          - Only abs/min/max are allowed as function calls.
          - Identifiers must be the binder, another param name, or a module const.
          - No transcendentals (sin, cos, exp, etc.) -- rejected at parse time.
          - No nested implication -- just &&, ||, !, comparisons, arithmetic.
        """
        lbrace = self._eat("LBRACE")

        # Must have a binder identifier
        if self._check("RBRACE"):
            raise ParseError(
                "refinement body cannot be empty; "
                f"expected '{{binder | predicate}}', e.g. {{{type_name[0].lower()} | ... }}",
                self._peek(), self.source_file,
            )
        # Check for missing binder: {| ...}
        if self._check("PIPE"):
            raise ParseError(
                "refinement body missing binder; "
                "expected '{binder | predicate}', e.g. {x | x > 0}",
                self._peek(), self.source_file,
            )

        binder_tok = self._eat("IDENT")
        binder = binder_tok.value

        self._eat("PIPE")  # the '|' pipe separator in {binder | predicate}

        # Extend allowed_idents with the binder for the predicate body.
        pred_idents = allowed_idents | {binder}

        predicate = self._parse_pred_expr(pred_idents)

        self._eat("RBRACE")

        return Refinement(
            binder=binder,
            predicate=predicate,
            line=lbrace.line,
            col=lbrace.col,
        )

    # ── Predicate sub-language Pratt parser ───────────────────────────

    def _parse_pred_expr(self, allowed_idents: set[str]) -> ASTNode:
        """Parse a predicate expression with the restricted grammar."""
        left = self._parse_pred_and(allowed_idents)
        while self._check("OR"):
            op_tok = self._advance()
            right = self._parse_pred_and(allowed_idents)
            left = ASTNode(
                kind=NodeKind.BINOP, value="||",
                children=[left, right],
                line=op_tok.line, col=op_tok.col,
            )
        return left

    def _parse_pred_and(self, allowed_idents: set[str]) -> ASTNode:
        """Parse a predicate conjunction."""
        left = self._parse_pred_cmp(allowed_idents)
        while self._check("AND"):
            op_tok = self._advance()
            right = self._parse_pred_cmp(allowed_idents)
            left = ASTNode(
                kind=NodeKind.BINOP, value="&&",
                children=[left, right],
                line=op_tok.line, col=op_tok.col,
            )
        return left

    def _parse_pred_cmp(self, allowed_idents: set[str]) -> ASTNode:
        """Parse a comparison."""
        left = self._parse_pred_arith(allowed_idents)
        tok = self._peek()
        if tok.kind in ("LT", "GT", "LE", "GE", "EQ", "NE"):
            op_tok = self._advance()
            op_text = {"LT": "<", "GT": ">", "LE": "<=", "GE": ">=",
                       "EQ": "==", "NE": "!="}[op_tok.kind]
            right = self._parse_pred_arith(allowed_idents)
            return ASTNode(
                kind=NodeKind.BINOP, value=op_text,
                children=[left, right],
                line=op_tok.line, col=op_tok.col,
            )
        return left

    def _parse_pred_arith(self, allowed_idents: set[str]) -> ASTNode:
        """Parse additive arithmetic."""
        left = self._parse_pred_term(allowed_idents)
        while self._check("PLUS") or self._check("MINUS"):
            op_tok = self._advance()
            right = self._parse_pred_term(allowed_idents)
            left = ASTNode(
                kind=NodeKind.BINOP,
                value="+" if op_tok.kind == "PLUS" else "-",
                children=[left, right],
                line=op_tok.line, col=op_tok.col,
            )
        return left

    def _parse_pred_term(self, allowed_idents: set[str]) -> ASTNode:
        """Parse multiplicative arithmetic."""
        left = self._parse_pred_unary(allowed_idents)
        while self._check("STAR") or self._check("SLASH"):
            op_tok = self._advance()
            right = self._parse_pred_unary(allowed_idents)
            left = ASTNode(
                kind=NodeKind.BINOP,
                value="*" if op_tok.kind == "STAR" else "/",
                children=[left, right],
                line=op_tok.line, col=op_tok.col,
            )
        return left

    def _parse_pred_unary(self, allowed_idents: set[str]) -> ASTNode:
        """Parse unary operators."""
        tok = self._peek()
        if tok.kind == "MINUS":
            self._advance()
            sub = self._parse_pred_unary(allowed_idents)
            return ASTNode(
                kind=NodeKind.UNARYOP, value="-",
                children=[sub], line=tok.line, col=tok.col,
            )
        if tok.kind == "BANG":
            self._advance()
            sub = self._parse_pred_unary(allowed_idents)
            return ASTNode(
                kind=NodeKind.UNARYOP, value="!",
                children=[sub], line=tok.line, col=tok.col,
            )
        return self._parse_pred_primary(allowed_idents)

    def _parse_pred_primary(self, allowed_idents: set[str]) -> ASTNode:
        """Parse primary expression in predicate sub-language."""
        tok = self._peek()

        # Parenthesised sub-expression
        if tok.kind == "LPAREN":
            self._advance()
            inner = self._parse_pred_expr(allowed_idents)
            self._eat("RPAREN")
            return inner

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

        # Identifier: function call or variable reference
        if tok.kind == "IDENT":
            name_tok = self._advance()
            name = name_tok.value
            # Function call?
            if self._check("LPAREN"):
                # Check for banned transcendentals first
                if name in _REFINEMENT_BANNED_CALLS:
                    raise ParseError(
                        f"function '{name}' is not allowed in a refinement predicate; "
                        f"only abs, min, and max are permitted. "
                        f"Transcendentals like {name!r} must stay in the function body.",
                        name_tok, self.source_file,
                    )
                if name not in _REFINEMENT_ALLOWED_CALLS:
                    raise ParseError(
                        f"function '{name}' is not allowed in a refinement predicate; "
                        f"only abs, min, and max are permitted.",
                        name_tok, self.source_file,
                    )
                self._advance()  # consume '('
                args: list[ASTNode] = []
                if not self._check("RPAREN"):
                    while True:
                        args.append(self._parse_pred_expr(allowed_idents))
                        if not self._accept("COMMA"):
                            break
                self._eat("RPAREN")
                # Map to the right NodeKind
                kind_map = {"abs": NodeKind.ABS}
                node_kind = kind_map.get(name, NodeKind.CALL)
                return ASTNode(
                    kind=node_kind, value=name, children=args,
                    line=name_tok.line, col=name_tok.col,
                )
            # Variable reference -- validate it's in scope
            if name not in allowed_idents:
                raise ParseError(
                    f"identifier '{name}' is not in scope in this refinement predicate; "
                    f"only the binder, other function parameters, and module-level "
                    f"constants are allowed. Undeclared identifier: '{name}'.",
                    name_tok, self.source_file,
                )
            return ASTNode(
                kind=NodeKind.VAR, value=name,
                line=name_tok.line, col=name_tok.col,
            )

        raise ParseError(
            "expected a predicate expression (literal, identifier, or parenthesised expression)",
            tok, self.source_file,
        )

    def _parse_requires_ensures_expr(
        self,
        allowed_idents: set[str],
    ) -> ASTNode:
        """Parse a ``requires`` or ``ensures`` expression.

        Phase C restricts these to the predicate sub-language: no
        transcendentals, only abs/min/max, identifiers must be in scope.
        The opening ``(`` is optional (the original parser accepted bare exprs).

        We always parse a parenthesised expression, matching the existing
        grammar ``requires (expr)``.  A bare expression without parens is
        also accepted for backwards compat.
        """
        if self._check("LPAREN"):
            self._advance()  # consume '('
            expr = self._parse_pred_expr(allowed_idents)
            self._eat("RPAREN")
            return expr
        # Bare expression (rare; kept for compat)
        return self._parse_pred_expr(allowed_idents)

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
            # Phase C: improved error for `^` in expression position.
            # `^` is reserved for unit-expression exponentiation (inside [...]);
            # in a regular expression it has no meaning and the old generic
            # "unexpected CARET" was confusing. Emit a structured error.
            if tok.kind == "CARET":
                raise ParseError(
                    "Use pow(x, 2) for exponentiation; "
                    "`^` is reserved for unit expressions (e.g. Real[s^2]). "
                    "Example: pow(x, 2) instead of x^2.",
                    tok, self.source_file,
                )
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
