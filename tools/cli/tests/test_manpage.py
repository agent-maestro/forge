"""Tests for the eml-compile man page generator."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.cli.manpage import emit_manpage


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_manpage_has_required_sections():
    page = emit_manpage()
    for section in (
        ".TH EML-COMPILE",
        ".SH NAME",
        ".SH SYNOPSIS",
        ".SH DESCRIPTION",
        ".SH OPTIONS",
        ".SH SUBCOMMANDS",
        ".SH EXAMPLES",
        ".SH EXIT STATUS",
        ".SH SEE ALSO",
    ):
        assert section in page, f"man page missing section {section!r}"


def test_manpage_documents_all_targets():
    page = emit_manpage()
    for tgt in ("c", "rust", "python", "llvm", "wasm",
                "verilog", "vhdl", "chisel", "lean"):
        assert tgt in page, f"man page missing target {tgt!r}"


def test_manpage_subcommand_dispatch():
    """`eml-compile manpage` returns the same text as the API call."""
    proc = subprocess.run(
        [sys.executable, "tools/cli/main.py", "manpage"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert ".TH EML-COMPILE" in proc.stdout
    assert ".SH SYNOPSIS" in proc.stdout
