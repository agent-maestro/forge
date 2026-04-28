"""Verilog backend -- emits parametric synthesizable Verilog.

Each EML operator maps to a hardware module:
  exp(x)    -> CORDIC or polynomial approximation
  ln(x)     -> CORDIC or series expansion
  +/-/*//   -> standard arithmetic units
  SuperBEST -> combinational logic selecting the optimal path

Reference: lang/spec/EML_LANG_DESIGN.md section 3.2.
SCAFFOLD.
"""

from __future__ import annotations

from typing import Any

from lang.parser.ast_nodes import EMLFunction


class VerilogBackend:
    """Generate synthesizable Verilog from a program + allocation."""

    name = "verilog"

    def compile(
        self,
        program: list[EMLFunction],
        allocation: dict[str, Any],
    ) -> str:
        """Returns full Verilog source covering top-level + per-function
        pipelines + transcendental unit instantiations."""
        modules = []
        if allocation.get("exp_units", 0) > 0:
            modules.append(self._generate_exp_module(allocation["exp_units"]))
        if allocation.get("ln_units", 0) > 0:
            modules.append(self._generate_ln_module(allocation["ln_units"]))

        for func in program:
            if any(
                a.get("kind") == "target" and
                a.get("args", {}).get("0") == "fpga"
                for a in func.annotations
            ):
                modules.append(self._generate_pipeline(func))

        modules.append(self._generate_top(program, allocation))
        return "\n\n".join(modules)

    # ── Module generators (SCAFFOLD) ──────────────────────────

    def _generate_exp_module(self, n_units: int) -> str:
        """CORDIC exp(x) module. See
        hardware/modules/transcendental/cordic_exp.v for the real
        implementation; this method instantiates N copies as
        needed."""
        return (
            f"// {n_units} eml_exp instance(s) -- see\n"
            f"// hardware/modules/transcendental/cordic_exp.v\n"
        )

    def _generate_ln_module(self, n_units: int) -> str:
        return (
            f"// {n_units} eml_ln instance(s) -- see\n"
            f"// hardware/modules/transcendental/cordic_ln.v\n"
        )

    def _generate_pipeline(self, func: EMLFunction) -> str:
        """One pipeline module per @target(fpga) function."""
        depth = (func.profile or {}).get("eml_depth", 1)
        co = (func.profile or {}).get("chain_order", 0)
        width = 64 if co >= 3 else 32
        params = ",\n    ".join(
            f"input  wire signed [WIDTH-1:0] {p['name']}"
            for p in func.params
        )
        return (
            f"// Pipeline: {func.name}\n"
            f"// Chain order: {co}, depth: {depth}, width: {width} bits\n"
            f"module {func.name}_pipeline #(\n"
            f"    parameter WIDTH = {width}\n"
            f") (\n"
            f"    input  wire             clk,\n"
            f"    input  wire             rst,\n"
            f"    input  wire             valid_in,\n"
            f"    {params},\n"
            f"    output reg              valid_out,\n"
            f"    output reg signed [WIDTH-1:0] result\n"
            f");\n"
            f"    // SCAFFOLD: pipeline body lands in Phase 3.2\n"
            f"endmodule\n"
        )

    def _generate_top(
        self, program: list[EMLFunction], allocation: dict[str, Any],
    ) -> str:
        """Top-level wiring of the per-function pipelines."""
        return (
            f"// top.v -- top-level wiring (SCAFFOLD)\n"
            f"// allocation: {allocation}\n"
        )
