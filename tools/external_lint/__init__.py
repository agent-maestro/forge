"""External-toolchain lint runners.

Wraps third-party CLIs (Verilator for Verilog, future: DXC for HLSL,
xcrun for Metal, etc.) behind a uniform `ExternalLinter` interface.
Each backend that emits a target-language source file gets a matching
linter so CI can prove every emit is syntactically + structurally
valid in that ecosystem.

When the underlying tool is missing on PATH, linters return
``LintResult(tool_unavailable=True, ok=True)`` instead of raising,
so tests downgrade to skips on dev machines without the toolchain.
"""

from tools.external_lint.base import (
    ExternalLinter,
    LintIssue,
    LintResult,
    LintSeverity,
)

__all__ = [
    "ExternalLinter",
    "LintIssue",
    "LintResult",
    "LintSeverity",
]
