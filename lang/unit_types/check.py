"""Phase B unit type-checker entry point.

`check_module(mod)` is the public API. It:

1. Builds a registry of name->Unit from the module's unit_decls.
2. Resolves all constants' unit annotations.
3. For each function, resolves parameter and return unit annotations,
   builds the TypeEnv, and walks the body + requires/ensures predicates
   with `infer_expr`, checking for dimensional mismatches.
4. Returns the module unchanged (the type-checked AST is the same object;
   backends see zero changes -- unit info is erased for them).

Errors raise `UnitTypeError` with line:col from the AST node where the
mismatch was detected.
"""

from __future__ import annotations

from lang.parser.ast_nodes import (
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLModule,
    NodeKind,
    Param,
)
from lang.unit_types.diagnostics import UnitTypeError
from lang.unit_types.infer import FnSignature, TypeEnv, infer_expr
from lang.unit_types.resolver import build_registry, resolve_unit_expr
from lang.unit_types.unit import DIMENSIONLESS, Unit, UnitOrVar, UnitVar


def check_module(mod: EMLModule) -> EMLModule:
    """Type-check all functions in an EMLModule for dimensional consistency.

    Parameters
    ----------
    mod : EMLModule
        The parsed module to type-check.

    Returns
    -------
    EMLModule
        The same module object, unmodified (backends see no change).

    Raises
    ------
    UnitTypeError
        On the first dimensional mismatch found, with source location.
    """
    # 1. Build the unit registry from declared unit names.
    registry = build_registry(mod.unit_decls)

    # 2. Build a global constant env (name -> unit).
    # Constants without a unit annotation are unit-polymorphic (UnitVar),
    # just like untagged numeric literals.  This lets bare `const PI: Real = 3.14`
    # appear next to a Real[rad] value without triggering a type error -- the
    # constant coerces to whatever unit context it's used in.
    const_env: TypeEnv = {}
    for const in mod.constants:
        if const.unit_expr is None:
            const_env[const.name] = UnitVar()
        else:
            unit = resolve_unit_expr(
                const.unit_expr, registry, line=const.line, col=const.col
            )
            const_env[const.name] = unit

    # 3. Build a function-signature registry for call-site checking.
    #    We need a two-pass approach: first collect signatures, then check bodies.
    fn_registry: dict[str, FnSignature] = {}
    for fn in mod.functions:
        sig = _build_signature(fn, registry)
        fn_registry[fn.name] = sig

    # 4. Check each function body + predicates.
    for fn in mod.functions:
        if fn.body is None:
            continue  # extern fn -- no body to check
        _check_function(fn, registry, const_env, fn_registry)

    return mod


# ── Helpers ───────────────────────────────────────────────────────────


def _resolve_or_dimensionless(
    unit_expr: str | None,
    registry: dict[str, Unit],
    line: int,
    col: int,
) -> UnitOrVar:
    """Return dimensionless if unit_expr is None, otherwise resolve it."""
    if unit_expr is None:
        return DIMENSIONLESS
    return resolve_unit_expr(unit_expr, registry, line=line, col=col)


def _build_signature(fn: EMLFunction, registry: dict[str, Unit]) -> FnSignature:
    """Build a FnSignature from an EMLFunction's annotations."""
    param_units: list[UnitOrVar] = []
    for p in fn.params:
        # Parameters without unit annotation are polymorphic (UnitVar),
        # matching any unit at the call site.
        if p.unit_expr is None:
            param_units.append(UnitVar())
        else:
            unit = resolve_unit_expr(p.unit_expr, registry, line=p.line, col=p.col)
            param_units.append(unit)

    # Return types without a unit annotation are polymorphic (UnitVar).
    if fn.return_unit_expr is None:
        return_unit: UnitOrVar = UnitVar()
    else:
        return_unit = resolve_unit_expr(
            fn.return_unit_expr, registry, line=fn.line, col=fn.col
        )
    return FnSignature(param_units, return_unit)


def _check_function(
    fn: EMLFunction,
    registry: dict[str, Unit],
    const_env: TypeEnv,
    fn_registry: dict[str, FnSignature],
) -> None:
    """Check a single function body and its requires/ensures predicates."""
    # Build the parameter environment.
    # Parameters without unit annotation are polymorphic (UnitVar).
    param_env: TypeEnv = {}
    for p in fn.params:
        if p.unit_expr is None:
            param_env[p.name] = UnitVar()
        else:
            param_env[p.name] = resolve_unit_expr(
                p.unit_expr, registry, line=p.line, col=p.col
            )

    # Resolve the declared return unit.
    # None means no unit annotation (polymorphic -- any unit is ok).
    if fn.return_unit_expr is None:
        declared_return: UnitOrVar = UnitVar()
    else:
        declared_return = resolve_unit_expr(
            fn.return_unit_expr, registry, line=fn.line, col=fn.col
        )

    # Merge const_env + param_env (params shadow consts).
    env: TypeEnv = {**const_env, **param_env}

    # Check requires predicates.
    for pred in fn.requires:
        infer_expr(pred, env, fn_registry)

    # Check ensures predicates.
    for pred in fn.ensures:
        infer_expr(pred, env, fn_registry)

    # Check the body and get its inferred return unit.
    assert fn.body is not None
    inferred_return = infer_expr(fn.body, env, fn_registry)

    # Validate the inferred return matches the declared return unit.
    # If the body is a UnitVar (e.g. a bare literal `42`), that's fine --
    # it coerces to whatever the declared return type is.
    # If declared return is UnitVar (bare Real), any inferred unit is fine.
    if not isinstance(inferred_return, UnitVar) and not isinstance(declared_return, UnitVar):
        assert isinstance(inferred_return, Unit) and isinstance(declared_return, Unit)
        if not inferred_return.equals_dimensionally(declared_return):
            raise UnitTypeError(
                f"function '{fn.name}' return type is declared as "
                f"Real[{declared_return.display()}] but the body infers "
                f"Real[{inferred_return.display()}]",
                fn.line,
                fn.col,
            )
