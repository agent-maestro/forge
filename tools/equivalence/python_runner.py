"""Python reference: lambdify the AST -> SymPy form and evaluate.

Used as the gold standard against which every other backend is
compared in the equivalence harness. Always available -- requires
only sympy + the parser+profiler.

Limitations are inherited from `lang/profiler/ast_to_sympy.py`:

  - Functions whose body decomposes into a tuple ("tuple" status)
    return a list of values per vector; callers must unpack.
  - Functions that compile via the "complex_body" status (mut /
    while / branching) cannot be evaluated through this path --
    callers must skip them.
"""

from __future__ import annotations

from typing import Iterable

import sympy as sp

from lang.parser.ast_nodes import EMLFunction
from lang.profiler.ast_to_sympy import convert_function_body


class PythonReferenceError(RuntimeError):
    """Raised when the function's body can't be lambdified."""


def lambdify_function(func: EMLFunction):
    """Return a callable `(*args) -> float | tuple[float, ...]`.

    Raises PythonReferenceError on functions whose body lies outside
    the SymPy-bridge's supported subset.
    """
    cr = convert_function_body(func)
    if cr.status == "complex_body":
        raise PythonReferenceError(
            f"function {func.name!r} has complex_body (mut/while)"
            " -- can't lambdify",
        )
    if cr.status == "non_arithmetic":
        raise PythonReferenceError(
            f"function {func.name!r} body has no arithmetic content",
        )

    param_syms = [sp.Symbol(p.name) for p in func.params]

    if cr.status == "ok":
        f = sp.lambdify(
            param_syms, cr.expression,
            modules=("math",),
        )
        return f

    # tuple
    fs = [
        sp.lambdify(param_syms, e, modules=("math",))
        for e in cr.expression
    ]
    def _call(*args):
        return tuple(f(*args) for f in fs)
    return _call


def run_python_reference(
    func: EMLFunction,
    vectors: Iterable[tuple[float, ...]],
) -> list[float | tuple[float, ...]]:
    """Evaluate `func` at every input vector via the SymPy reference."""
    f = lambdify_function(func)
    out: list = []
    for vec in vectors:
        out.append(f(*vec))
    return out
