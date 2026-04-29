"""Structural + Verilator-lint tests for the transcendental
module library.

These tests confirm that:

- Every transcendental NodeKind the Verilog backend dispatches to
  has a corresponding `.v` file on disk.
- Each `.v` file declares a module with the expected name, ports,
  and parameters that the backend's instance code expects.
- Each `.v` file passes `verilator --lint-only` when verilator is
  on PATH (skipped otherwise).

Together they catch the most common failure mode for the hardware
backend: the Python emitter calls a module that does not exist,
or has drifted from the expected interface.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest


MODULE_DIR = Path(__file__).resolve().parent.parent
EXPECTED_MODULES = [
    "eml_exp",
    "eml_ln",
    "eml_sin",
    "eml_cos",
    "eml_tan",
    "eml_sqrt",
    "eml_sinh",
    "eml_cosh",
    "eml_tanh",
    "eml_asin",
    "eml_acos",
    "eml_atan",
]


def _read(name: str) -> str:
    return (MODULE_DIR / f"{name}.v").read_text(encoding="utf-8")


# ── 1. Existence ──────────────────────────────────────────────


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_file_exists(name: str) -> None:
    path = MODULE_DIR / f"{name}.v"
    assert path.exists(), f"missing {path}"


# ── 2. Structural shape ───────────────────────────────────────


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_declaration(name: str) -> None:
    src = _read(name)
    # Module declaration with the expected name.
    assert re.search(
        rf"\bmodule\s+{re.escape(name)}\s*#\s*\(", src,
    ), f"{name}: module declaration not found"
    # Closing endmodule.
    assert "endmodule" in src, f"{name}: missing endmodule"


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_has_required_parameters(name: str) -> None:
    src = _read(name)
    for p in ("WIDTH", "FRAC", "PIPELINE_STAGES"):
        assert re.search(
            rf"\bparameter\s+{p}\b", src,
        ), f"{name}: missing parameter {p}"


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_has_required_ports(name: str) -> None:
    src = _read(name)
    required_ports = ("clk", "rst", "in_valid", "x_in",
                      "out_valid", "result")
    for port in required_ports:
        assert re.search(
            rf"\b(?:input|output)\s+wire[^\n;]*\b{port}\b", src,
        ), f"{name}: missing port {port}"


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_default_nettype_guarded(name: str) -> None:
    """Every module should re-establish `default_nettype wire after
    use, so it can be safely dropped into projects that use
    `default_nettype none."""
    src = _read(name)
    assert "`default_nettype none" in src, f"{name}: missing 'none' directive"
    assert "`default_nettype wire" in src, f"{name}: missing restore directive"


@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_has_pipeline_register(name: str) -> None:
    """Each module should advance valid_pipe each cycle."""
    src = _read(name)
    assert "valid_pipe" in src, f"{name}: missing valid_pipe register"
    assert "PIPELINE_STAGES" in src, (
        f"{name}: PIPELINE_STAGES not used in body"
    )


# ── 3. Verilator lint (optional) ──────────────────────────────


def _verilator_available() -> bool:
    return shutil.which("verilator") is not None


@pytest.mark.skipif(
    not _verilator_available(), reason="verilator not on PATH",
)
@pytest.mark.parametrize("name", EXPECTED_MODULES)
def test_module_passes_verilator_lint(name: str, tmp_path: Path) -> None:
    src = MODULE_DIR / f"{name}.v"
    r = subprocess.run(
        [
            "verilator", "--lint-only",
            "-Wno-WIDTH", "-Wno-UNUSED",
            "--top-module", name,
            str(src),
        ],
        cwd=str(tmp_path),
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        pytest.fail(f"{name} failed verilator lint:\n{r.stderr[:1000]}")
