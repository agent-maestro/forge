"""Cross-target equivalence harness.

Operational proof of Patent #22 (dual-target compilation): the same
.eml source produces equivalent results across every backend the
compiler emits to.

Public entry: `cross_target_check(eml_path, function_name, vectors,
tolerance=1e-9)` returns an `EquivalenceReport` summarising every
backend's outputs and their agreement with the Python SymPy
reference.

Backends that require an external toolchain (cargo, gcc, verilator)
report `available=False` rather than raising when the toolchain
isn't on PATH; tests can skip themselves accordingly.
"""

from tools.equivalence.harness import (
    EquivalenceReport,
    TargetResult,
    cross_target_check,
)

__all__ = ["EquivalenceReport", "TargetResult", "cross_target_check"]
