"""FPGA resource allocator -- Patent #14 implementation.

Reference: lang/spec/EML_LANG_DESIGN.md section 3.1.
SCAFFOLD.
"""

from __future__ import annotations

from typing import Any

from lang.parser.ast_nodes import EMLFunction


class CompileError(Exception):
    """Allocation failed -- usually because the design exceeds
    the user's LUT / DSP / BRAM budget."""


class FPGAAllocator:
    """Per Patent #14: decide what hardware to instantiate."""

    def allocate(
        self,
        program: list[EMLFunction],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        """Returns a dict the Verilog backend can act on:
            exp_units, ln_units, trig_units, mac_units,
            sharing_strategy, pipeline_depth, estimated_luts,
            estimated_dsps, clock_mhz, throughput.
        """
        exp_units = self._count_instances(program, kind="exp")
        ln_units = self._count_instances(program, kind="ln")
        trig_units = self._count_instances(program, kind="trig")

        # Sharing policy: dedicated when count <= 2; shared otherwise.
        strategy = "dedicated" if exp_units <= 2 else "shared"

        # Per-function precision selection.
        for func in program:
            co = (func.profile or {}).get("chain_order", 0)
            if co >= 3:
                func.hw_precision = "float64"
            elif co >= 1:
                func.hw_precision = "float32"
            else:
                func.hw_precision = "float16"

        pipeline_depth = max(
            ((f.profile or {}).get("eml_depth", 0) for f in program),
            default=0,
        )

        estimated_luts = self._estimate_luts(
            exp_units, ln_units, trig_units, strategy)
        max_luts = constraints.get("max_luts")
        if max_luts is not None and estimated_luts > max_luts:
            agg = sum((f.profile or {}).get("chain_order", 0) for f in program)
            raise CompileError(
                f"Design requires {estimated_luts} LUTs but budget is "
                f"{max_luts}. Reduce program complexity (current "
                f"aggregate chain order: {agg})."
            )

        clock_mhz = constraints.get("clock_mhz", 100)
        throughput = (
            f"{clock_mhz / max(pipeline_depth, 1):.1f} Msamples/s"
        )

        return {
            "exp_units": exp_units,
            "ln_units": ln_units,
            "trig_units": trig_units,
            "mac_units": sum(
                (f.profile or {}).get("eml_depth", 0) for f in program),
            "sharing_strategy": strategy,
            "pipeline_depth": pipeline_depth,
            "estimated_luts": estimated_luts,
            "estimated_dsps": exp_units * 4 + ln_units * 3,
            "clock_mhz": clock_mhz,
            "throughput": throughput,
        }

    # ── Helpers ───────────────────────────────────────────────

    def _count_instances(
        self, program: list[EMLFunction], kind: str
    ) -> int:
        """Count nodes of `kind` across all FPGA-targeted functions.
        SCAFFOLD: returns sum of cost-class hits today; will walk
        AST in Phase 3.1."""
        total = 0
        for f in program:
            cc = (f.profile or {}).get("cost_class", "")
            total += cc.count(kind)
        return total

    def _estimate_luts(
        self, exp_units: int, ln_units: int, trig_units: int,
        strategy: str,
    ) -> int:
        """Rough LUT estimate per unit. Vendor-specific numbers
        come from `hardware/targets/<vendor>/<board>.py` in
        Phase 3.1."""
        per_exp = 1200 if strategy == "dedicated" else 1500
        per_ln = 1000 if strategy == "dedicated" else 1300
        per_trig = 1400
        return (exp_units * per_exp
                + ln_units * per_ln
                + trig_units * per_trig)
