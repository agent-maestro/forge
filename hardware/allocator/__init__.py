"""FPGA resource allocator (Patent #14).

Given a program's aggregate Pfaffian profile + user constraints
(`clock_mhz`, `precision`, `max_luts`, `max_dsps`, `max_brams`),
decide how many transcendental units to instantiate, whether to
share or dedicate them, what bit-widths to use, and how deep to
pipeline.

The allocation plan is consumed by the Verilog/VHDL/Chisel
backends.
"""

from hardware.allocator.allocator import (
    AllocationPlan,
    CompileError,
    FPGAAllocator,
    TranscendentalUnit,
)

__all__ = [
    "AllocationPlan",
    "CompileError",
    "FPGAAllocator",
    "TranscendentalUnit",
]
