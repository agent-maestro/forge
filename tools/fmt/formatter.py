"""AST-driven canonical formatter for EML-lang."""

from __future__ import annotations

from pathlib import Path

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    EMLTypeAlias,
    NodeKind,
    Param,
    WhereClause,
)
from lang.parser.parser import parse_source


# ── Operator precedence (must mirror parser) ──────────────────


_PRECEDENCE: dict[str, int] = {
    "||": 1,
    "&&": 2,
    "==": 3, "!=": 3, "<": 3, ">": 3, "<=": 3, ">=": 3,
    "+": 4, "-": 4,
    "*": 5, "/": 5,
}
_UNARY_PREC = 6
_CALL_PREC = 7
_ATOM_PREC = 8


# Map NodeKind for builtins to their source-level name.
_KIND_TO_BUILTIN_NAME: dict[NodeKind, str] = {
    NodeKind.EML: "eml",
    NodeKind.EXP: "exp",
    NodeKind.LN: "ln",
    NodeKind.SIN: "sin",
    NodeKind.COS: "cos",
    NodeKind.TAN: "tan",
    NodeKind.SQRT: "sqrt",
    NodeKind.POW: "pow",
    NodeKind.ABS: "abs",
    NodeKind.CLAMP: "clamp",
    NodeKind.ASIN: "asin",
    NodeKind.ACOS: "acos",
    NodeKind.ATAN: "atan",
    NodeKind.SINH: "sinh",
    NodeKind.COSH: "cosh",
    NodeKind.TANH: "tanh",
}


# ── Public API ────────────────────────────────────────────────


def format_source(text: str, *, source_file: str = "<string>") -> str:
    """Parse + re-emit a .eml source string in canonical form.

    Comments are NOT preserved (the parser strips them at lex time).
    Use line-anchored doc-comments inside @verify(...) annotations
    if you need persistent prose.
    """
    mod = parse_source(text, source_file)
    return _Formatter().format_module(mod)


def format_file(path: str | Path) -> str:
    """Parse + re-emit a .eml file. Returns the canonical string;
    the file on disk is NOT modified by this function -- callers
    decide whether to write it back."""
    p = Path(path)
    return format_source(
        p.read_text(encoding="utf-8"),
        source_file=str(p),
    )


# ── Internal formatter ────────────────────────────────────────


