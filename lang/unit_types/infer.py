"""Bottom-up unit inference for EML-lang AST expressions (Phase B).

`infer_expr` walks an `ASTNode` and returns the inferred `Unit` (or
`UnitVar` for polymorphic untagged literals).  The caller provides a
`TypeEnv` mapping variable names to their resolved `Unit`.

Design
------
- Untagged numeric literals produce `UnitVar()`.  When a `UnitVar` is
  combined with a concrete `Unit`, the concrete unit "wins" (the literal
  coerces).  Two `UnitVar`s combined remain `UnitVar`.
- `let` bindings add their inferred unit to the env so subsequent
  references carry the correct unit.
- The function is purely functional with respect to the env; callers
  must pass an extended env dict when entering scopes.

Key invariants
--------------
- Addition / subtraction / comparisons require dimensionally equal operands
  (after coercing UnitVars).
- Multiplication / division compose units multiplicatively.
- Transcendentals (sin, cos, tan, exp, ln, sqrt, asin, acos, atan,
  sinh, cosh, tanh) require dimensionless (or rad) input and return
  dimensionless (or rad for inverse-trig).
- abs preserves the operand's unit.
- clamp / min / max require all non-UnitVar arguments to be dimensionally
  equal; the result carries that unit.
- pow(b, e): if b has non-zero units, e must be an integer literal.
"""

from __future__ import annotations

from typing import Union

from lang.parser.ast_nodes import ASTNode, NodeKind
from lang.unit_types.unit import DIMENSIONLESS, Unit, UnitVar, UnitOrVar
from lang.unit_types.diagnostics import UnitTypeError


# Type environment: variable name -> Unit (or UnitVar for polymorphic bindings)
TypeEnv = dict[str, UnitOrVar]


# ── Helpers ───────────────────────────────────────────────────────────


def _is_unitvar(u: UnitOrVar) -> bool:
    return isinstance(u, UnitVar)


def _coerce(a: UnitOrVar, b: UnitOrVar) -> tuple[Unit | None, Unit | None]:
    """Given two units (possibly UnitVar), return the concrete pair after coercion.

    Rules:
    - UnitVar + concrete -> concrete + concrete
    - concrete + UnitVar -> concrete + concrete
    - UnitVar + UnitVar -> None + None  (both remain polymorphic)
    - concrete + concrete -> as-is
    """
    if _is_unitvar(a) and _is_unitvar(b):
        return None, None
    if _is_unitvar(a):
        return b, b  # type: ignore[return-value]
    if _is_unitvar(b):
        return a, a  # type: ignore[return-value]
    return a, b  # type: ignore[return-value]


def _require_dimensionless(
    unit: UnitOrVar,
    fn_name: str,
    node: ASTNode,
) -> None:
    """Raise UnitTypeError if unit is not dimensionless (or UnitVar)."""
    if _is_unitvar(unit):
        return  # literal 0.5, etc. -- ok
    assert isinstance(unit, Unit)
    if not unit.is_dimensionless() and not (
        # rad is the only non-dimensionless base that some trig accepts
        # (handled per-function in the callers, not here)
        False
    ):
        raise UnitTypeError(
            f"{fn_name}() requires a dimensionless argument, "
            f"but got Real[{unit.display()}]; "
            f"only dimensionless (Real or Real[1]) or Real[rad] inputs are allowed",
            node.line,
            node.col,
        )


def _require_dimensionless_strict(
    unit: UnitOrVar,
    fn_name: str,
    node: ASTNode,
) -> None:
    """Raise UnitTypeError if unit is not dimensionless (rad NOT accepted)."""
    if _is_unitvar(unit):
        return
    assert isinstance(unit, Unit)
    if not unit.is_dimensionless():
        raise UnitTypeError(
            f"{fn_name}() requires a dimensionless argument, "
            f"but got Real[{unit.display()}]; "
            f"use exp(e * ln(b)) if you need exponentiation of a dimensional value",
            node.line,
            node.col,
        )


# ── Main inference function ────────────────────────────────────────────


