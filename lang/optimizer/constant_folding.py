"""Constant-folding optimisation pass.

Walks an EML AST and evaluates pure-literal sub-trees at compile
time. The resulting AST is semantically equivalent to the input
but smaller and (for constant initialisers) faster. Folded
constants don't need MAC units on the FPGA backend, so this also
reduces resource demand.

Folding rules:

  - LITERAL / VAR: passthrough.
  - UNARYOP on a numeric literal: `-3` -> -3, `!true` -> false.
  - BINOP on two numeric literals: `1 + 2` -> 3, `2.0 * 3.0` -> 6.0,
    comparisons -> booleans, boolean ops on bool literals.
  - Algebraic identities (only when at least one operand is a
    literal so the AST never grows):
        x + 0  -> x        x * 1 -> x        x * 0 -> 0
        0 + x  -> x        1 * x -> x        0 * x -> 0
        x - 0  -> x        x / 1 -> x
  - Builtin transcendentals on a literal argument:
        exp(0) -> 1.0      sin(0) -> 0.0     cos(0) -> 1.0
        ln(1)  -> 0.0      sqrt(0) -> 0.0    sqrt(1) -> 1.0
        abs(c), clamp(c, lo, hi), pow(b, e), eml(x, y) when
        all-literal.

Numeric semantics: Python's float arithmetic. Division by zero
is NOT folded -- we keep the original node so the runtime
handles it the way each backend documents.

Idempotence: `fold(fold(x))` returns the same shape as `fold(x)`.
"""

from __future__ import annotations

import math
from copy import deepcopy

from lang.parser.ast_nodes import ASTNode, NodeKind


# Builtins we know how to evaluate at compile time when the
# argument is itself a numeric literal.
_BUILTIN_EVAL = {
    NodeKind.EXP:   math.exp,
    NodeKind.LN:    math.log,
    NodeKind.SIN:   math.sin,
    NodeKind.COS:   math.cos,
    NodeKind.TAN:   math.tan,
    NodeKind.SQRT:  math.sqrt,
    NodeKind.ABS:   abs,
    NodeKind.SINH:  math.sinh,
    NodeKind.COSH:  math.cosh,
    NodeKind.TANH:  math.tanh,
    NodeKind.ASIN:  math.asin,
    NodeKind.ACOS:  math.acos,
    NodeKind.ATAN:  math.atan,
    NodeKind.FLOOR: math.floor,
}


def fold_constants(node: ASTNode) -> ASTNode:
    """Return a new AST with literal sub-trees evaluated.

    Caller-friendly entrypoint: deep-copies the input so the
    original AST is never mutated. Use `fold_in_place(node)` if
    you don't need that guarantee."""
    return _fold(deepcopy(node))


def fold_in_place(node: ASTNode) -> ASTNode:
    """Same as `fold_constants` but mutates the input. Returns
    the (possibly replaced) root node."""
    return _fold(node)


# ── Implementation ───────────────────────────────────────────


def _fold(node: ASTNode) -> ASTNode:
    # Recurse first: we want fully-folded children before applying
    # any rule to the parent node.
    node.children = [_fold(c) for c in node.children]

    k = node.kind
    if k == NodeKind.LITERAL or k == NodeKind.VAR:
        return node

    if k == NodeKind.UNARYOP:
        return _fold_unary(node)

    if k == NodeKind.BINOP:
        return _fold_binop(node)

    if k in _BUILTIN_EVAL:
        return _fold_builtin(node)

    if k == NodeKind.CLAMP:
        return _fold_clamp(node)

    if k == NodeKind.POW:
        return _fold_pow(node)

    if k == NodeKind.EML:
        return _fold_eml(node)

    return node


def _is_literal(n: ASTNode) -> bool:
    return n.kind == NodeKind.LITERAL


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _lit(value, *, line: int = 0, col: int = 0) -> ASTNode:
    return ASTNode(
        kind=NodeKind.LITERAL, value=value,
        line=line, col=col,
    )


# ── Unary ─────────────────────────────────────────────────────


def _fold_unary(node: ASTNode) -> ASTNode:
    op = node.value
    inner = node.children[0]
    if not _is_literal(inner):
        return node
    v = inner.value
    if op == "-" and _is_num(v):
        return _lit(-v, line=node.line, col=node.col)
    if op == "!" and isinstance(v, bool):
        return _lit(not v, line=node.line, col=node.col)
    return node


# ── BinOp ─────────────────────────────────────────────────────


_NUMERIC_OPS = {
    "+":  lambda a, b: a + b,
    "-":  lambda a, b: a - b,
    "*":  lambda a, b: a * b,
    "/":  lambda a, b: a / b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<":  lambda a, b: a < b,
    ">":  lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
}

