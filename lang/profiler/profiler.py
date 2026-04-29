"""Profile every parsed EML-lang function.

Bridges the AST (via lang.profiler.ast_to_sympy) into eml-cost's
analyze + analyze_dynamics. Output populates `EMLFunction.profile`
with chain order, cost class, dynamics, FPGA estimate, and stability
warnings BEFORE codegen runs.

Reference: `lang/spec/EML_LANG_DESIGN.md` section 1.3.
"""

from __future__ import annotations

from typing import Any

from lang.parser.ast_nodes import EMLFunction
from lang.profiler.ast_to_sympy import convert_function_body


def _cost_class(result: Any) -> str:
    """Build the standard p<r>-d<d>-w<w>-c<c> cost-class string from
    an eml_cost.AnalyzeResult."""
    return (
        f"p{result.pfaffian_r}"
        f"-d{result.eml_depth}"
        f"-w{result.max_path_r}"
        f"-c{1 if result.is_pfaffian_not_eml else 0}"
    )


class Profiler:
    """Profiles AST functions in place."""

    def __init__(self):
        try:
            import eml_cost  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

    # ── Public API ────────────────────────────────────────────

    def profile_function(self, func: EMLFunction) -> dict:
        """Compute the profile dict and store on `func.profile`.
        Returns the dict for callers that want it directly."""
        if not self._available:
            return self._unavailable_profile(func)

        import eml_cost

        # AST -> SymPy
        conv = convert_function_body(func)

        if conv.status == "complex_body":
            func.profile = {
                "status": "complex_body",
                "note": conv.note,
                "chain_order": -1,
                "cost_class": "complex",
                "stability_warnings": [],
                "fpga_estimate": {},
            }
            return func.profile

        if conv.status == "non_arithmetic":
            func.profile = {
                "status": "non_arithmetic",
                "note": conv.note,
                "chain_order": 0,
                "cost_class": "p0-d0-w0-c0",
                "stability_warnings": [],
                "fpga_estimate": {},
            }
            return func.profile

        # Tuple-return functions: profile each component, take the
        # WORST chain order across them. The cost-class string is
        # the comma-joined per-element classes.
        if conv.status == "tuple":
            per_element = []
            for sub_expr in conv.expression:
                ar = eml_cost.analyze(sub_expr)
                per_element.append({
                    "result": ar,
                    "cost_class": _cost_class(ar),
                })
            worst_co = max(p["result"].pfaffian_r for p in per_element)
            worst_depth = max(p["result"].eml_depth for p in per_element)
            worst_path = max(p["result"].max_path_r for p in per_element)
            func.profile = {
                "status": "tuple",
                "chain_order": worst_co,
                "max_path_r": worst_path,
                "eml_depth": worst_depth,
                "node_count": worst_depth,
                "cost_class": ", ".join(p["cost_class"] for p in per_element),
                "structural_overhead": sum(
                    getattr(p["result"], "structural_overhead", 0)
                    for p in per_element),
                "tuple_components": [p["cost_class"] for p in per_element],
                "dynamics": {"oscillations": 0, "decays": 0,
                             "predicted_r": worst_co},
                "stability_warnings": [],
                "fp16_drift_risk": self._assess_drift_risk_from_co(worst_co),
                "fpga_estimate": self._estimate_fpga_aggregate(per_element),
            }
            return func.profile

        # Single-expression body -- the common case.
        sympy_expr = conv.expression
        result = eml_cost.analyze(sympy_expr)
        try:
            dynamics = eml_cost.analyze_dynamics(sympy_expr)
            dyn = {
                "oscillations": dynamics.n_oscillations,
                "decays":       dynamics.n_decays,
                "predicted_r":  dynamics.predicted_r,
            }
        except Exception:  # noqa: BLE001 -- best-effort
            dyn = {"oscillations": 0, "decays": 0, "predicted_r": 0}

        func.profile = {
            "status": "ok",
            "chain_order": result.pfaffian_r,
            "max_path_r": result.max_path_r,
            "eml_depth": result.eml_depth,
            "structural_overhead": getattr(
                result, "structural_overhead", 0),
            "cost_class": _cost_class(result),
            "is_pfaffian_not_eml": bool(result.is_pfaffian_not_eml),
            "predicted_depth": getattr(result, "predicted_depth",
                                       result.eml_depth),
            "dynamics": dyn,
            "node_count": result.eml_depth,
            "stability_warnings": self._check_stability(sympy_expr),
            "fp16_drift_risk": self._assess_drift_risk(result),
            "fpga_estimate": self._estimate_fpga(result, sympy_expr),
        }
        return func.profile

    def profile_module(self, mod) -> None:
        """Profile every function in an EMLModule in-place."""
        for fn in mod.functions:
            self.profile_function(fn)

    # ── Helpers ───────────────────────────────────────────────

    def _unavailable_profile(self, func: EMLFunction) -> dict:
        func.profile = {
            "status": "eml_cost_unavailable",
            "chain_order": -1,
            "cost_class": "unknown",
            "stability_warnings": [
                "eml-cost not installed -- profile skipped",
            ],
            "fpga_estimate": {},
        }
        return func.profile

    def _check_stability(self, sympy_expr: Any) -> list[str]:
        """Domain-restriction warnings (e.g. ln requires x > 0)."""
        warnings: list[str] = []
        s = str(sympy_expr)
        if "log(" in s or "ln(" in s:
            warnings.append(
                "expression contains `log/ln` -- argument must be > 0; "
                "add `where domain: <arg> > 0` to make it explicit"
            )
        if "1/" in s or "/0" in s:
            warnings.append(
                "expression contains division -- guard against "
                "zero denominator"
            )
        return warnings

    def _assess_drift_risk(self, result: Any) -> str:
        """LOW / MEDIUM / HIGH per chain order."""
        return self._assess_drift_risk_from_co(result.pfaffian_r)

    @staticmethod
    def _assess_drift_risk_from_co(co: int) -> str:
        if co >= 3:
            return "HIGH"
        if co >= 1:
            return "MEDIUM"
        return "LOW"

    def _estimate_fpga(self, result: Any, sympy_expr: Any) -> dict:
        """Per Patent #14: rough FPGA resource estimate. Counts
        function calls in the SymPy expression rather than relying
        on string matching of the cost class."""
        s = str(sympy_expr)
        exp_units = s.count("exp(")
        ln_units = s.count("log(")
        trig_units = s.count("sin(") + s.count("cos(") + s.count("tan(")
        depth = result.eml_depth
        return {
            "exp_units": exp_units,
            "ln_units": ln_units,
            "trig_units": trig_units,
            "mac_units": depth,
            "estimated_latency_cycles": depth * 2,
            "precision_bits_needed": 64 if result.pfaffian_r >= 3 else 32,
        }

    def _estimate_fpga_aggregate(self, per_element: list[dict]) -> dict:
        """Sum FPGA resources across tuple components."""
        agg = {
            "exp_units": 0, "ln_units": 0, "trig_units": 0,
            "mac_units": 0, "estimated_latency_cycles": 0,
            "precision_bits_needed": 32,
        }
        for p in per_element:
            r = p["result"]
            agg["mac_units"] += r.eml_depth
            agg["estimated_latency_cycles"] += r.eml_depth * 2
            if r.pfaffian_r >= 3:
                agg["precision_bits_needed"] = 64
        return agg
