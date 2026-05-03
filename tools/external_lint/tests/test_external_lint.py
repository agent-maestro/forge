"""Unit + integration tests for the external-lint runners.

Pure-Python paths (parsing, severity routing, missing-tool downgrade)
test on every machine. The "real" Verilator integration test skips
when ``verilator`` is not on PATH.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.external_lint.base import (
    ExternalLinter,
    LintIssue,
    LintResult,
    LintSeverity,
)
from tools.external_lint.verilog import VerilogLinter


# ──────── Helpers ────────

class _StubLinter(ExternalLinter):
    """Minimal subclass for testing the base logic in isolation."""
    tool = "stub-linter-not-on-path"
    language = "stub"

    def _argv(self, source: Path) -> list[str]:
        return [str(source)]

    def _parse(self, stdout, stderr, returncode):
        return tuple(
            LintIssue(severity=LintSeverity.ERROR, message=line)
            for line in stdout.splitlines() if line
        )


class _RealEchoLinter(ExternalLinter):
    """Subclass that resolves to ``echo`` for end-to-end subprocess tests."""
    tool = "echo"
    language = "echo"

    def __init__(self, payload: str = "", **kw):
        super().__init__(**kw)
        self._payload = payload

    def _argv(self, source: Path) -> list[str]:
        return [self._payload]

    def _parse(self, stdout, stderr, returncode):
        if "ERR:" in stdout:
            return (LintIssue(severity=LintSeverity.ERROR,
                                message=stdout.strip()),)
        if "WARN:" in stdout:
            return (LintIssue(severity=LintSeverity.WARNING,
                                message=stdout.strip()),)
        return ()


# ──────── Base: missing-tool downgrade ────────

def test_missing_tool_returns_unavailable(tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("hello")
    result = _StubLinter().lint(src)
    assert result.tool_unavailable is True
    assert result.ok is True
    assert result.issues == ()


def test_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _StubLinter().lint(tmp_path / "does-not-exist.v")


def test_available_reflects_path():
    assert _StubLinter().available() is False
    if shutil.which("echo"):
        assert _RealEchoLinter().available() is True


# ──────── Base: subprocess + parsing routing ────────

@pytest.mark.skipif(shutil.which("echo") is None, reason="needs echo on PATH")
def test_subprocess_invocation_routes_to_parse(tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("hello")
    linter = _RealEchoLinter(payload="ERR: synthetic")
    result = linter.lint(src)
    assert result.ok is False
    assert len(result.issues) == 1
    assert result.issues[0].severity is LintSeverity.ERROR
    assert "ERR:" in result.issues[0].message
    assert result.elapsed_s >= 0.0


@pytest.mark.skipif(shutil.which("echo") is None, reason="needs echo on PATH")
def test_warning_only_keeps_ok_true(tmp_path):
    src = tmp_path / "x.txt"
    src.write_text("hello")
    linter = _RealEchoLinter(payload="WARN: cosmetic")
    result = linter.lint(src)
    assert result.ok is True
    assert len(result.issues) == 1
    assert result.issues[0].severity is LintSeverity.WARNING
    assert result.warnings() == result.issues
    assert result.errors() == ()


# ──────── Base: timeout ────────

def test_timeout_yields_synthetic_error(tmp_path):
    src = tmp_path / "x.v"
    src.write_text("// trivial")
    linter = _RealEchoLinter(payload="never-runs", timeout_s=0.01)
    if not linter.available():
        pytest.skip("needs echo on PATH")
    fake_exc = subprocess.TimeoutExpired(cmd=["echo"], timeout=0.01)
    with patch("tools.external_lint.base.subprocess.run", side_effect=fake_exc):
        result = linter.lint(src)
    assert result.ok is False
    assert len(result.issues) == 1
    assert result.issues[0].code == "TIMEOUT"
    assert result.issues[0].severity is LintSeverity.ERROR


# ──────── VerilogLinter: argv shape ────────

def test_verilog_argv_v_extension(tmp_path):
    src = tmp_path / "foo.v"
    src.write_text("// stub")
    argv = VerilogLinter()._argv(src)
    assert argv[:3] == ["--lint-only", "--quiet", "-Wall"]
    assert "--sv" not in argv
    assert argv[-1] == str(src)


def test_verilog_argv_sv_extension_adds_sv_flag(tmp_path):
    src = tmp_path / "foo.sv"
    src.write_text("// stub")
    argv = VerilogLinter()._argv(src)
    assert "--sv" in argv
    assert argv[-1] == str(src)


# ──────── VerilogLinter: diagnostic parser ────────

def test_verilog_parse_error_with_code():
    stderr = (
        "%Error-NAMECONFLICT: foo.v:5:3: Identifier 'sig' "
        "already declared\n"
    )
    issues = VerilogLinter()._parse("", stderr, 1)
    assert len(issues) == 1
    i = issues[0]
    assert i.severity is LintSeverity.ERROR
    assert i.code == "NAMECONFLICT"
    assert i.file == "foo.v"
    assert i.line == 5
    assert i.column == 3
    assert "sig" in i.message


def test_verilog_parse_error_without_code():
    stderr = "%Error: bar.v:10:7: syntax error, unexpected ';'\n"
    issues = VerilogLinter()._parse("", stderr, 1)
    assert len(issues) == 1
    assert issues[0].code is None
    assert issues[0].severity is LintSeverity.ERROR
    assert issues[0].line == 10


def test_verilog_parse_warning_with_code():
    stderr = ("%Warning-WIDTH: out.sv:42:9: Operator ASSIGN expects "
              "8 bits on the Assign RHS, but RHS generates 32.\n")
    issues = VerilogLinter()._parse("", stderr, 0)
    assert len(issues) == 1
    i = issues[0]
    assert i.severity is LintSeverity.WARNING
    assert i.code == "WIDTH"
    assert i.column == 9


def test_verilog_parse_drops_exiting_summary():
    stderr = (
        "%Error: foo.v:5:3: real error\n"
        "%Error: Exiting due to 1 error(s)\n"
    )
    issues = VerilogLinter()._parse("", stderr, 1)
    assert len(issues) == 1  # summary line dropped
    assert issues[0].file == "foo.v"


def test_verilog_parse_ignores_continuation_lines():
    stderr = (
        "%Warning-WIDTH: foo.v:10:7: Operator expects 8 bits\n"
        "                : ... see also: bar.v:3\n"
        "%Error: foo.v:11:1: end of file\n"
    )
    issues = VerilogLinter()._parse("", stderr, 1)
    assert len(issues) == 2
    assert {i.severity for i in issues} == {
        LintSeverity.WARNING, LintSeverity.ERROR,
    }


def test_verilog_parse_ok_when_no_diagnostics():
    issues = VerilogLinter()._parse("", "", 0)
    assert issues == ()


def test_verilog_parse_handles_missing_column():
    stderr = "%Warning-UNUSED: foo.v:3: Signal is not used: 'foo'\n"
    issues = VerilogLinter()._parse("", stderr, 0)
    assert len(issues) == 1
    assert issues[0].column is None
    assert issues[0].line == 3


# ──────── VerilogLinter: integration (skips when verilator missing) ────────

_HAS_VERILATOR = shutil.which("verilator") is not None


@pytest.mark.skipif(not _HAS_VERILATOR, reason="needs verilator on PATH")
def test_verilog_lints_clean_module(tmp_path):
    src = tmp_path / "ok.sv"
    src.write_text("""\