class _Formatter:
    INDENT = "    "

    def __init__(self) -> None:
        self.depth = 0

    def _ind(self) -> str:
        return self.INDENT * self.depth

    # ── Module ────────────────────────────────────────────────

    def format_module(self, mod: EMLModule) -> str:
        out: list[str] = []
        if mod.name:
            out.append(f"module {mod.name};\n")

        # `use stdlib::name;` block.
        if mod.imports:
            for imp in mod.imports:
                out.append(f"use {imp.joined};")
            out.append("")

        # Constants block
        if mod.constants:
            for c in mod.constants:
                out.append(self._format_constant(c))
            out.append("")  # blank line after the block

        # Type aliases block
        if mod.types:
            for t in mod.types:
                out.append(self._format_type_alias(t))
            out.append("")

        # Functions
        for i, fn in enumerate(mod.functions):
            if i > 0:
                out.append("")  # blank line between functions
            out.append(self._format_function(fn))

        text = "\n".join(out).rstrip() + "\n"
        # Collapse runs of >=3 blank lines down to 2.
        while "\n\n\n\n" in text:
            text = text.replace("\n\n\n\n", "\n\n\n")
        return text

    # ── Top-level declarations ────────────────────────────────

    def _format_constant(self, c: EMLConstant) -> str:
        rhs = self._format_expr(c.value, parent_prec=0)
        return f"const {c.name}: {c.type_name} = {rhs};"

    def _format_type_alias(self, t: EMLTypeAlias) -> str:
        s = f"type {t.name} = {t.base_type}"
        if t.constraint:
            s += (
                f" where chain_order {t.constraint['op']}"
                f" {t.constraint['value']}"
            )
        return s + ";"

    def _format_function(self, fn: EMLFunction) -> str:
        lines: list[str] = []
        for ann in fn.annotations:
            lines.append(self._format_annotation(ann))

        params_s = ", ".join(self._format_param(p) for p in fn.params)
        if fn.return_tuple_types:
            ret_s = "(" + ", ".join(fn.return_tuple_types) + ")"
        else:
            ret_s = fn.return_type
        header = f"fn {fn.name}({params_s}) -> {ret_s}"
        lines.append(header)

        if fn.where_clauses:
            wc_lines = [
                self._format_where(w, is_first=(i == 0))
                for i, w in enumerate(fn.where_clauses)
            ]
            # Comma at the end of every line except the last.
            wc_text = ",\n".join(wc_lines)
            lines.append(wc_text)

        for r in fn.requires:
            lines.append(
                f"{self.INDENT}requires "
                f"{self._format_expr(r, parent_prec=0)}"
            )
        for e in fn.ensures:
            lines.append(
                f"{self.INDENT}ensures "
                f"{self._format_expr(e, parent_prec=0)}"
            )

        # Body. _format_block manages its own indent depth, so we
        # do NOT bump self.depth here -- that would push body stmts
        # to two indentation levels.
        if fn.body is None:
            lines.append("{ }")
        else:
            lines.append(self._format_block(fn.body))

        return "\n".join(lines)

    def _format_annotation(self, ann: Annotation) -> str:
        # Reconstruct positional + keyword args in declaration order.
        # The parser stores positional under int keys (0, 1, 2...) and
        # keyword under their name. Render positional first.
        pos: list[str] = []
        kw: list[str] = []
        for k, v in ann.args.items():
            if isinstance(k, int):
                pos.append((k, str(v)))
            else:
                kw.append(f"{k} = {v}")
        pos.sort(key=lambda t: t[0])
        pos_strs = [p[1] for p in pos]
        all_args = ", ".join(pos_strs + kw)
        return f"@{ann.kind}({all_args})"

    def _format_param(self, p: Param) -> str:
        return f"{p.name}: {p.type_name}"

    def _format_where(self, w: WhereClause, *, is_first: bool) -> str:
        prefix = (
            f"{self.INDENT}where "
            if is_first
            else f"{self.INDENT}      "
        )
        if w.kind == "chain_order":
            return f"{prefix}chain_order {w.op} {w.value}"
        if w.kind == "domain":
            expr = self._format_expr(w.value, parent_prec=0)
            return f"{prefix}domain: {expr}"
        if w.kind == "precision":
            return f"{prefix}precision {w.op} {w.value}"
        # Fallback for unknown kinds.
        return f"{prefix}{w.kind}"

    # ── Statements / blocks ───────────────────────────────────

    def _format_block(self, block: ASTNode) -> str:
        lines: list[str] = ["{"]
        self.depth += 1
        for stmt in block.children:
            lines.append(self._format_stmt(stmt))
        self.depth -= 1
        lines.append(f"{self._ind()}}}")
        return "\n".join(lines)

    def _format_stmt(self, node: ASTNode) -> str:
        ind = self._ind()
        k = node.kind
        if k in (NodeKind.LET, NodeKind.LET_MUT):
            kw = "let mut" if k == NodeKind.LET_MUT else "let"
            type_part = (
                f": {node.type_annotation}"
                if node.type_annotation else ""
            )
            rhs = self._format_expr(node.children[0], parent_prec=0)
            return f"{ind}{kw} {node.value}{type_part} = {rhs};"
        if k == NodeKind.ASSIGN:
            rhs = self._format_expr(node.children[0], parent_prec=0)
            return f"{ind}{node.value} = {rhs};"
        if k == NodeKind.WHILE:
            cond = self._format_expr(node.children[0], parent_prec=0)
            self.depth += 0  # body block handles its own depth
            body = self._format_block(node.children[1])
            return f"{ind}while {cond} {body}"
        if k == NodeKind.EXPR_STMT:
            expr = self._format_expr(node.children[0], parent_prec=0)
            return f"{ind}{expr};"
        # Final expression in a block (no trailing semicolon).
        expr = self._format_expr(node, parent_prec=0)
        return f"{ind}{expr}"

    # ── Expressions ───────────────────────────────────────────

    def _format_expr(self, node: ASTNode, *, parent_prec: int) -> str:
        k = node.kind
        if k == NodeKind.LITERAL:
            return self._format_literal(node.value)

        if k == NodeKind.VAR:
            return str(node.value)

        if k == NodeKind.UNARYOP:
            op = node.value
            inner = self._format_expr(
                node.children[0], parent_prec=_UNARY_PREC,
            )
            text = f"{op}{inner}"
            return _wrap(text, _UNARY_PREC, parent_prec)

        if k == NodeKind.BINOP:
            op = node.value
            prec = _PRECEDENCE.get(op, 0)
            # Left-associative: left at prec, right at prec+1.
            left = self._format_expr(
                node.children[0], parent_prec=prec,
            )
            right = self._format_expr(
                node.children[1], parent_prec=prec + 1,
            )
            text = f"{left} {op} {right}"
            return _wrap(text, prec, parent_prec)

        if k == NodeKind.CALL:
            args = ", ".join(
                self._format_expr(c, parent_prec=0)
                for c in node.children
            )
            return f"{node.value}({args})"

        if k in _KIND_TO_BUILTIN_NAME:
            name = _KIND_TO_BUILTIN_NAME[k]
            args = ", ".join(
                self._format_expr(c, parent_prec=0)
                for c in node.children
            )
            return f"{name}({args})"

        if k == NodeKind.TUPLE:
            elems = ", ".join(
                self._format_expr(c, parent_prec=0)
                for c in node.children
            )
            return f"({elems})"

        if k == NodeKind.BLOCK:
            self.depth -= 0
            return self._format_block(node)

        # Fallback (should not happen for valid AST).
        return f"<unhandled:{k.value}>"

    def _format_literal(self, value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            # Canonical: shortest repr that round-trips.
            s = repr(value)
            # Python's repr emits 1e16 without a dot; preserve it.
            return s
        return str(value)


# ── Helpers ───────────────────────────────────────────────────


def _wrap(text: str, my_prec: int, parent_prec: int) -> str:
    if my_prec < parent_prec:
        return f"({text})"
    return text
