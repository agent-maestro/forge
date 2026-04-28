"""Profile every parsed EML-lang function.

Bridges the AST into eml-cost's analyze + analyze_dynamics +
predict_chain_order_via_additivity. Output populates the
`EMLFunction.profile` dict; backends and the type checker read
from there.

SCAFFOLD. Implementation lands in Phase 1.3.
"""

from __future__ import annotations

from typing import Any

from lang.parser.ast_nodes import ASTNode, EMLFunction


class Profiler:
    """Profiles AST functions in place."""

    def profile_function(self, func: EMLFunction) -> dict:
        """Compute the profile dict and store on `func.profile`.
        Returns the dict for callers that want it directly."""
        sympy_expr = self._ast_to_sympy(func.body)

        try:
            from eml_cost import analyze, analyze_dynamics, canonicalize
        except ImportError:
            return self._minimal_profile(func)

        canonical = canonicalize(sympy_expr)
        result = analyze(canonical)
        dynamics = analyze_dynamics(sympy_expr)

        profile = {
            "chain_order": result.pfaffian_r,
            "max_path_r": result.max_path_r,
            "eml_depth": result.eml_depth,
            "structural_overhead": getattr(result, "structural_overhead", 0),
            "cost_class": result.cost_class,
            "dynamics": {
                "oscillations": dynamics.n_oscillations,
                "decays": dynamics.n_decays,
                "predicted_r": dynamics.predicted_r,
            },
            "node_count": result.eml_depth,
            "stability_warnings": self._check_stability(sympy_expr),
            "fp16_drift_risk": self._assess_drift_risk(result),
            "fpga_estimate": self._estimate_fpga(result),
        }
        func.profile = profile
        return profile

    # ── Helpers ───────────────────────────────────────────────

    def _ast_to_sympy(self, node: ASTNode | None) -> Any:
        """Convert an AST subtree into a SymPy expression for the
        analyzer to consume. SCAFFOLD."""
        raise NotImplementedError("AST->SymPy lands in Phase 1.3")

    def _minimal_profile(self, func: EMLFunction) -> dict:
        """Fallback when eml-cost is unavailable -- profile is
        marked as 'unknown'. The compiler should refuse to emit
        when this fires (means we can't enforce chain-order types)."""
        func.profile = {
            "chain_order": -1,
            "cost_class": "unknown",
            "stability_warnings": ["eml-cost unavailable; profile skipped"],
            "fpga_estimate": {},
        }
        return func.profile

    def _check_stability(self, sympy_expr: Any) -> list[str]:
        """Domain-restriction warnings (e.g. ln requires x > 0)."""
        return []

    def _assess_drift_risk(self, result: Any) -> str:
        """Return 'LOW' / 'MEDIUM' / 'HIGH' based on chain order +
        E-193 fp16 drift estimate."""
        co = getattr(result, "pfaffian_r", 0)
        if co >= 3:
            return "HIGH"
        if co >= 1:
            return "MEDIUM"
        return "LOW"

    def _estimate_fpga(self, result: Any) -> dict:
        """Per Patent #14: rough resource estimate from cost class."""
        cc = getattr(result, "cost_class", "")
        depth = getattr(result, "eml_depth", 0)
        return {
            "exp_units": cc.count("exp"),
            "ln_units":  cc.count("ln"),
            "trig_units": 1 if getattr(result, "pfaffian_r", 0) >= 2 else 0,
            "mac_units": depth,
            "estimated_latency_cycles": depth * 2,
            "precision_bits_needed":
                64 if getattr(result, "pfaffian_r", 0) >= 3 else 32,
        }