module ok (
    input  logic       clk,
    input  logic [7:0] a,
    input  logic [7:0] b,
    output logic [8:0] s
);
    always_ff @(posedge clk) begin
        s <= {1'b0, a} + {1'b0, b};
    end
endmodule
""")
    result = VerilogLinter().lint(src)
    assert result.tool_unavailable is False
    assert result.ok is True, f"unexpected issues: {result.issues}"


@pytest.mark.skipif(not _HAS_VERILATOR, reason="needs verilator on PATH")
def test_verilog_lints_broken_module_reports_error(tmp_path):
    src = tmp_path / "broken.sv"
    src.write_text("""\
module broken (
    input  logic clk,
    output logic q
)
    always_ff @(posedge clk) q <= ~q;
endmodule
""")
    result = VerilogLinter().lint(src)
    assert result.tool_unavailable is False
    assert result.ok is False
    assert len(result.errors()) >= 1


@pytest.mark.skipif(_HAS_VERILATOR, reason="exercises the unavailable path")
def test_verilog_skips_when_verilator_missing(tmp_path):
    src = tmp_path / "x.sv"
    src.write_text("module x; endmodule\n")
    result = VerilogLinter().lint(src)
    assert result.tool_unavailable is True
    assert result.ok is True


# ──────── package re-exports ────────

def test_package_reexports():
    from tools.external_lint import (
        ExternalLinter as _EL,
        LintIssue as _LI,
        LintResult as _LR,
        LintSeverity as _LS,
    )
    assert _EL is ExternalLinter
    assert _LI is LintIssue
    assert _LR is LintResult
    assert _LS is LintSeverity
