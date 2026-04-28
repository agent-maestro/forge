"""HDL code-generation backends.

Each backend takes (program, allocation_plan) from the parser +
allocator and emits HDL source ready for synthesis or simulation.

Available (SCAFFOLD): verilog_backend.
"""

from hardware.hdl_gen.verilog_backend import VerilogBackend

__all__ = ["VerilogBackend"]
