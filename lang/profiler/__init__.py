"""EML-lang profiler.

Wires the parsed AST into the eml-cost analyzer + dynamics counter
so every function's `profile` field carries chain order, cost
class, dynamics, FPGA estimate, and stability warnings BEFORE
codegen runs.

See `lang/spec/EML_LANG_DESIGN.md` section 1.3.
"""

from lang.profiler.profiler import Profiler

__all__ = ["Profiler"]
