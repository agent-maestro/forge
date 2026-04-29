"""EML-lang profiler.

Wires the parsed AST into the eml-cost analyzer + dynamics counter
so every function's `profile` field carries chain order, cost
class, dynamics, FPGA estimate, and stability warnings BEFORE
codegen runs.

See `lang/spec/EML_LANG_DESIGN.md` section 1.3.
"""

from lang.profiler.ast_to_sympy import ConvertResult, convert_function_body
from lang.profiler.profiler import Profiler

__all__ = ["ConvertResult", "Profiler", "convert_function_body"]
