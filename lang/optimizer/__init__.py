"""SuperBEST routing + fusion + CSE + constant folding.

The optimizer is the DEFAULT (not opt-in). Every function passes
through it before any backend emits code, so all backends share
the same optimal node count + the same per-node operator choice.
"""

from lang.optimizer.superbest import route_superbest

__all__ = ["route_superbest"]
