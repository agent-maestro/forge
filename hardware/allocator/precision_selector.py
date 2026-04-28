"""Per-unit precision selection.

Given a function's chain order + declared precision constraint,
pick a bit width that meets the precision bound while minimizing
FPGA resource use.

Patent #14 + Patent #20 (quantization drift prediction).
SCAFFOLD.
"""

from __future__ import annotations


def select_precision(chain_order: int, declared_eps: float | None) -> str:
    """Return one of 'float16' | 'float32' | 'float64'."""
    if declared_eps is not None:
        if declared_eps < 1e-12:
            return "float64"
        if declared_eps < 1e-6:
            return "float32"
        return "float16"
    # Fall back to chain-order rule when no explicit eps declared.
    if chain_order >= 3:
        return "float64"
    if chain_order >= 1:
        return "float32"
    return "float16"
