"""Verilator-based hardware simulation.

Builds the generated Verilog with Verilator, drives it with
test vectors, and compares output against the C reference.
On Blackwell: swap to a CUDA-resident batch simulator for
10K+ vector runs.

Reference: lang/spec/EML_LANG_DESIGN.md section 3.3.
SCAFFOLD.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SimResult:
    test_vectors: int
    max_abs_error: float
    max_rel_error: float
    bits_lost: int
    all_match: bool


class FPGASimulator:
    """Run software-vs-hardware comparison."""

    def simulate(
        self, verilog: str, test_vectors: list,
    ) -> SimResult:
        """Compile the Verilog with Verilator, run each vector
        through both software and hardware paths, return the
        comparison."""
        raise NotImplementedError("simulator body lands in Phase 3.3")
