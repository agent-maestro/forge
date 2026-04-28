"""Dynamics-counter wrapper -- exposes eml-cost.analyze_dynamics
in the shape backends need.

The dynamics counter (Patent #15, chain-order additivity rule)
reports oscillation + decay modes + predicted aggregate chain
order from the multiset of PNE primitives in the AST.

SCAFFOLD.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynamicsReport:
    """Dynamics summary for one function or expression."""
    n_oscillations: int
    n_decays: int
    predicted_r: int  # = 2 * n_osc + 1 * n_decay + tower_base sum


def report_for_function(func) -> DynamicsReport:
    """Convenience wrapper -- assumes func.profile already populated."""
    if not func.profile:
        raise RuntimeError(
            f"function {func.name} has no profile -- "
            f"run Profiler.profile_function first"
        )
    d = func.profile["dynamics"]
    return DynamicsReport(
        n_oscillations=d["oscillations"],
        n_decays=d["decays"],
        predicted_r=d["predicted_r"],
    )
