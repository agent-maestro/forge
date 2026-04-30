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

from lang.optimizer.constant_folding import fold_constants
from lang.parser.ast_nodes import EMLConstant, EMLFunction, EMLModule, NodeKind
from lang.profiler.ast_to_sympy import convert_function_body


class PythonReferenceError(RuntimeError):
    """Raised when the function's body can't be lambdified."""


def constants_from_module(mod: EMLModule) -> dict[str, float | int | bool]:
    """Extract every literal-valued module-level `const NAME = X;`
    so the SymPy bridge can inline them when lambdifying. Each
    initialiser is constant-folded first so negative literals
    (`-100.0`, parsed as UNARYOP over a positive LITERAL) are
    recovered as a single literal value. Initialisers that don't
    fold to a literal are skipped (the bridge keeps them symbolic)."""
    out: dict[str, float | int | bool] = {}
    for c in mod.constants:
        if not isinstance(c, EMLConstant):
            continue
        folded = fold_constants(c.value)
        if folded.kind == NodeKind.LITERAL:
            v = folded.value
            if isinstance(v, (bool, int, float)):
                out[c.name] = v
    return out


def lambdify_function(
    func: EMLFunction,
    *,
    constants: dict[str, float | int | bool] | None = None,
    callee_table: dict | None = None,
):
    """Return a callable `(*args) -> float | tuple[float, ...]`.

    `constants` -- optional mapping of module-level const names to
    their literal values; passed through to the SymPy bridge so
    they inline as numeric literals rather than free symbols.

    `callee_table` -- optional mapping of *user* function names
    (from the same module) to their already-lambdified callables.
    Lets `func` reference siblings that the inliner declined to
    inline (e.g. functions with `let` bindings).

    Raises PythonReferenceError on functions whose body lies outside
    the SymPy-bridge's supported subset.
    """
    cr = convert_function_body(func, constants=constants)
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
    # `modules` arg: math first, then any user-callable resolver dict
    # so SymPy `Function` nodes for sibling calls evaluate correctly.
    modules: tuple = ("math",)
    if callee_table:
        modules = (callee_table, "math")

    if cr.status == "ok":
        f = sp.lambdify(param_syms, cr.expression, modules=modules)
        return f

    # tuple
    fs = [
        sp.lambdify(param_syms, e, modules=modules)
        for e in cr.expression
    ]
    def _call(*args):
        return tuple(f(*args) for f in fs)
    return _call


def build_module_callee_table(
    mod: EMLModule,
    target_fn_name: str,
    *,
    constants: dict[str, float | int | bool] | None = None,
) -> dict:
    """Lambdify every function in `mod` that the target depends on
    (transitively) and return them in a name -> callable dict.

    Used by `cross_target_check` to resolve sibling CALLs that
    the inliner declined to inline (e.g. functions with `let`
    bindings). Functions whose body the SymPy bridge can't handle
    are silently dropped -- if the target depends on one of those,
    `lambdify_function` will fail with a NameError at evaluation
    time, which propagates as a clearer error than this helper
    silently swallowing it.
    """
    table: dict = {}
    for fn in mod.functions:
        if fn.name == target_fn_name:
            continue
        if fn.is_extern:
            # Extern primitives have no SymPy body. Skip silently;
            # if the target calls one, evaluation will surface a
            # NameError that points at the right place.
            continue
        try:
            table[fn.name] = lambdify_function(fn, constants=constants)
        except PythonReferenceError:
            # complex_body or unsupported -- skip; the target may
            # still avoid this callee on its evaluation path.
            continue
    return table


def run_python_reference(
    func: EMLFunction,
    vectors: Iterable[tuple[float, ...]],
    *,
    constants: dict[str, float | int | bool] | None = None,
    callee_table: dict | None = None,
) -> list[float | tuple[float, ...]]:
    """Evaluate `func` at every input vector via the SymPy reference."""
    f = lambdify_function(
        func, constants=constants, callee_table=callee_table,
    )
    out: list = []
    for vec in vectors:
        out.append(f(*vec))
    return out
