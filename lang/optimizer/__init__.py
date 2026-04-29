"""SuperBEST routing + fusion + CSE + constant folding.

The optimizer is the DEFAULT (not opt-in). Every function passes
through it before any backend emits code, so all backends share
the same optimal node count + the same per-node operator choice.

Public entries:

  optimize_module(mod)    Run the full pass sequence over every
                          function in `mod`. Mutates the module
                          in place and returns it for chaining.
  optimize_function(fn)   Same, single function.
  fold_constants(node)    Just the constant-folding pass.
  apply_cse(fn)           Just the CSE pass.
  route_superbest(node)   Just SuperBEST routing (today: identity).

Default pass sequence (in order):

  1. constant_folding  -- fold pure-literal sub-trees first so
                          downstream passes see a smaller tree.
  2. cse               -- hoist remaining duplicates into lets.
  3. superbest         -- per-node operator-family selection
                          (placeholder; wired in for Phase 2.1).
"""

from copy import deepcopy

from lang.optimizer.constant_folding import fold_constants, fold_in_place
from lang.optimizer.cse import apply_cse, apply_cse_module
from lang.optimizer.superbest import route_superbest
from lang.parser.ast_nodes import EMLFunction, EMLModule, NodeKind


def optimize_function(fn: EMLFunction) -> EMLFunction:
    """Run the default pass sequence on one function. Returns a
    new function -- the input is not mutated."""
    if fn.body is None:
        return fn

    out = deepcopy(fn)

    # Pass 1: constant folding (in-place on the deep copy).
    if out.body is not None:
        out.body = fold_in_place(out.body)
    # Pass 2: CSE -- operates on the whole function.
    out = apply_cse(out)
    # Pass 3: superbest (no-op today).
    if out.body is not None:
        out.body = route_superbest(out.body)
    return out


def optimize_module(mod: EMLModule) -> EMLModule:
    """Run the default pass sequence on every function in `mod`.
    Returns a new module; the input is not mutated."""
    out = deepcopy(mod)
    out.functions = [optimize_function(fn) for fn in mod.functions]
    return out


__all__ = [
    "optimize_function",
    "optimize_module",
    "fold_constants",
    "apply_cse",
    "apply_cse_module",
    "route_superbest",
]
