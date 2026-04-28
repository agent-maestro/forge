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

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    BUILTIN_TO_KIND,
    EMLConstant,
    EMLFunction,
    EMLModule,
    EMLTypeAlias,
    NodeKind,
    Param,
    WhereClause,
)
from lang.parser.lexer import Token, tokenize


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

        while not self._check("EOF"):
            tok = self._peek()
            if self._check("KEYWORD", "const"):
                mod.constants.append(self._parse_const())
            elif self._check("KEYWORD", "type"):
                mod.types.append(self._parse_type_alias())
            elif self._check("AT") or self._check("KEYWORD", "fn"):
                mod.functions.append(self._parse_function())
            else:
                raise ParseError(
                    "expected `const`, `type`, `fn`, or `@`-annotation",
                    tok, self.source_file,
                )
        return mod

    # ── Declarations ──────────────────────────────────────────

    def _parse_const(self) -> EMLConstant:
        kw = self._eat("KEYWORD", "const")
        name_tok = self._eat("IDENT")
        self._eat("COLON")
        type_name = self._parse_type_name()
        self._eat("ASSIGN")
        expr = self._parse_expr()
        # Optional trailing semicolon (some demo files include it,
        # others don't).
        self._accept("SEMI")
        return EMLConstant(
            name=name_tok.value,
            type_name=type_name,
            value=expr,
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
        return_type, return_tuple_types = self._parse_return_type()
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
            where_clauses=where_clauses,
            body=body,
            annotations=annotations,
            requires=requires,
            ensures=ensures,
            line=kw.line,
            col=kw.col,
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
            type_name = self._parse_type_name()
            params.append(Param(
                name=name_tok.value,
                type_name=type_name,
                line=name_tok.line,
                col=name_tok.col,
            ))
            if not self._accept("COMMA"):
                break
        return params

    def _parse_return_type(self) -> tuple[str, list[str]]:
        """Return (single_type_name, tuple_types). Only one is non-empty.
        For tuple returns like `(f64, f64)`, single_type_name is empty
        and tuple_types is the list."""
        if self._check("LPAREN"):
            self._advance()
            tuple_types: list[str] = []
            while not self._check("RPAREN"):
                tuple_types.append(self._parse_type_name())
                if not self._accept("COMMA"):
                    break
            self._eat("RPAREN")
            return ("", tuple_types)
        return (self._parse_type_name(), [])

    def _parse_type_name(self) -> str:
        """A type is a single keyword (Real, f64, ...), an identifier
        (a user-declared alias), or `fixed<W,F>`."""
        tok = self._peek()
        if tok.kind == "KEYWORD" and tok.value == "fixed":
            self._advance()
            self._eat("LT")
            w = self._eat("INT").value
            self._eat("COMMA")
            f = self._eat("INT").value
            self._eat("GT")
            return f"fixed<{w},{f}>"
        if tok.kind in ("IDENT", "KEYWORD"):
            return self._advance().value
        raise ParseError("expected a type name", tok, self.source_file)

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
        args: list[ASTNode] = []
        if self._check("RPAREN"):
            return args
        while True:
            args.append(self._parse_expr())
            if not self._accept("COMMA"):
                break
        return args


# ── Convenience entrypoints ───────────────────────────────────

def parse_source(text: str, source_file: str = "<string>") -> EMLModule:
    """Parse a string of .eml source into an EMLModule."""
    return Parser(text, source_file).parse()


def parse_file(path: str | Path) -> EMLModule:
    """Parse a .eml file into an EMLModule."""
    p = Path(path)
    return parse_source(p.read_text(encoding="utf-8"), str(p))
