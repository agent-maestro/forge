"""SymPy -> EML AST converter (the inverse of `ast_to_sympy`).

Used by the SuperBEST routing pass: after `eml_cost.canonicalize`
returns a more numerically-stable SymPy form, we need to lower
that form back into the EML AST so the C / Rust / Verilog
backends can emit it.

Scope is intentionally narrow -- only the SymPy node kinds that
canonicalize() can produce. If `canonicalize` ever starts
emitting something we don't recognise, sympy_to_ast raises
ConversionError and the SuperBEST pass falls back to leaving
the original AST alone.
"""

from __future__ import annotations

import sympy as sp

from lang.parser.ast_nodes import ASTNode, NodeKind


class ConversionError(RuntimeError):
    """Raised when a SymPy node has no EML-AST equivalent."""


# SymPy class -> NodeKind for the unary builtins.
_SYMPY_TO_BUILTIN: dict[type, NodeKind] = {
    sp.exp:   NodeKind.EXP,
    sp.log:   NodeKind.LN,
    sp.sin:   NodeKind.SIN,
    sp.cos:   NodeKind.COS,
    sp.tan:   NodeKind.TAN,
    sp.asin:  NodeKind.ASIN,
    sp.acos:  NodeKind.ACOS,
    sp.atan:  NodeKind.ATAN,
    sp.sinh:  NodeKind.SINH,
    sp.cosh:  NodeKind.COSH,
    sp.tanh:  NodeKind.TANH,
}


def sympy_to_ast(expr: sp.Basic) -> ASTNode:
    """Lower a SymPy expression into an equivalent EML ASTNode."""
    return _convert(sp.sympify(expr))


def _convert(expr: sp.Basic) -> ASTNode:
    # Literals: integers, floats, named numeric constants.
    if isinstance(expr, sp.Integer):
        return ASTNode(kind=NodeKind.LITERAL, value=int(expr))
    if isinstance(expr, sp.Float):
        return ASTNode(kind=NodeKind.LITERAL, value=float(expr))
    if isinstance(expr, sp.Rational):
        # Render as a divide of two literal integers so backends
        # that don't have rational literal support still work.
        return ASTNode(
            kind=NodeKind.BINOP, value="/",
            children=[
                ASTNode(kind=NodeKind.LITERAL, value=int(expr.p)),
                ASTNode(kind=NodeKind.LITERAL, value=int(expr.q)),
            ],
        )
    if expr is sp.S.NegativeOne:
        return ASTNode(kind=NodeKind.LITERAL, value=-1)
    if expr is sp.S.Zero:
        return ASTNode(kind=NodeKind.LITERAL, value=0)
    if expr is sp.S.One:
        return ASTNode(kind=NodeKind.LITERAL, value=1)
    if expr is sp.S.Half:
        return ASTNode(kind=NodeKind.LITERAL, value=0.5)

    # Symbols become VAR.
    if isinstance(expr, sp.Symbol):
        return ASTNode(kind=NodeKind.VAR, value=str(expr))

    # Add / Mul -- left-fold into binops.
    if isinstance(expr, sp.Add):
        return _left_fold("+", [_convert(a) for a in expr.args])
    if isinstance(expr, sp.Mul):
        return _left_fold("*", [_convert(a) for a in expr.args])

    # Pow with integer exponent -> repeated multiply for small cases,
    # CALL pow(...) otherwise.
    if isinstance(expr, sp.Pow):
        base = _convert(expr.base)
        exp_arg = expr.exp
        if isinstance(exp_arg, sp.Integer) and 1 <= int(exp_arg) <= 4:
            n = int(exp_arg)
            out = base
            for _ in range(n - 1):
                out = ASTNode(
                    kind=NodeKind.BINOP, value="*",
                    children=[out, _convert(expr.base)],
                )
            return out
        if isinstance(exp_arg, sp.Integer) and int(exp_arg) == -1:
            # x^-1 -> 1 / x
            return ASTNode(
                kind=NodeKind.BINOP, value="/",
                children=[
                    ASTNode(kind=NodeKind.LITERAL, value=1),
                    base,
                ],
            )
        # General case: pow(base, exp).
        return ASTNode(
            kind=NodeKind.POW, value="pow",
            children=[base, _convert(exp_arg)],
        )

    # Builtin transcendentals.
    if isinstance(expr, sp.Function):
        kind = _SYMPY_TO_BUILTIN.get(type(expr))
        if kind is not None and len(expr.args) == 1:
            return ASTNode(
                kind=kind, value=kind.value,
                children=[_convert(expr.args[0])],
            )
        # sqrt is sp.Pow(x, 1/2); canonicalize sometimes
        # represents it as sp.sqrt(x), which is also a Function.
        if isinstance(expr, sp.functions.elementary.miscellaneous.Min):
            # Min(...) -> nested min(min(...)) -- not handled today.
            raise ConversionError("Min() unsupported by sympy_to_ast")
        if isinstance(expr, sp.functions.elementary.miscellaneous.Max):
            raise ConversionError("Max() unsupported by sympy_to_ast")

    raise ConversionError(
        f"sympy_to_ast: unsupported {type(expr).__name__} expression "
        f"{expr!r}"
    )


def _left_fold(op: str, terms: list[ASTNode]) -> ASTNode:
    """Combine `terms` into a left-associative binop chain."""
    if len(terms) == 1:
        return terms[0]
    out = terms[0]
    for t in terms[1:]:
        out = ASTNode(kind=NodeKind.BINOP, value=op, children=[out, t])
    return out
