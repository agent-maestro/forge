"""Direct tree-walking interpreter for EML-lang function bodies.

Phase 2.5 control-flow path: where `ast_to_sympy.convert_function_body`
returns `status="complex_body"` (because the body uses `let mut`,
`while`, or `assign`) the SymPy bridge cannot lambdify it. This
module provides a fallback that evaluates the AST directly in
Python -- handling the imperative constructs SymPy can't model.

The interpreter is intentionally narrow: it is for the equivalence
harness's reference path (the gold standard against which compiled
backends are checked). It is NOT for runtime use; the C / Rust /
LLVM emitters remain the production path. Performance and tail-
recursion limits live in the backends, not here.

Capabilities:
  - Arithmetic + transcendental builtins (delegated to `math`).
  - `let` / `let mut` / `assign` -- a single environment dict.
  - `while` with a configurable iteration cap (`MAX_ITERS`) to
    prevent runaway loops.
  - User function calls via a name -> callable resolver table
    (passed by the harness; same shape as the SymPy bridge's
    `callee_table`).
  - Tuple returns -- evaluated component-wise.

Out of scope for now:
  - `if` / `else` (the parser currently only ships while + assign;
    branching arrives later). When it lands, add a NodeKind.IF case
    in `_exec_block`.
  - Recursion control: depth tracked at the call boundary;
    `MAX_CALL_DEPTH` aborts pathological cases.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind


class InterpreterError(RuntimeError):
    """Raised when the interpreter encounters an unsupported construct
    or exceeds an iteration / recursion cap."""


# Per-while-loop cap. Set high enough that genuine algorithms (Newton
# iteration, fixed-point solvers) finish, but low enough that an
# unintended infinite loop fails fast in tests.
MAX_ITERS = 10_000

# Function call recursion cap.
MAX_CALL_DEPTH = 64


# ── Builtin transcendentals -------------------------------------------------

_UNARY_BUILTIN_TO_PY: dict[NodeKind, Callable[[float], float]] = {
    NodeKind.EXP:   math.exp,
    NodeKind.LN:    math.log,
    NodeKind.SIN:   math.sin,
    NodeKind.COS:   math.cos,
    NodeKind.TAN:   math.tan,
    NodeKind.SQRT:  math.sqrt,
    NodeKind.ABS:   abs,
    NodeKind.ASIN:  math.asin,
    NodeKind.ACOS:  math.acos,
    NodeKind.ATAN:  math.atan,
    NodeKind.SINH:  math.sinh,
    NodeKind.COSH:  math.cosh,
    NodeKind.TANH:  math.tanh,
    NodeKind.FLOOR: math.floor,
}


# ── Public API --------------------------------------------------------------


def run_function(
    func: EMLFunction,
    args: tuple[Any, ...],
    *,
    constants: dict[str, Any] | None = None,
    callees: dict[str, Callable[..., Any]] | None = None,
    _depth: int = 0,
) -> Any:
    """Evaluate `func` at `args`. Returns a scalar or a tuple.

    `constants` -- module-level `const NAME = X;` table inlined as
    initial bindings.

    `callees` -- name -> callable resolver for sibling user
    functions invoked via NodeKind.CALL.
    """
    if _depth > MAX_CALL_DEPTH:
        raise InterpreterError(
            f"call depth exceeded {MAX_CALL_DEPTH} in {func.name!r}")
    if func.is_extern:
        raise InterpreterError(
            f"cannot interpret extern fn {func.name!r} -- no body")
    if func.body is None or func.body.kind != NodeKind.BLOCK:
        raise InterpreterError(
            f"{func.name!r} has no parseable body block")
    if len(args) != len(func.params):
        raise InterpreterError(
            f"{func.name!r} expects {len(func.params)} args, got {len(args)}")

    env: dict[str, Any] = {}
    if constants:
        env.update(constants)
    for param, value in zip(func.params, args):
        env[param.name] = value
    return _exec_block(
        func.body, env,
        callees=callees or {},
        depth=_depth,
    )


# ── Block + statement execution --------------------------------------------


def _exec_block(
    block: ASTNode,
    env: dict[str, Any],
    *,
    callees: dict[str, Callable[..., Any]],
    depth: int,
) -> Any:
    """Execute a BLOCK node. Returns the value of the final expression
    (or None when the block is statement-only)."""
    last: Any = None
    for stmt in block.children:
        kind = stmt.kind
        if kind == NodeKind.LET or kind == NodeKind.LET_MUT:
            env[stmt.value] = _eval_expr(
                stmt.children[0], env, callees=callees, depth=depth)
        elif kind == NodeKind.ASSIGN:
            if stmt.value not in env:
                raise InterpreterError(
                    f"assign to unbound name {stmt.value!r}")
            env[stmt.value] = _eval_expr(
                stmt.children[0], env, callees=callees, depth=depth)
        elif kind == NodeKind.WHILE:
            cond_node, body_node = stmt.children[0], stmt.children[1]
            iters = 0
            while _eval_expr(cond_node, env,
                             callees=callees, depth=depth):
                _exec_block(body_node, env,
                            callees=callees, depth=depth)
                iters += 1
                if iters >= MAX_ITERS:
                    raise InterpreterError(
                        f"while loop exceeded {MAX_ITERS} iterations")
        elif kind == NodeKind.EXPR_STMT:
            _eval_expr(stmt.children[0], env,
                       callees=callees, depth=depth)
        else:
            # Final expression of the block.
            last = _eval_expr(stmt, env, callees=callees, depth=depth)
    return last


# ── Expression evaluation --------------------------------------------------


def _eval_expr(
    node: ASTNode,
    env: dict[str, Any],
    *,
    callees: dict[str, Callable[..., Any]],
    depth: int,
) -> Any:
    kind = node.kind

    if kind == NodeKind.LITERAL:
        return node.value

    if kind == NodeKind.VAR:
        name = node.value
        if name not in env:
            raise InterpreterError(f"unbound variable {name!r}")
        return env[name]

    if kind == NodeKind.UNARYOP:
        sub = _eval_expr(node.children[0], env,
                         callees=callees, depth=depth)
        if node.value == "-": return -sub
        if node.value == "!": return not bool(sub)
        raise InterpreterError(f"unsupported unary op {node.value!r}")

    if kind == NodeKind.BINOP:
        l = _eval_expr(node.children[0], env, callees=callees, depth=depth)
        r = _eval_expr(node.children[1], env, callees=callees, depth=depth)
        op = node.value
        if op == "+":  return l + r
        if op == "-":  return l - r
        if op == "*":  return l * r
        if op == "/":  return l / r
        if op == "==": return l == r
        if op == "!=": return l != r
        if op == "<":  return l < r
        if op == ">":  return l > r
        if op == "<=": return l <= r
        if op == ">=": return l >= r
        if op == "&&": return bool(l) and bool(r)
        if op == "||": return bool(l) or bool(r)
        raise InterpreterError(f"unsupported binop {op!r}")

    if kind in _UNARY_BUILTIN_TO_PY:
        arg = _eval_expr(node.children[0], env,
                         callees=callees, depth=depth)
        return _UNARY_BUILTIN_TO_PY[kind](arg)

    if kind == NodeKind.POW:
        base = _eval_expr(node.children[0], env,
                          callees=callees, depth=depth)
        exponent = _eval_expr(node.children[1], env,
                              callees=callees, depth=depth)
        return math.pow(base, exponent)

    if kind == NodeKind.EML:
        # eml(x, y) = exp(x) - ln(y)
        x = _eval_expr(node.children[0], env,
                       callees=callees, depth=depth)
        y = _eval_expr(node.children[1], env,
                       callees=callees, depth=depth)
        return math.exp(x) - math.log(y)

    if kind == NodeKind.CLAMP:
        x = _eval_expr(node.children[0], env,
                       callees=callees, depth=depth)
        lo = _eval_expr(node.children[1], env,
                        callees=callees, depth=depth)
        hi = _eval_expr(node.children[2], env,
                        callees=callees, depth=depth)
        return min(max(x, lo), hi)

    if kind == NodeKind.CALL:
        name = node.value
        if name not in callees:
            raise InterpreterError(
                f"call to unknown function {name!r}")
        args = tuple(
            _eval_expr(c, env, callees=callees, depth=depth)
            for c in node.children
        )
        return callees[name](*args)

    if kind == NodeKind.TUPLE:
        return tuple(
            _eval_expr(c, env, callees=callees, depth=depth)
            for c in node.children
        )

    raise InterpreterError(f"unsupported AST kind in expr position: {kind}")
