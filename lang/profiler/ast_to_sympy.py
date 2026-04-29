"""Convert an EML-lang AST expression into a SymPy expression.

The eml-cost analyzer takes SymPy expressions; this module bridges
the parser's typed AST into that form. Handles the let-binding
inlining and the tuple-return decomposition needed to profile
real-world demo files.

Limitations (deferred to Phase 2):
  - Cross-function calls are treated as opaque (rendered as a
    generic SymPy `Function` with no body — the analyzer profiles
    the call shape, not the callee's expansion).
  - Functions with `while` / mutation / `let mut` produce
    `ConvertResult(status="complex_body")` and are not analyzable
    by eml-cost today.
  - String literals don't appear in arithmetic and are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sympy as sp

from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind


@dataclass(frozen=True)
class ConvertResult:
    """One of three outcomes per function."""
    status: str          # "ok" | "tuple" | "complex_body" | "non_arithmetic"
    expression: Any | None = None
    """SymPy expression when status='ok' (single expr) or list of
    SymPy expressions when status='tuple'."""
    note: str = ""


class _Converter:
    """Walks a function body building a SymPy expression."""

    # Map AST node kinds to SymPy callables for the unary-arg builtins.
    _UNARY_BUILTIN_TO_SYMPY = {
        NodeKind.EXP:   sp.exp,
        NodeKind.LN:    sp.log,
        NodeKind.SIN:   sp.sin,
        NodeKind.COS:   sp.cos,
        NodeKind.TAN:   sp.tan,
        NodeKind.SQRT:  sp.sqrt,
        NodeKind.ABS:   sp.Abs,
        NodeKind.ASIN:  sp.asin,
        NodeKind.ACOS:  sp.acos,
        NodeKind.ATAN:  sp.atan,
        NodeKind.SINH:  sp.sinh,
        NodeKind.COSH:  sp.cosh,
        NodeKind.TANH:  sp.tanh,
    }

    def __init__(self, params: list[str]):
        # Each param becomes a real-valued SymPy symbol.
        self.symbols: dict[str, sp.Symbol] = {
            name: sp.Symbol(name, real=True) for name in params
        }
        # Let-bindings inline as we walk; values are SymPy expressions.
        self.bindings: dict[str, Any] = dict(self.symbols)

    # ── Public entry ──────────────────────────────────────────

    def convert_function(self, func: EMLFunction) -> ConvertResult:
        """Walk the function body, returning the SymPy expression
        (or tuple of expressions, or a complex-body note)."""
        body = func.body
        if body is None or body.kind != NodeKind.BLOCK:
            return ConvertResult(status="complex_body",
                                 note="no parsed body")

        # Reject early if the body contains mutation or loops.
        if self._has_complex_control_flow(body):
            return ConvertResult(
                status="complex_body",
                note="contains let mut / while / assignment "
                     "(Phase 2 will analyze)",
            )

        final_expr: ASTNode | None = None
        for stmt in body.children:
            if stmt.kind == NodeKind.LET:
                # Inline the let binding into the substitution map.
                rhs = self._convert_expr(stmt.children[0])
                self.bindings[stmt.value] = rhs
            elif stmt.kind == NodeKind.EXPR_STMT:
                # Discarded -- no return value, no profile contribution.
                continue
            else:
                # The final expression of the block.
                final_expr = stmt

        if final_expr is None:
            return ConvertResult(status="non_arithmetic",
                                 note="block has no final expression")

        # Tuple return -- profile each element independently.
        if final_expr.kind == NodeKind.TUPLE:
            sympy_parts = [self._convert_expr(child)
                           for child in final_expr.children]
            return ConvertResult(
                status="tuple", expression=sympy_parts,
                note=f"tuple of {len(sympy_parts)} components",
            )

        sympy_expr = self._convert_expr(final_expr)
        return ConvertResult(status="ok", expression=sympy_expr)

    # ── Helpers ───────────────────────────────────────────────

    def _has_complex_control_flow(self, block: ASTNode) -> bool:
        """True iff the body contains LET_MUT / WHILE / ASSIGN."""
        complex_kinds = {NodeKind.LET_MUT, NodeKind.WHILE, NodeKind.ASSIGN}
        for stmt in block.children:
            if stmt.kind in complex_kinds:
                return True
        return False

    def _convert_expr(self, node: ASTNode) -> Any:
        """Recursive AST -> SymPy converter. Raises ValueError on
        unsupported constructs (caller treats as complex_body)."""
        kind = node.kind

        if kind == NodeKind.LITERAL:
            v = node.value
            if isinstance(v, bool):
                # Booleans don't get analyzed by eml-cost; map to int.
                return sp.Integer(1 if v else 0)
            if isinstance(v, int):
                return sp.Integer(v)
            if isinstance(v, float):
                return sp.Float(v)
            raise ValueError(f"unsupported literal type: {type(v).__name__}")

        if kind == NodeKind.VAR:
            name = node.value
            if name in self.bindings:
                return self.bindings[name]
            # Free variable -- introduce a fresh real symbol so analyze
            # can still process the expression. Common case: module-
            # level constants referenced in fn bodies.
            sym = sp.Symbol(name, real=True)
            self.bindings[name] = sym
            return sym

        if kind == NodeKind.UNARYOP:
            sub = self._convert_expr(node.children[0])
            if node.value == "-":
                return -sub
            if node.value == "!":
                # Logical not -- map to (1 - x) for analyzer purposes.
                return sp.Integer(1) - sub
            raise ValueError(f"unsupported unary op: {node.value!r}")

        if kind == NodeKind.BINOP:
            left = self._convert_expr(node.children[0])
            right = self._convert_expr(node.children[1])
            op = node.value
            if op == "+":  return left + right
            if op == "-":  return left - right
            if op == "*":  return left * right
            if op == "/":  return left / right
            # Comparisons + boolean ops -- not arithmetic, but the
            # analyzer can handle them in domain predicates. Map to
            # something sane.
            if op == "==": return sp.Eq(left, right)
            if op == "!=": return sp.Ne(left, right)
            if op == "<":  return sp.Lt(left, right)
            if op == ">":  return sp.Gt(left, right)
            if op == "<=": return sp.Le(left, right)
            if op == ">=": return sp.Ge(left, right)
            if op == "&&": return sp.And(left, right)
            if op == "||": return sp.Or(left, right)
            raise ValueError(f"unsupported binop: {op!r}")

        # Built-in unary functions
        if kind in self._UNARY_BUILTIN_TO_SYMPY:
            sympy_fn = self._UNARY_BUILTIN_TO_SYMPY[kind]
            arg = self._convert_expr(node.children[0])
            return sympy_fn(arg)

        # POW(x, y)
        if kind == NodeKind.POW:
            base = self._convert_expr(node.children[0])
            exponent = self._convert_expr(node.children[1])
            return sp.Pow(base, exponent)

        # EML(x, y) = exp(x) - ln(y)
        if kind == NodeKind.EML:
            x = self._convert_expr(node.children[0])
            y = self._convert_expr(node.children[1])
            return sp.exp(x) - sp.log(y)

        # CLAMP(x, lo, hi) -- approximate as min(max(x, lo), hi).
        # Analyzer treats Min/Max as opaque, but the expression survives.
        if kind == NodeKind.CLAMP:
            x = self._convert_expr(node.children[0])
            lo = self._convert_expr(node.children[1])
            hi = self._convert_expr(node.children[2])
            return sp.Min(sp.Max(x, lo), hi)

        # CALL -- user function. Render as an opaque sympy.Function so
        # the expression structure is preserved.
        if kind == NodeKind.CALL:
            fn = sp.Function(node.value)
            args = [self._convert_expr(c) for c in node.children]
            return fn(*args)

        # Tuple in a non-final position would be unusual; if it
        # happens, take the first element (rough heuristic).
        if kind == NodeKind.TUPLE:
            return self._convert_expr(node.children[0])

        raise ValueError(f"unsupported AST kind: {kind}")


# ── Public entrypoint ────────────────────────────────────────────────

def convert_function_body(func: EMLFunction) -> ConvertResult:
    """Public entry: convert one EMLFunction's body into a SymPy
    expression (or report complex_body / tuple)."""
    param_names = [p.name for p in func.params]
    return _Converter(param_names).convert_function(func)
