"""Verilator wrapper -- lint Verilog / SystemVerilog produced by the
`hardware.hdl_gen.verilog_backend` emitter.

Usage::

    from tools.external_lint.verilog import VerilogLinter

    result = VerilogLinter().lint(Path("out.sv"))
    if not result.ok:
        for err in result.errors():
            print(err)

When ``verilator`` is missing on PATH, ``result.tool_unavailable`` is
True and ``result.ok`` is True -- callers (including pytest) skip
gracefully rather than failing.

Verilator diagnostic format (verified against verilator 5.x)::

    %Error: file.v:5:3: syntax error, unexpected ';'
    %Error-NAMECONFLICT: file.v:5:3: Identifier ...
    %Warning-WIDTH: file.v:10:7: Operator ASSIGN expects ...
    %Warning-UNUSED: file.v:3:9: Signal is not used: 'foo'

Continuation lines (Verilator emits indented context after a primary
diagnostic) are ignored -- they're recoverable from `stdout` if a
caller wants the full report.
"""
from __future__ import annotations

import re
from pathlib import Path

from tools.external_lint.base import (
    ExternalLinter,
    LintIssue,
    LintSeverity,
)


# %Severity[-CODE]: file:line[:col]: message
# (?:-(\w+))? -- optional `-WIDTH`/`-UNUSED`/etc. code
# col is sometimes absent in older verilator outputs
_DIAG_RE = re.compile(
    r"^%(?P<sev>Error|Warning|Info)"
    r"(?:-(?P<code>\w+))?:\s+"
    r"(?P<file>[^:\s]+):(?P<line>\d+)"
    r"(?::(?P<col>\d+))?:\s+"
    r"(?P<msg>.+)$"
)

_SEVERITY_MAP = {
    "Error": LintSeverity.ERROR,
    "Warning": LintSeverity.WARNING,
    "Info": LintSeverity.INFO,
}

# "Exiting due to N error(s), N warning(s)" -- a summary line we drop.
_EXITING_RE = re.compile(r"^%Error:\s*Exiting due to ")


class VerilogLinter(ExternalLinter):
    """Run ``verilator --lint-only`` on a single Verilog/SystemVerilog file."""

    tool = "verilator"
    language = "verilog"

    def _argv(self, source: Path) -> list[str]:
        argv = ["--lint-only", "--quiet", "-Wall"]
        if source.suffix.lower() == ".sv":
            argv.append("--sv")
        argv.append(str(source))
        return argv

    def _parse(self, stdout: str, stderr: str, returncode: int) -> tuple[LintIssue, ...]:
        # Verilator writes diagnostics to stderr; stdout is usually empty
        # under --lint-only --quiet. Combine to be defensive.
        issues: list[LintIssue] = []
        for line in (stderr + "\n" + stdout).splitlines():
            line = line.rstrip()
            if not line:
                continue
            if _EXITING_RE.match(line):
                continue
            m = _DIAG_RE.match(line)
            if not m:
                continue
            sev = _SEVERITY_MAP.get(m.group("sev"))
            if sev is None:
                continue
            col = m.group("col")
            issues.append(
                LintIssue(
                    severity=sev,
                    file=m.group("file"),
                    line=int(m.group("line")),
                    column=int(col) if col is not None else None,
                    code=m.group("code"),
                    message=m.group("msg").strip(),
                )
            )
        return tuple(issues)