def infer_expr(
    node: ASTNode,
    env: TypeEnv,
    fn_registry: dict[str, "FnSignature"] | None = None,  # noqa: F821
) -> UnitOrVar:
    """Infer the unit of `node` given the type environment `env`.

    Parameters
    ----------
    node : ASTNode
        The expression to type-check.
    env : TypeEnv
        Mapping of variable names to their units.
    fn_registry : dict[str, FnSignature] | None
        Optional mapping of user-function names to their signatures,
        for call-site checking.  Pass None to skip call checking.

    Returns
    -------
    UnitOrVar
        The inferred unit, or UnitVar() for polymorphic expressions.

    Raises
    ------
    UnitTypeError
        On any dimensional mismatch.
    """
    kind = node.kind

    # ── Literals ─────────────────────────────────────────────
    if kind == NodeKind.LITERAL:
        return UnitVar()

    # ── Variable references ───────────────────────────────────
    if kind == NodeKind.VAR:
        name = node.value
        if name in env:
            return env[name]
        # Unknown variable -- treat as dimensionless (constants resolved
        # separately, or forward reference).
        return DIMENSIONLESS

    # ── Unary operator ────────────────────────────────────────
    if kind == NodeKind.UNARYOP:
        operand_unit = infer_expr(node.children[0], env, fn_registry)
        # Unary minus / not: preserve unit.
        return operand_unit

    # ── Binary operators ──────────────────────────────────────
    if kind == NodeKind.BINOP:
        op = node.value
        left = infer_expr(node.children[0], env, fn_registry)
        right = infer_expr(node.children[1], env, fn_registry)

        if op in ("+", "-"):
            # Operands must be dimensionally equal.
            cl, cr = _coerce(left, right)
            if cl is None:
                # Both UnitVar -- stays polymorphic.
                return UnitVar()
            if not cl.equals_dimensionally(cr):  # type: ignore[union-attr]
                raise UnitTypeError(
                    f"cannot {('add' if op == '+' else 'subtract')} "
                    f"Real[{cl.display()}] and Real[{cr.display()}]; "  # type: ignore[union-attr]
                    f"units must match",
                    node.line,
                    node.col,
                )
            return cl

        if op == "*":
            if _is_unitvar(left) and _is_unitvar(right):
                return UnitVar()
            if _is_unitvar(left):
                return right  # literal * x -> x's unit (literal coerces to dimensionless)
            if _is_unitvar(right):
                return left   # x * literal -> x's unit (literal coerces to dimensionless)
            assert isinstance(left, Unit) and isinstance(right, Unit)
            return left * right

        if op == "/":
            if _is_unitvar(left) and _is_unitvar(right):
                return UnitVar()
            if _is_unitvar(left) and isinstance(right, Unit):
                # literal / x[U] -> 1/U (literal treated as dimensionless numerator)
                return DIMENSIONLESS / right
            if isinstance(left, Unit) and _is_unitvar(right):
                # x[U] / literal -> x[U] (literal coerces to dimensionless, F# rule).
                # Symmetric with multiplication. Untagged literals are dimensionless;
                # to express a same-unit divisor (e.g. speed of light), declare it
                # as a unit-tagged const: `const C: Real[m/s] = 299792458.0`.
                return left
            assert isinstance(left, Unit) and isinstance(right, Unit)
            return left / right

        if op in ("==", "!=", "<", ">", "<=", ">="):
            # Comparison: operands must be dimensionally equal.
            cl, cr = _coerce(left, right)
            if cl is not None:
                if not cl.equals_dimensionally(cr):  # type: ignore[union-attr]
                    raise UnitTypeError(
                        f"cannot compare Real[{cl.display()}] and "  # type: ignore[union-attr]
                        f"Real[{cr.display()}]; units must match",  # type: ignore[union-attr]
                        node.line,
                        node.col,
                    )
            # Comparison always returns a dimensionless (boolean) value.
            return DIMENSIONLESS

        if op in ("&&", "||"):
            return DIMENSIONLESS

        return DIMENSIONLESS  # fallback for unknown ops

    # ── Transcendentals that require dimensionless input ──────

    if kind in (NodeKind.EXP, NodeKind.LN, NodeKind.SQRT,
                NodeKind.SINH, NodeKind.COSH, NodeKind.TANH):
        fn_name = kind.value
        arg_unit = infer_expr(node.children[0], env, fn_registry)
        _require_dimensionless_strict(arg_unit, fn_name, node)
        return DIMENSIONLESS

    # sin / cos / tan accept dimensionless OR rad; return dimensionless.
    if kind in (NodeKind.SIN, NodeKind.COS, NodeKind.TAN):
        fn_name = kind.value
        arg_unit = infer_expr(node.children[0], env, fn_registry)
        if not _is_unitvar(arg_unit):
            assert isinstance(arg_unit, Unit)
            rad_unit = Unit(base=(0, 0, 0, 0, 0, 0, 0, 1), scale=1.0, name="rad")
            if not arg_unit.is_dimensionless() and not arg_unit.equals_dimensionally(rad_unit):
                raise UnitTypeError(
                    f"{fn_name}() requires a dimensionless or Real[rad] argument, "
                    f"but got Real[{arg_unit.display()}]",
                    node.line,
                    node.col,
                )
        return DIMENSIONLESS

    # asin / acos / atan: dimensionless input -> rad output.
    if kind in (NodeKind.ASIN, NodeKind.ACOS, NodeKind.ATAN):
        fn_name = kind.value
        arg_unit = infer_expr(node.children[0], env, fn_registry)
        _require_dimensionless_strict(arg_unit, fn_name, node)
        return Unit(base=(0, 0, 0, 0, 0, 0, 0, 1), scale=1.0, name="rad")

    # ── abs ───────────────────────────────────────────────────
    if kind == NodeKind.ABS:
        arg_unit = infer_expr(node.children[0], env, fn_registry)
        return arg_unit

    # ── clamp(v, lo, hi) ──────────────────────────────────────
    if kind == NodeKind.CLAMP:
        v_unit = infer_expr(node.children[0], env, fn_registry)
        lo_unit = infer_expr(node.children[1], env, fn_registry)
        hi_unit = infer_expr(node.children[2], env, fn_registry)

        # Determine the concrete unit (any non-UnitVar wins).
        concrete: Unit | None = None
        for u in (v_unit, lo_unit, hi_unit):
            if not _is_unitvar(u):
                concrete = u  # type: ignore[assignment]
                break

        if concrete is not None:
            for u in (v_unit, lo_unit, hi_unit):
                if not _is_unitvar(u) and isinstance(u, Unit):
                    if not u.equals_dimensionally(concrete):
                        raise UnitTypeError(
                            f"clamp() arguments must all have the same unit; "
                            f"got Real[{concrete.display()}] and Real[{u.display()}]",
                            node.line,
                            node.col,
                        )
            return concrete
        return UnitVar()

    # ── pow(b, e) ─────────────────────────────────────────────
    if kind == NodeKind.POW:
        base_unit = infer_expr(node.children[0], env, fn_registry)
        exp_node = node.children[1]

        if _is_unitvar(base_unit) or (isinstance(base_unit, Unit) and base_unit.is_dimensionless()):
            # Dimensionless base -- any exponent is fine.
            return DIMENSIONLESS

        # base has nonzero units -- exponent must be an integer literal.
        assert isinstance(base_unit, Unit)
        if exp_node.kind != NodeKind.LITERAL:
            raise UnitTypeError(
                f"pow() with a dimensional base Real[{base_unit.display()}] "
                f"requires an integer literal exponent; "
                f"got a non-literal exponent -- use pow(b, 2) not pow(b, e)",
                node.line,
                node.col,
            )
        exp_val = exp_node.value
        if not isinstance(exp_val, int) and (isinstance(exp_val, float) and exp_val != int(exp_val)):
            raise UnitTypeError(
                f"pow() with a dimensional base Real[{base_unit.display()}] "
                f"requires an integer exponent, but got {exp_val!r}; "
                f"for fractional powers of a dimensional value, use "
                f"exp(e * ln(b)) after ensuring dimensional consistency",
                node.line,
                node.col,
            )
        exp_int = int(exp_val)
        return base_unit ** exp_int

    # ── eml (EML-cost transcendental) ──────────────────────────
    if kind == NodeKind.EML:
        return DIMENSIONLESS

    # ── Tuple ────────────────────────────────────────────────
    if kind == NodeKind.TUPLE:
        # Return UnitVar for tuples -- checked per-element by callers.
        return UnitVar()

    # ── User-defined function call ────────────────────────────
    if kind == NodeKind.CALL:
        fn_name = node.value
        if fn_registry and fn_name in fn_registry:
            sig = fn_registry[fn_name]
            # Check argument units.
            for i, (arg, param_unit) in enumerate(
                zip(node.children, sig.param_units)
            ):
                arg_unit = infer_expr(arg, env, fn_registry)
                ca, cp = _coerce(arg_unit, param_unit)
                if ca is not None and not ca.equals_dimensionally(cp):  # type: ignore[union-attr]
                    raise UnitTypeError(
                        f"argument {i+1} of {fn_name}() has unit "
                        f"Real[{ca.display()}] but the parameter expects "  # type: ignore[union-attr]
                        f"Real[{cp.display()}]",  # type: ignore[union-attr]
                        node.line,
                        node.col,
                    )
            return sig.return_unit
        return DIMENSIONLESS

    # ── Block ─────────────────────────────────────────────────
    if kind == NodeKind.BLOCK:
        return _infer_block(node, env, fn_registry)

    # ── Let bindings ──────────────────────────────────────────
    if kind in (NodeKind.LET, NodeKind.LET_MUT):
        # Let itself returns the unit of its rhs -- but this is handled
        # inside _infer_block, not here directly.
        return infer_expr(node.children[0], env, fn_registry)

    # ── Assignment ────────────────────────────────────────────
    if kind == NodeKind.ASSIGN:
        return infer_expr(node.children[0], env, fn_registry)

    # ── Expr statement ────────────────────────────────────────
    if kind == NodeKind.EXPR_STMT:
        return infer_expr(node.children[0], env, fn_registry)

    # ── While loop ────────────────────────────────────────────
    if kind == NodeKind.WHILE:
        infer_expr(node.children[0], env, fn_registry)  # cond
        infer_expr(node.children[1], env, fn_registry)  # body
        return DIMENSIONLESS

    return DIMENSIONLESS


