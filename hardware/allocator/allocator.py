"""FPGA resource allocator -- Patent #14 implementation.

Walks the AST of every `@target(fpga, ...)` function in an
EMLModule. For each transcendental operator instance
(exp/ln/sin/cos/tan/sqrt) decides:

  - whether to allocate a DEDICATED unit (one per use) or SHARED
    unit (time-multiplexed across uses)
  - what precision the unit needs (f16 / f32 / f64) per the
    function's chain order or @target precision arg
  - how much LUT / DSP / BRAM the unit costs on the target device

Aggregates costs across all FPGA-targeted functions, validates
against the target device's budget (LUTs / DSPs / BRAM), and
returns an `AllocationPlan` the Verilog backend will consume in
Phase 3.2.

Reference: lang/spec/EML_LANG_DESIGN.md section 3.1.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Optional

from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind


class CompileError(Exception):
    """Allocation failed -- usually because the design exceeds the
    target device's LUT / DSP / BRAM budget."""


# ── NodeKinds that map to hardware transcendental units ──────────────

_TRANSCENDENTAL_NODE_KINDS: dict[NodeKind, str] = {
    NodeKind.EXP:  "exp",
    NodeKind.LN:   "ln",
    NodeKind.SIN:  "sin",
    NodeKind.COS:  "cos",
    NodeKind.TAN:  "tan",
    NodeKind.SQRT: "sqrt",
    # EML(x, y) = exp(x) - ln(y) -- counts as one exp + one ln.
    NodeKind.EML:  "_eml",
}


@dataclass(frozen=True)
class TranscendentalUnit:
    """One allocated hardware unit instance type."""
    op: str                 # "exp" | "ln" | "sin" | "cos" | "tan" | "sqrt"
    count: int              # how many AST occurrences across the design
    sharing: str            # "dedicated" | "shared"
    precision_bits: int     # 16 | 32 | 64
    luts: int
    dsps: int
    bram_kb: int


@dataclass(frozen=True)
class AllocationPlan:
    """Output of `FPGAAllocator.allocate()`. The Verilog backend
    reads this to know what modules to instantiate and how to
    pipeline them."""
    target_device: str
    transcendental_units: tuple[TranscendentalUnit, ...]
    mac_units: int
    pipeline_depth: int
    estimated_luts: int
    estimated_dsps: int
    estimated_bram_kb: int
    clock_mhz: int
    throughput_msps: float
    notes: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> str:
        """Pretty-print for the CLI's --allocate output."""
        lines = [
            f"  FPGA allocation plan for {self.target_device}",
            f"  Pipeline depth: {self.pipeline_depth} stages",
            f"  Clock target:   {self.clock_mhz} MHz",
            f"  Throughput:     {self.throughput_msps:.1f} Msamples/s",
            "",
            f"  Resources:  {self.estimated_luts:>5} LUTs   "
            f"{self.estimated_dsps:>3} DSPs   "
            f"{self.estimated_bram_kb:>4} KB BRAM",
            f"  MAC units:  {self.mac_units}",
        ]
        if self.transcendental_units:
            lines.append("")
            lines.append("  Transcendental units:")
            lines.append(
                f"    {'op':>5}  {'count':>5}  {'sharing':>10}  "
                f"{'prec':>5}  {'LUTs':>5}  {'DSPs':>4}"
            )
            for u in self.transcendental_units:
                lines.append(
                    f"    {u.op:>5}  {u.count:>5}  {u.sharing:>10}  "
                    f"{u.precision_bits:>3}b  {u.luts:>5}  {u.dsps:>4}"
                )
        else:
            lines.append("  Transcendental units: none "
                         "(pure-polynomial design)")
        for n in self.notes:
            lines.append(f"  NOTE: {n}")
        return "\n".join(lines)


