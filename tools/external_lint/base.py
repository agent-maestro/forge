"""Abstract base for external-toolchain lint runners.

Subclasses wrap one CLI (`verilator`, `dxc`, `xcrun metal ...`)
and parse its diagnostic format into the uniform `LintIssue`
schema. The `lint(source)` method handles subprocess invocation,
PATH lookup, timeout, and the missing-tool downgrade path.

Design contract for a subclass:

  * Set ``tool``: the executable name as it appears on PATH.
  * Set ``language``: short identifier (``"verilog"``, ``"hlsl"``).
  * Implement ``_argv(source)``: build the argv list for one file.
  * Implement ``_parse(stdout, stderr, returncode)``: produce a
    ``LintResult``. Subclasses own the diagnostic-format regex.

The base ``lint(source)`` orchestrates: PATH check, subprocess run
with timeout, exception capture, then ``_parse`` on the output.
A subprocess that times out yields a ``LintResult`` with one
synthetic Error issue carrying ``code='TIMEOUT'``.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LintSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class LintIssue:
    """One diagnostic from an external linter.

    `file`, `line`, `column` may be ``None`` when the linter emits a
    file-level message with no position. `code` is the linter's own
    short code (e.g. Verilator's ``WIDTH``, DXC's ``HLSL_E####``);
    ``None`` when the linter didn't emit one.
    """
    severity: LintSeverity
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    code: str | None = None


@dataclass(frozen=True)
class LintResult:
    """Outcome of one `ExternalLinter.lint()` call.

    Invariants:
      * If ``tool_unavailable`` is True, ``ok`` is True and ``issues``
        is empty: callers can treat this as a clean skip.
      * ``ok`` is True iff there are no Error-severity issues. Warnings
        do not flip ``ok`` to False -- that's a downstream policy choice.
    """
    ok: bool
    tool_unavailable: bool = False
    issues: tuple[LintIssue, ...] = field(default_factory=tuple)
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    elapsed_s: float = 0.0

    def errors(self) -> tuple[LintIssue, ...]:
        return tuple(i for i in self.issues if i.severity is LintSeverity.ERROR)

    def warnings(self) -> tuple[LintIssue, ...]:
        return tuple(i for i in self.issues if i.severity is LintSeverity.WARNING)


_DEFAULT_TIMEOUT_S = 60.0


class ExternalLinter(ABC):
    """Base class for one CLI-backed linter.

    Construct, call ``lint(source_path)``, get a ``LintResult``.
    Subclasses pin ``tool`` and ``language`` and implement ``_argv``
    + ``_parse``. The base owns subprocess + path lookup + timeout +
    failure containment.
    """

    #: Executable name as it appears on PATH.
    tool: str = ""
    #: Short language identifier used in error messages and test IDs.
    language: str = ""

    def __init__(self, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s

    # ── PATH check ─────────────────────────────────────────────────

    def available(self) -> bool:
        """Return True iff `self.tool` resolves on PATH."""
        return shutil.which(self.tool) is not None

    def tool_path(self) -> str | None:
        """Resolved absolute path to the tool, or None if missing."""
        return shutil.which(self.tool)

    # ── Subclass hooks ────────────────────────────────────────────

    @abstractmethod
    def _argv(self, source: Path) -> list[str]:
        """Argv for one source file. Should NOT include the executable
        name (the base prepends it from `self.tool_path()`)."""

    @abstractmethod
    def _parse(self, stdout: str, stderr: str, returncode: int) -> tuple[LintIssue, ...]:
        """Parse linter output into LintIssue tuple."""

    # ── Public entry point ────────────────────────────────────────

    def lint(self, source: Path) -> LintResult:
        """Run the linter on one source file."""
        if not source.is_file():
            raise FileNotFoundError(
                f"{self.language}: source not found: {source}"
            )
        tool_path = self.tool_path()
        if tool_path is None:
            return LintResult(ok=True, tool_unavailable=True)
        argv = [tool_path, *self._argv(source)]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            return LintResult(
                ok=False,
                issues=(
                    LintIssue(
                        severity=LintSeverity.ERROR,
                        message=(f"{self.tool} timed out after "
                                  f"{self.timeout_s}s"),
                        code="TIMEOUT",
                    ),
                ),
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                elapsed_s=time.monotonic() - t0,
            )
        elapsed = time.monotonic() - t0
        issues = self._parse(proc.stdout, proc.stderr, proc.returncode)
        # `ok` requires BOTH a clean exit AND no Error-severity issues.
        # The returncode check is the silent-failure backstop: if the
        # tool emits an unrecognized error format (e.g. an unknown-CLI-
        # flag message) the parser may extract zero issues but exit
        # non-zero -- without this gate the result would falsely report
        # `ok=True`.
        no_error_issues = not any(
            i.severity is LintSeverity.ERROR for i in issues
        )
        ok = (proc.returncode == 0) and no_error_issues
        return LintResult(
            ok=ok,
            issues=issues,
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            elapsed_s=elapsed,
        )
