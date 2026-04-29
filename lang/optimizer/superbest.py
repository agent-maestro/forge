"""SuperBEST routing -- selects the most numerically-stable
algebraic form for each function body.

This pass is the optimizer's third stage (after constant folding
and CSE). It uses `eml_cost.recommend_form` to detect when a
function body matches one of the four E-193 Phase-3 supported
families (sigmoid, exponential decay, logistic growth, cardiac
oscillator). When a recommendation is available AND it would
save precision (`digits_saved > 0`), the body is rewritten to
the canonical form.

When `recommend_form` abstains (the body isn't in any supported
family) OR returns the input unchanged (already canonical), the
pass is a no-op for that function.

When the SymPy-to-AST inverse can't lower the canonical form
(unsupported sympy node), the pass logs a warning via the
function's stability_warnings list (if present) and leaves the
body alone -- correctness over optimization.

Patents: #01 (SuperBEST), #02 (hybrid routing), #08 (cost-branch
selection). The default optimizer for every backend.
"""

from __future__ import annotations

from copy import deepcopy

from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind


# Minimum precision-improvement threshold to bother rewriting.
# Below this, the rewrite is judged not worth the AST shape change.
_MIN_DIGITS_SAVED = 0.5


def route_superbest(node: ASTNode) -> ASTNode:
    """Backwards-compatible expression-level entry. Today this is
    an identity; the real routing happens at the function level
    via `superbest_function` / `superbest_module`.

    Kept so existing callers (the optimizer's per-function loop)
    continue to work without change."""
    return node


def superbest_function(fn: EMLFunction) -> EMLFunction:
    """Apply SuperBEST routing to one function. Returns a new
    function -- input is not mutated. Returns `fn` unchanged
    when:
      - the body isn't a single-expression block
      - eml_cost.recommend_form abstains
      - the recommended form saves <0.5 digits
      - sympy_to_ast can't lower the canonical form
    """
    if fn.body is None or fn.body.kind != NodeKind.BLOCK:
        return fn
    # Only operate on functions whose body is a single final
    # expression -- multi-statement bodies need a more careful
    # rewrite that's deferred to a later phase.
    if len(fn.body.children) != 1:
        return fn
    if fn.return_tuple_types:
        return fn

    # Lazy imports to keep the optimizer's cold-path light.
    from lang.profiler.ast_to_sympy import convert_function_body
    from lang.profiler.sympy_to_ast import (
        ConversionError,
        sympy_to_ast,
    )
    try:
        from eml_cost import recommend_form
    except ImportError:
        # eml_cost is a forge dependency, but treat it as optional
        # for this pass so the build doesn't break if an alternate
        # cost analyzer is plugged in later.
        return fn

    cr = convert_function_body(fn)
    if cr.status != "ok":
        return fn

    import sympy as sp
    expr = cr.expression
    if not isinstance(expr, sp.Basic):
        return fn

    # Fast filters BEFORE the slow eml_cost.recommend_form call.
    # All 4 supported families use either `exp` or `tanh` -- if
    # neither appears in the expression's function-atom set, the
    # call can't possibly match. Sin / cos / log / sqrt
    # expressions all early-exit here.
    #
    # Pure-polynomial expressions also early-exit (no Function
    # atoms at all). And bigger expressions (>10 atoms) get
    # skipped because nsimplify-then-recommend_form is expensive
    # on them and the families are all SHALLOW anyway.
    #
    # Together these cut a full-stdlib snapshot from ~3 minutes
    # to ~1 second on this codebase. recommend_form on a
    # 6-atom sin-only expression cost ~16s before this pre-filter.
    function_atoms = expr.atoms(sp.Function)
    if not function_atoms:
        return fn
    fn_classes = {type(f) for f in function_atoms}
    if not (fn_classes & {sp.exp, sp.tanh}):
        return fn
    try:
        n_atoms = len(expr.atoms())
    except Exception:
        return fn
    if n_atoms > 10:
        return fn

    # Skip nsimplify when any Float in the expression looks
    # irrational at f64 precision (e.g. GELU's `0.7978845608` and
    # `0.035677408136172`). nsimplify(rational=True) on those
    # spends seconds doing continued-fraction expansion that
    # never matches a nice fraction.
    #
    # Heuristic: a "round" float in the SuperBEST families is
    # something like 0.5, 1, 2, etc -- short Python repr (<= 8 chars).
    # NB: we check `repr(float(f))` rather than `repr(f)` because
    # `sp.Float`'s repr always extends to its full 15-digit
    # precision, which would reject every value that contains 0.5.
    floats = expr.atoms(sp.Float)
    if any(len(repr(float(f))) > 8 for f in floats):
        return fn

    # `recommend_form` keys on the SymPy node-class structure
    # and is sensitive to Float vs Rational coefficients (it
    # matches `tanh(x/2)/2 + 1/2`, not `0.5*tanh(0.5*x) + 0.5`).
    # convert_function_body emits the Float form, so convert any
    # numerically-clean Floats to Rationals via nsimplify first.
    try:
        normalized = sp.nsimplify(expr, rational=True)
    except Exception:
        normalized = expr

    try:
        rec = recommend_form(normalized)
    except Exception:
        # The cost analyzer failed on this expression -- bail out
        # rather than fail the whole compile.
        return fn
    if rec is None:
        return fn
    if rec.digits_saved < _MIN_DIGITS_SAVED:
        # Already at (or near) canonical form -- no rewrite worth
        # making.
        return fn

    try:
        new_expr_ast = sympy_to_ast(rec.canonical_form)
    except ConversionError:
        # Can't lower the recommendation -- leave the body alone.
        return fn

    out = deepcopy(fn)
    out.body = ASTNode(
        kind=NodeKind.BLOCK, children=[new_expr_ast],
    )
    # Annotate the profile so consumers know SuperBEST fired.
    if out.profile is not None:
        warnings = list(out.profile.get("stability_warnings", []))
        warnings.append(
            f"SuperBEST routed to {rec.family!r} canonical form "
            f"(saved {rec.digits_saved:.2f} digits)"
        )
        out.profile = dict(out.profile)
        out.profile["stability_warnings"] = warnings
        out.profile["superbest_family"] = rec.family
        out.profile["superbest_digits_saved"] = float(rec.digits_saved)
    return out


def superbest_module(mod: EMLModule) -> EMLModule:
    """Apply SuperBEST routing to every function. Returns a new
    module; input is not mutated."""
    out = deepcopy(mod)
    out.functions = [superbest_function(f) for f in out.functions]
    return out
