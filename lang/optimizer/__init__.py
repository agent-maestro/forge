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
from lang.optimizer.inliner import inline_calls
from lang.optimizer.log_domain import (
    apply_log_domain_optimizer_module,
    write_log_domain_trace,
)
from lang.optimizer.ml_routing import route_ml_activations_module
from lang.optimizer.superbest import (
    route_superbest,
    superbest_function,
    superbest_module,
)
from lang.optimizer.tree_shaker import shake_imports
from lang.parser.ast_nodes import EMLFunction, EMLModule, NodeKind


def optimize_function(fn: EMLFunction) -> EMLFunction:
    """Run the per-function pass sequence (constant_folding + CSE +
    superbest). Returns a new function -- input is not mutated.

    NOTE: the call-inliner is a MODULE-level pass (it needs to
    look up callees in the module's function table) so it lives
    in `optimize_module`, not here. Calling `optimize_function`
    directly skips inlining."""
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


def optimize_module(mod: EMLModule, *,
                    ml_routing: bool = False,
                    log_domain: bool = False,
                    optimizer_trace_path: str | None = None) -> EMLModule:
    """Run the default pass sequence on every function in `mod`.
    Returns a new module; the input is not mutated.

    Pass order:
      0. inline_calls       -- substitute eligible same-module
                               CALLs with the callee's body
      1. constant_folding   -- fold pure-literal sub-trees
                               (incl. ones exposed by inlining)
      2. cse                -- hoist remaining duplicates
      3. superbest          -- per-node operator-family selection
      3.5 ml_routing        -- (opt-in) pattern-rewrite sigmoid /
                               softplus to libmonogate runtime calls
                               for HIGH-drift functions
      3.6 log_domain        -- (opt-in) annotate functions that should
                               be searched in log-domain coordinates and
                               optionally export a trace packet
      4. shake_imports      -- drop unused imports

    `ml_routing` defaults to False because the pass emits CALL
    nodes targeting libmonogate runtime symbols, which only the
    C and Rust backends know how to resolve. Enable when
    targeting C / Rust on a known-drifty workload.
    """
    # Pass 0: module-level inliner.
    out = inline_calls(mod)
    # Passes 1 -> 2: per-function (constant_folding + CSE).
    out.functions = [optimize_function(fn) for fn in out.functions]
    # Pass 3: module-level SuperBEST routing -- needs SymPy
    # bridge access so it lives outside optimize_function.
    out = superbest_module(out)
    # Pass 3.5: opt-in ML pattern rewriter (libmonogate runtime).
    if ml_routing:
        out = route_ml_activations_module(out)
    if log_domain:
        out, trace_packet = apply_log_domain_optimizer_module(out)
        if optimizer_trace_path:
            write_log_domain_trace(trace_packet, optimizer_trace_path)
    # Pass 4: drop unused imports (after inlining so reachable set
    # reflects the post-inline call graph).
    out = shake_imports(out)
    return out


__all__ = [
    "optimize_function",
    "optimize_module",
    "fold_constants",
    "fold_in_place",
    "apply_cse",
    "apply_cse_module",
    "inline_calls",
    "apply_log_domain_optimizer_module",
    "write_log_domain_trace",
    "route_superbest",
    "superbest_function",
    "superbest_module",
    "route_ml_activations_module",
    "shake_imports",
    "EMLFunction",
    "EMLModule",
    "NodeKind",
]
