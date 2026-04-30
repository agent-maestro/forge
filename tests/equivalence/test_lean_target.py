"""Lean structural-equivalence target tests.

The Lean target proves the @verify(lean) blocks emitted for every
production-shape vertical compile cleanly. Without a Lean
toolchain we can only do a structural check (theorem name
present, MachLib import line found, proof tactic body found);
when `lean` is on PATH the runner additionally syntactically
validates the file. The same EquivalenceReport shape used by the
C/Rust paths gets reused so callers can mix all three.

These tests are NEVER skipped on toolchain availability -- the
structural check works everywhere. Lean-toolchain-dependent
behaviour (the syntactic validation pass) is exercised by
LeanRunner's own unit tests, not here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.equivalence import cross_target_check
from tools.equivalence.lean_runner import (
    LeanRunner,
    lake_available,
    lean_available,
)
from lang.parser.parser import parse_file


REPO_ROOT = Path(__file__).resolve().parents[2]


# ── Production-shape vertical cases with @verify(lean) ───────


VERIFIED_VERTICAL_CASES: list[tuple[str, str]] = [
    ("industries/aerospace/flight_control/autopilot.eml",
     "autopilot_step"),
    ("industries/automotive/powertrain/motor_foc.eml",
     "foc_d_axis"),
    ("industries/defense/navigation/ins.eml",
     "attitude_step"),
    ("industries/medical/devices/infusion_pump.eml",
     "motor_command"),
    ("industries/energy/renewable/mppt.eml",
     "mppt_step"),
    ("industries/robotics/kinematics/arm_6dof.eml",
     "arm_endpoint_x"),
]


@pytest.mark.parametrize(
    "path,fn_name",
    VERIFIED_VERTICAL_CASES,
    ids=[f"{c[0]}::{c[1]}" for c in VERIFIED_VERTICAL_CASES],
)
def test_vertical_lean_structural_check(
    path: str, fn_name: str,
) -> None:
    """Every @verify(lean)-annotated vertical function must emit
    Lean source that passes the structural check (right theorem
    name, right imports, proof-tactic body present)."""
    mod = parse_file(REPO_ROOT / path)
    runner = LeanRunner(mod, full_build=False)
    check = runner.check(fn_name)

    assert check.available, (
        f"{fn_name}: lean target unavailable -- "
        f"{check.error or 'no @verify(lean) found'}"
    )
    assert check.structural_ok, (
        f"{fn_name}: structural check failed:\n  "
        + "\n  ".join(check.structural_findings)
    )
    assert not check.error, (
        f"{fn_name}: lean error: {check.error}"
    )


# ── Cross-target harness wires lean in cleanly ────────────────


def test_cross_target_check_includes_lean_when_requested() -> None:
    """When `lean` is in the targets tuple, the Lean structural
    check shows up in the EquivalenceReport's targets dict."""
    r = cross_target_check(
        REPO_ROOT / "industries/defense/navigation/ins.eml",
        "attitude_step",
        [(0.0, 0.0)],
        targets=("python", "lean"),
    )
    assert "lean" in r.targets
    lean = r.targets["lean"]
    assert lean.available, f"lean unavailable: {lean.error}"
    assert lean.error == "", f"lean error: {lean.error}"
    # Overall match should still be True even though Lean
    # contributes no numeric outputs.
    assert r.overall_match


def test_cross_target_check_skips_lean_when_no_verify(
    tmp_path: Path,
) -> None:
    """A function with no @verify(lean) reports lean as
    available=False and doesn't break overall_match."""
    src = (
        "fn t(x: f64) -> f64 { x * x }\n"
    )
    f = tmp_path / "t.eml"
    f.write_text(src, encoding="utf-8")
    r = cross_target_check(
        f, "t", [(2.0,)],
        targets=("python", "lean"),
    )
    assert r.targets["lean"].available is False
    assert r.overall_match


# ── Toolchain detection helpers ───────────────────────────────


def test_lean_available_returns_bool() -> None:
    """Smoke-check the toolchain probes -- they should never raise."""
    assert isinstance(lean_available(), bool)
    assert isinstance(lake_available(), bool)


# ── Negative: malformed verify catches structural errors ──────


def test_missing_theorem_name_caught() -> None:
    """A @verify(lean) without a theorem= argument is structurally
    invalid; the runner reports it as a structural finding."""
    src = (
        "@verify(lean)\n"
        "fn t(x: f64) -> f64 { x }\n"
    )
    from lang.parser.parser import parse_source
    mod = parse_source(src)
    runner = LeanRunner(mod, full_build=False)
    check = runner.check("t")
    # Either available=False (no proper @verify(lean) parsed) or
    # available=True with a structural finding -- both signal an
    # author error, which is what we want here.
    assert (not check.available) or (not check.structural_ok), (
        "missing theorem= should not be reported as fully OK"
    )
