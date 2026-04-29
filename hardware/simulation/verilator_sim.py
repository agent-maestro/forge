"""Verilator-based hardware simulation harness.

Compiles generated Verilog with verilator, drives it with test
vectors, and compares output against the C reference.

The dual-target patent (#22) claim -- "same source produces both
software and hardware with provable equivalence" -- is
*operationally* demonstrated when this harness reports
`all_match: True` on the same `.eml` source compiled to both
targets.

When verilator is NOT on PATH, every method returns gracefully
with `unavailable=True` instead of raising. CI integration tests
can skip themselves in that case.

Reference: lang/spec/EML_LANG_DESIGN.md section 3.3.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from hardware.hdl_gen.qformat import QFormat, decode_to_float, encode_float


@dataclass(frozen=True)
class SimResult:
    """Outcome of one simulator run."""
    test_vectors: int = 0
    all_match: bool = False
    max_abs_error: float = 0.0
    max_rel_error: float = 0.0
    bits_lost: float = 0.0
    sw_results: tuple[float, ...] = field(default_factory=tuple)
    hw_results: tuple[float, ...] = field(default_factory=tuple)
    unavailable: bool = False
    """True iff verilator wasn't on PATH; the harness ran no
    simulation but didn't crash."""
    error: str = ""
    """Set when the simulator failed for any reason other than
    'unavailable' (e.g. compilation error in the generated code)."""

    def render(self) -> str:
        if self.unavailable:
            return "  [verilator not on PATH; skipped]"
        if self.error:
            return f"  ERROR: {self.error}"
        marker = "MATCH" if self.all_match else "DIVERGED"
        return (
            f"  [{marker}] {self.test_vectors} test vectors\n"
            f"    max abs error: {self.max_abs_error:.6g}\n"
            f"    max rel error: {self.max_rel_error:.6g}\n"
            f"    bits of precision lost: {self.bits_lost:.2f}"
        )


def verilator_available() -> bool:
    """True iff `verilator` is on PATH."""
    return shutil.which("verilator") is not None


