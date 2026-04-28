"""Chain-order type checker.

Verifies that every function's inferred chain order satisfies its
declared `where chain_order <op> N` constraint. Runs AFTER the
profiler, so each function carries its `profile['chain_order']`.

SCAFFOLD. Real implementation in Phase 1.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from lang.parser.ast_nodes import EMLFunction


@dataclass(frozen=True)
class TypeError_:
    """A single chain-order constraint violation."""
    function_name: str
    declared_op: str
    declared_value: int
    inferred_value: int
    line: int
    col: int

    def message(self) -> str:
        return (
            f"Type error in {self.function_name}: return type "
            f"requires chain_order {self.declared_op} "
            f"{self.declared_value}, but body has chain_order "
            f"{self.inferred_value}"
        )


def type_check_function(func: EMLFunction) -> list[TypeError_]:
    """Return list of constraint violations for one function.
    Empty list = type-check OK."""
    if not func.return_constraint or not func.profile:
        return []
    op = func.return_constraint["op"]
    limit = func.return_constraint["value"]
    actual = func.profile["chain_order"]

    ok = {
        "<=": actual <= limit,
        "<":  actual < limit,
        ">=": actual >= limit,
        ">":  actual > limit,
        "==": actual == limit,
        "!=": actual != limit,
    }.get(op, True)

    if ok:
        return []
    return [TypeError_(
        function_name=func.name,
        declared_op=op,
        declared_value=limit,
        inferred_value=actual,
        line=getattr(func.body, "line", 0),
        col=getattr(func.body, "col", 0),
    )]


def type_check_program(functions: list[EMLFunction]) -> list[TypeError_]:
    """Run type_check_function on every function; concatenate errors."""
    out: list[TypeError_] = []
    for f in functions:
        out.extend(type_check_function(f))
    return out
