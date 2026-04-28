"""End-to-end integration tests.

SCAFFOLD -- real tests land as backends mature. For now, a
single smoke test that the example files exist and the CLI
runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_examples_exist(example_files):
    """The 10 demo .eml files must all be present."""
    assert len(example_files) >= 10
    expected = {
        "hello.eml", "pid_basic.eml", "pid_nonlinear.eml",
        "motor_foc.eml", "trajectory.eml", "kalman.eml",
        "arrhenius.eml", "bessel_fm.eml", "sigmoid.eml",
        "orbit.eml",
    }
    actual = {p.name for p in example_files}
    assert expected.issubset(actual)


def test_cli_version(repo_root):
    """eml-compile --version should print a version string."""
    result = subprocess.run(
        [sys.executable, "tools/cli/main.py", "--version"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "eml-compile" in result.stdout or "eml-compile" in result.stderr