class FPGASimulator:
    """Run software-vs-hardware comparison via verilator."""

    def __init__(
        self,
        *,
        qformat: QFormat | None = None,
        timeout_s: float = 60.0,
    ):
        # Default: Q16.16 (matches the verilog backend's 32-bit default).
        from hardware.hdl_gen.qformat import default_q
        self.qformat = qformat or default_q(32)
        self.timeout_s = timeout_s

    def simulate_module(
        self,
        verilog_source: str,
        module_name: str,
        param_names: list[str],
        test_vectors: Iterable[tuple[float, ...]],
        sw_reference,
    ) -> SimResult:
        """Compile + simulate `<module_name>_pipeline` from
        `verilog_source`, drive it with `test_vectors`, compare each
        output to `sw_reference(*vec)`. Returns a SimResult.

        param_names: input port names IN PORT ORDER.
        test_vectors: iterable of float-tuples, one per param.
        sw_reference: callable taking the same float args, returning
                      a single float (the C-backend's compiled fn).
        """
        if not verilator_available():
            return SimResult(unavailable=True)

        vectors = list(test_vectors)
        if not vectors:
            return SimResult(error="no test vectors supplied")

        n_params = len(param_names)
        for i, v in enumerate(vectors):
            if len(v) != n_params:
                return SimResult(
                    error=(f"vector {i} has {len(v)} values "
                           f"but module has {n_params} params"),
                )

        with tempfile.TemporaryDirectory(prefix="forge_sim_") as tmp:
            tmp_path = Path(tmp)
            verilog_file = tmp_path / "design.v"
            verilog_file.write_text(verilog_source, encoding="utf-8")

            tb_file = tmp_path / f"tb_{module_name}.cpp"
            tb_file.write_text(
                self._render_testbench(
                    module_name, param_names, vectors,
                ),
                encoding="utf-8",
            )

            verilator_dir = tmp_path / "obj_dir"
            cmd_compile = [
                "verilator", "--cc", "--exe", "--build",
                "-Wno-fatal", "-Wno-WIDTH", "-Wno-UNUSED",
                "--top-module", f"{module_name}_pipeline",
                "-Mdir", str(verilator_dir),
                str(verilog_file),
                str(tb_file),
            ]
            try:
                r = subprocess.run(
                    cmd_compile, cwd=str(tmp_path),
                    capture_output=True, text=True,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired:
                return SimResult(
                    error=f"verilator compile timed out after "
                          f"{self.timeout_s}s",
                )
            if r.returncode != 0:
                return SimResult(
                    error=f"verilator compile failed:\n{r.stderr[:500]}",
                )

            # Locate the produced binary.
            sim_bin = verilator_dir / f"V{module_name}_pipeline"
            if not sim_bin.exists():
                exe_candidates = list(verilator_dir.glob(
                    f"V{module_name}_pipeline*"))
                if not exe_candidates:
                    return SimResult(
                        error=f"verilator did not produce a binary "
                              f"in {verilator_dir}",
                    )
                sim_bin = exe_candidates[0]

            try:
                r = subprocess.run(
                    [str(sim_bin)],
                    capture_output=True, text=True,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired:
                return SimResult(
                    error=f"sim run timed out after {self.timeout_s}s",
                )
            if r.returncode != 0:
                return SimResult(
                    error=f"sim run failed:\n{r.stderr[:500]}",
                )

            hw_encoded: list[int] = []
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    hw_encoded.append(int(line))
                except ValueError:
                    return SimResult(
                        error=f"non-integer line in sim output: "
                              f"{line!r}",
                    )

            if len(hw_encoded) != len(vectors):
                return SimResult(
                    error=(f"sim emitted {len(hw_encoded)} results "
                           f"but expected {len(vectors)}"),
                )

            return self._compare(vectors, hw_encoded, sw_reference)

    # ── Helpers ───────────────────────────────────────────────

    def _render_testbench(
        self,
        module_name: str,
        param_names: list[str],
        vectors: list[tuple[float, ...]],
    ) -> str:
        """Generate a C++ Verilator testbench that drives every
        vector through the DUT and prints each registered result."""
        n_params = len(param_names)
        n_vec = len(vectors)
        port_decls = "\n".join(
            f"        dut->{p} = vectors[i][{j}];"
            for j, p in enumerate(param_names)
        )
        vector_lines = []
        for v in vectors:
            encoded = [encode_float(x, self.qformat) for x in v]
            vector_lines.append("{" + ", ".join(map(str, encoded)) + "}")
        vectors_init = ",\n        ".join(vector_lines)

        return textwrap.dedent(f"""
            #include "V{module_name}_pipeline.h"
            #include "verilated.h"
            #include <iostream>
            #include <cstdint>

            int main(int argc, char** argv) {{
                Verilated::commandArgs(argc, argv);
                V{module_name}_pipeline* dut = new V{module_name}_pipeline;

                int64_t vectors[{n_vec}][{n_params}] = {{
                    {vectors_init}
                }};

                dut->rst = 1;
                dut->clk = 0; dut->eval();
                dut->clk = 1; dut->eval();
                dut->rst = 0;

                for (int i = 0; i < {n_vec}; i++) {{
            {port_decls}
                    dut->valid_in = 1;
                    dut->clk = 0; dut->eval();
                    dut->clk = 1; dut->eval();
                    // One more clock to register the output.
                    dut->clk = 0; dut->eval();
                    dut->clk = 1; dut->eval();
                    std::cout << (int64_t)dut->result << std::endl;
                }}

                delete dut;
                return 0;
            }}
        """).strip()

    def _compare(
        self,
        vectors: list[tuple[float, ...]],
        hw_encoded: list[int],
        sw_reference,
    ) -> SimResult:
        sw_results: list[float] = []
        hw_results: list[float] = []
        max_abs = 0.0
        max_rel = 0.0
        for vec, hw_int in zip(vectors, hw_encoded):
            sw = float(sw_reference(*vec))
            hw = decode_to_float(hw_int, self.qformat)
            sw_results.append(sw)
            hw_results.append(hw)
            err = abs(sw - hw)
            max_abs = max(max_abs, err)
            denom = max(abs(sw), 1e-12)
            max_rel = max(max_rel, err / denom)

        # `bits_lost` is a rough proxy: log2 of the relative-error
        # ratio against the Q-format's resolution.
        if max_rel > 0:
            bits_lost = max(
                0.0, math.log2(max_rel / self.qformat.resolution),
            )
        else:
            bits_lost = 0.0
        # Match tolerance: ~3 LSBs of the Q-format resolution.
        tolerance = 3 * self.qformat.resolution
        all_match = max_abs <= tolerance

        return SimResult(
            test_vectors=len(vectors),
            all_match=all_match,
            max_abs_error=max_abs,
            max_rel_error=max_rel,
            bits_lost=bits_lost,
            sw_results=tuple(sw_results),
            hw_results=tuple(hw_results),
        )