def _infer_block(
    block: ASTNode,
    env: TypeEnv,
    fn_registry: dict | None,
) -> UnitOrVar:
    """Infer the unit of a BLOCK node.

    Processes each statement in order, extending the env for let
    bindings.  Returns the unit of the final expression.
    """
    local_env = dict(env)  # mutable copy; does not mutate callers' env
    last_unit: UnitOrVar = DIMENSIONLESS

    for child in block.children:
        if child.kind in (NodeKind.LET, NodeKind.LET_MUT):
            rhs_unit = infer_expr(child.children[0], local_env, fn_registry)
            local_env[child.value] = rhs_unit
            last_unit = rhs_unit
        elif child.kind == NodeKind.ASSIGN:
            rhs_unit = infer_expr(child.children[0], local_env, fn_registry)
            if child.value in local_env:
                local_env[child.value] = rhs_unit
            last_unit = rhs_unit
        elif child.kind == NodeKind.EXPR_STMT:
            infer_expr(child.children[0], local_env, fn_registry)
            # expr-stmts don't contribute the final value
        elif child.kind == NodeKind.WHILE:
            infer_expr(child, local_env, fn_registry)
        else:
            # Final expression of block
            last_unit = infer_expr(child, local_env, fn_registry)

    return last_unit


# ── Signature record ──────────────────────────────────────────────────


class FnSignature:
    """Resolved signature for a user-defined function."""

    __slots__ = ("param_units", "return_unit")

    def __init__(self, param_units: list[UnitOrVar], return_unit: UnitOrVar) -> None:
        self.param_units = param_units
        self.return_unit = return_unit