class FPGAAllocator:
    """Real allocator -- walks the AST per Patent #14."""

    # Sharing decision: dedicated when count <= this threshold,
    # else shared (time-multiplexed). Tunable per-target later.
    _SHARING_THRESHOLD = 2

    def allocate(
        self,
        mod: EMLModule,
        constraints: Optional[dict[str, Any]] = None,
    ) -> AllocationPlan:
        """Return a plan covering every `@target(fpga)` function
        in the module. constraints overrides the chosen target's
        defaults (clock_mhz, max_luts, max_dsps, max_brams,
        precision)."""
        constraints = constraints or {}

        target = self._resolve_target(constraints)
        target_dict = target.as_dict()

        # Collect FPGA-targeted functions and merge their
        # @target(fpga, ...) annotation args into the constraints.
        fpga_funcs = self._collect_fpga_functions(mod)
        if not fpga_funcs:
            raise CompileError(
                "No @target(fpga, ...) functions found in module. "
                "Add @target(fpga, ...) to at least one function."
            )

        merged = self._merge_constraints(constraints, fpga_funcs, target_dict)
        clock_mhz = int(merged.get("clock_mhz", target_dict["max_freq_mhz"]))
        max_luts = int(merged.get("max_luts", target_dict["luts"]))
        max_dsps = int(merged.get("max_dsps", target_dict["dsps"]))
        max_bram = int(merged.get("max_brams", target_dict["bram_kb"]))
        forced_precision = merged.get("precision")  # "float16/32/64" or None

        # ── Walk every @target(fpga) function's AST ──────────
        op_counts: dict[str, int] = {}
        per_func_depth: list[int] = []
        per_func_precision: list[int] = []
        for fn in fpga_funcs:
            counts = self._count_ops_in_function(fn)
            for op, c in counts.items():
                op_counts[op] = op_counts.get(op, 0) + c
            depth = (fn.profile or {}).get("eml_depth", 0)
            per_func_depth.append(depth)
            per_func_precision.append(
                self._select_precision(fn, forced_precision)
            )

        # Worst-case precision across the design (one shared unit
        # has to serve the highest-precision caller).
        design_precision = max(per_func_precision, default=32)
        pipeline_depth = max(per_func_depth, default=0)

        # ── Per-op allocation ────────────────────────────────
        units: list[TranscendentalUnit] = []
        total_luts = 0
        total_dsps = 0
        total_bram_kb = 0
        for op in ("exp", "ln", "sin", "cos", "tan", "sqrt"):
            count = op_counts.get(op, 0)
            if count == 0:
                continue
            sharing = ("dedicated" if count <= self._SHARING_THRESHOLD
                       else "shared")
            base_costs = target.PER_UNIT_COST.get((op, sharing))
            if base_costs is None:
                continue
            base_luts, base_dsps, base_bram = base_costs
            lut_mult, dsp_mult = target.precision_multiplier(design_precision)
            unit_luts = int(base_luts * lut_mult)
            unit_dsps = int(base_dsps * dsp_mult)
            n_units = count if sharing == "dedicated" else 1
            units.append(TranscendentalUnit(
                op=op, count=count, sharing=sharing,
                precision_bits=design_precision,
                luts=unit_luts * n_units,
                dsps=unit_dsps * n_units,
                bram_kb=base_bram * n_units,
            ))
            total_luts += unit_luts * n_units
            total_dsps += unit_dsps * n_units
            total_bram_kb += base_bram * n_units

        # MAC units: one per AST internal arithmetic node, summed
        # across all FPGA-targeted functions.
        mac_units = sum(per_func_depth)
        total_luts += mac_units * target.MAC_LUTS_PER_UNIT
        total_dsps += mac_units * target.MAC_DSPS_PER_UNIT

        # ── Budget validation ────────────────────────────────
        notes: list[str] = []
        if total_luts > max_luts:
            agg_co = sum((f.profile or {}).get("chain_order", 0)
                         for f in fpga_funcs)
            raise CompileError(
                f"Design requires {total_luts} LUTs but budget is "
                f"{max_luts}. Aggregate chain order: {agg_co}. "
                f"Reduce program complexity or pick a larger target."
            )
        if total_dsps > max_dsps:
            raise CompileError(
                f"Design requires {total_dsps} DSPs but budget is "
                f"{max_dsps}."
            )
        if total_bram_kb > max_bram:
            raise CompileError(
                f"Design requires {total_bram_kb} KB BRAM but budget "
                f"is {max_bram}."
            )

        if total_luts > max_luts * 0.8:
            notes.append(
                f"LUT utilization {total_luts}/{max_luts} "
                f"({100 * total_luts / max_luts:.0f}%) -- tight"
            )
        if any(u.sharing == "shared" for u in units):
            notes.append(
                "Shared transcendental unit(s) -- the Verilog "
                "backend will insert FIFO arbiters between callers."
            )

        throughput = clock_mhz / max(pipeline_depth, 1)
        return AllocationPlan(
            target_device=target_dict["name"],
            transcendental_units=tuple(units),
            mac_units=mac_units,
            pipeline_depth=pipeline_depth,
            estimated_luts=total_luts,
            estimated_dsps=total_dsps,
            estimated_bram_kb=total_bram_kb,
            clock_mhz=clock_mhz,
            throughput_msps=throughput,
            notes=tuple(notes),
        )

    # ── Helpers ───────────────────────────────────────────────

    def _resolve_target(self, constraints: dict) -> Any:
        """Load the target file (default: Xilinx Artix-7)."""
        target_name = constraints.get("target", "xilinx.artix7")
        module_path = f"hardware.targets.{target_name}"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            raise CompileError(
                f"unknown FPGA target: {target_name!r} "
                f"(import failed: {e})"
            )

    def _collect_fpga_functions(
        self, mod: EMLModule,
    ) -> list[EMLFunction]:
        """All functions with `@target(fpga, ...)` annotations."""
        out: list[EMLFunction] = []
        for fn in mod.functions:
            for a in fn.annotations:
                if a.kind != "target":
                    continue
                if a.args.get(0) == "fpga":
                    out.append(fn)
                    break
        return out

    def _merge_constraints(
        self,
        constraints: dict,
        fpga_funcs: list[EMLFunction],
        target_dict: dict,
    ) -> dict:
        """Merge user constraints with per-function @target args.
        User constraints win over per-function args; per-function
        wins over target defaults."""
        merged = dict(target_dict)
        for fn in fpga_funcs:
            for a in fn.annotations:
                if a.kind == "target" and a.args.get(0) == "fpga":
                    for k, v in a.args.items():
                        if k == 0:
                            continue
                        merged[k] = v
        merged.update(constraints)
        return merged

    def _count_ops_in_function(
        self, fn: EMLFunction,
    ) -> dict[str, int]:
        """Walk fn.body, return {op_name: count} for transcendentals."""
        counts: dict[str, int] = {}

        def walk(node: ASTNode | None) -> None:
            if node is None:
                return
            if node.kind in _TRANSCENDENTAL_NODE_KINDS:
                op = _TRANSCENDENTAL_NODE_KINDS[node.kind]
                if op == "_eml":
                    counts["exp"] = counts.get("exp", 0) + 1
                    counts["ln"] = counts.get("ln", 0) + 1
                else:
                    counts[op] = counts.get(op, 0) + 1
            for c in node.children:
                walk(c)

        walk(fn.body)
        return counts

    def _select_precision(
        self,
        fn: EMLFunction,
        forced: Optional[str],
    ) -> int:
        """Per-function precision: forced override > @target arg >
        chain-order rule."""
        if forced:
            return _precision_str_to_bits(forced)
        for a in fn.annotations:
            if a.kind == "target" and a.args.get(0) == "fpga":
                p = a.args.get("precision")
                if p:
                    return _precision_str_to_bits(p)
        co = (fn.profile or {}).get("chain_order", 0)
        if co >= 3:
            return 64
        if co >= 1:
            return 32
        return 16


def _precision_str_to_bits(s: str) -> int:
    """'float16'/'float32'/'float64' -> 16/32/64. Defaults to 32
    on unrecognized input."""
    table = {
        "float16": 16, "f16": 16, "fp16": 16, "16": 16,
        "float32": 32, "f32": 32, "fp32": 32, "32": 32,
        "float64": 64, "f64": 64, "fp64": 64, "64": 64,
    }
    return table.get(str(s), 32)