_BOOL_OPS = {
    "&&": lambda a, b: a and b,
    "||": lambda a, b: a or b,
}


def _fold_binop(node: ASTNode) -> ASTNode:
    op = node.value
    left, right = node.children

    # Both literals + numeric op.
    if _is_literal(left) and _is_literal(right) and op in _NUMERIC_OPS:
        a, b = left.value, right.value
        if _is_num(a) and _is_num(b):
            if op == "/" and b == 0:
                # Don't fold div-by-zero -- runtime handles it.
                return node
            try:
                result = _NUMERIC_OPS[op](a, b)
            except (ZeroDivisionError, ValueError):
                return node
            return _lit(result, line=node.line, col=node.col)

    # Both bool literals + boolean op.
    if _is_literal(left) and _is_literal(right) and op in _BOOL_OPS:
        a, b = left.value, right.value
        if isinstance(a, bool) and isinstance(b, bool):
            return _lit(
                _BOOL_OPS[op](a, b),
                line=node.line, col=node.col,
            )

    return _algebraic_identity(node, op, left, right)


def _algebraic_identity(node, op, left, right) -> ASTNode:
    """One-side-literal identity rules. Tree never grows."""
    L = left.value if _is_literal(left) and _is_num(left.value) else None
    R = right.value if _is_literal(right) and _is_num(right.value) else None

    if op == "+":
        if R == 0:
            return left
        if L == 0:
            return right
    elif op == "-":
        if R == 0:
            return left
        if L == 0:
            # 0 - x  -> -x : keep as a unary so the AST shape
            # stays predictable.
            return ASTNode(
                kind=NodeKind.UNARYOP, value="-",
                children=[right],
                line=node.line, col=node.col,
            )
    elif op == "*":
        if R == 1:
            return left
        if L == 1:
            return right
        # Multiply by literal 0 collapses -- only when the other
        # operand is side-effect free (a literal, a variable, or
        # a tree of those).
        if R == 0 and _is_safe_to_drop(left):
            return _lit(
                0.0 if isinstance(R, float) else 0,
                line=node.line, col=node.col,
            )
        if L == 0 and _is_safe_to_drop(right):
            return _lit(
                0.0 if isinstance(L, float) else 0,
                line=node.line, col=node.col,
            )
    elif op == "/":
        if R == 1:
            return left

    return node


def _is_safe_to_drop(n: ASTNode) -> bool:
    """True iff evaluating `n` is side-effect free, so we can
    silently discard it under `0 * n`. Conservative: only
    LITERAL + VAR + recursive safe combinations."""
    if n.kind in (NodeKind.LITERAL, NodeKind.VAR):
        return True
    if n.kind in (NodeKind.UNARYOP, NodeKind.BINOP, NodeKind.TUPLE):
        return all(_is_safe_to_drop(c) for c in n.children)
    return False


# ── Builtins ──────────────────────────────────────────────────


def _fold_builtin(node: ASTNode) -> ASTNode:
    fn = _BUILTIN_EVAL[node.kind]
    if len(node.children) != 1:
        return node
    arg = node.children[0]
    if not _is_literal(arg) or not _is_num(arg.value):
        return node
    try:
        result = fn(arg.value)
    except (ValueError, OverflowError, ZeroDivisionError):
        return node
    return _lit(float(result), line=node.line, col=node.col)


def _fold_pow(node: ASTNode) -> ASTNode:
    if len(node.children) != 2:
        return node
    base, exp_arg = node.children
    if (_is_literal(base) and _is_literal(exp_arg)
            and _is_num(base.value) and _is_num(exp_arg.value)):
        try:
            result = math.pow(base.value, exp_arg.value)
        except (ValueError, OverflowError):
            return node
        return _lit(float(result), line=node.line, col=node.col)
    return node


def _fold_clamp(node: ASTNode) -> ASTNode:
    if len(node.children) != 3:
        return node
    x, lo, hi = node.children
    if all(_is_literal(c) and _is_num(c.value) for c in (x, lo, hi)):
        result = max(lo.value, min(hi.value, x.value))
        return _lit(float(result), line=node.line, col=node.col)
    return node


def _fold_eml(node: ASTNode) -> ASTNode:
    """eml(x, y) = exp(x) - ln(y). Fold when both args are literal."""
    if len(node.children) != 2:
        return node
    x, y = node.children
    if (_is_literal(x) and _is_literal(y)
            and _is_num(x.value) and _is_num(y.value)
            and y.value > 0):
        try:
            result = math.exp(x.value) - math.log(y.value)
        except (ValueError, OverflowError):
            return node
        return _lit(float(result), line=node.line, col=node.col)
    return node
