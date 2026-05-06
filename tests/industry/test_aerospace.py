"""Aerospace vertical integration tests.

Confirms that `industries/aerospace/flight_control/autopilot.eml`
flows cleanly through every backend + the FPGA allocator, and
that the DO-178C cert template files are in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.verilog_backend import VerilogBackend
from lang.parser import parse_file
from lang.profiler import Profiler
from software.backends.c_backend import CBackend
from software.backends.rust_backend import RustBackend
from software.verification.lean.LeanBackend import LeanBackend


REPO_ROOT = Path(__file__).resolve().parents[2]
AEROSPACE_DIR = REPO_ROOT / "industries" / "aerospace"
AUTOPILOT_FILE = AEROSPACE_DIR / "flight_control" / "autopilot.eml"


@pytest.fixture(scope="module")
def autopilot_module():
    """Parse + profile the autopilot module once for the whole
    integration test class."""
    mod = parse_file(AUTOPILOT_FILE)
    Profiler().profile_module(mod)
    return mod


# ── Source file presence ────────────────────────────────────────────


def test_autopilot_source_exists():
    assert AUTOPILOT_FILE.exists(), (
        f"missing autopilot example: {AUTOPILOT_FILE}"
    )


# ── Parse + profile ─────────────────────────────────────────────────


def test_autopilot_parses_and_profiles(autopilot_module):
    """The autopilot module must parse cleanly and produce a
    populated profile for every LOCAL function. (Since the
    2026-04 stdlib refactor the module also imports
    `stdlib::control` -- filter to imported_from=None to compare
    just the locally-defined functions.)"""
    mod = autopilot_module
    assert mod.name == "autopilot"
    local = [f for f in mod.functions if f.imported_from is None]
    local_names = {f.name for f in local}
    assert local_names == {
        "gravity_compensation", "rate_controller", "autopilot_step",
    }
    for fn in local:
        assert fn.profile is not None
        assert fn.profile.get("status") == "ok"


def test_gravity_compensation_chain_order_2(autopilot_module):
    """gravity_compensation uses cos -> chain order 2 -- triggers
    the 1-trig-unit FPGA estimate."""
    fn = next(f for f in autopilot_module.functions
              if f.name == "gravity_compensation")
    assert fn.profile["chain_order"] == 2
    assert fn.profile["fpga_estimate"]["trig_units"] >= 1


def test_autopilot_step_carries_verify_annotation(autopilot_module):
    """autopilot_step is the @verify(lean) function -- it must
    carry the right annotation + theorem name."""
    fn = next(f for f in autopilot_module.functions
              if f.name == "autopilot_step")
    verify_anns = [a for a in fn.annotations if a.kind == "verify"]
    assert len(verify_anns) == 1
    assert verify_anns[0].args.get("theorem") == "autopilot_command_within_limits"


def test_autopilot_step_has_requires_and_ensures(autopilot_module):
    """The DO-178C example -- 3 input domains (now refinements after
    Phase F migration), 1 ensures."""
    fn = next(f for f in autopilot_module.functions
              if f.name == "autopilot_step")
    # Three single-variable input bounds were folded into parameter
    # refinements during the Phase F migration; only the multi-variable
    # / cross-parameter clauses remain in fn.requires (zero here).
    refined_params = [p for p in fn.params if p.refinement is not None]
    assert len(refined_params) == 3
    assert len(fn.requires) == 0
    assert len(fn.ensures) == 1


# ── All four backends compile cleanly ───────────────────────────────


def test_compiles_to_c(autopilot_module):
    src = CBackend().compile(autopilot_module)
    assert "double autopilot_step(" in src
    assert "mg_cos(" in src   # via gravity_compensation
    assert "mg_clamp(" in src  # actuator-limit gate


def test_compiles_to_rust(autopilot_module):
    src = RustBackend().compile(autopilot_module)
    assert "pub fn autopilot_step(" in src
    assert "mg_cos(" in src
    assert "mg_clamp(" in src


def test_compiles_to_lean(autopilot_module):
    src = LeanBackend().compile_module(autopilot_module)
    assert "theorem autopilot_command_within_limits" in src
    # The ensures clause references `result`; the backend must
    # rewrite that to the actual function call.
    assert "(autopilot_step pitch_setpoint pitch_measured pitch_integral)" in src


def test_compiles_to_verilog_unoptimized(autopilot_module):
    """With the inliner OFF, the inner rate_controller call
    materialises as a separate sub-pipeline."""
    plan = FPGAAllocator().allocate(autopilot_module)
    raw = VerilogBackend(optimize=False)
    src = raw.compile(autopilot_module, plan)
    assert "module autopilot_step_pipeline" in src
    assert "rate_controller_pipeline" in src


def test_compiles_to_verilog_optimized(autopilot_module):
    """With the optimizer ON (default), rate_controller gets
    inlined; the actuator clamp emerges as the standard ternary."""
    plan = FPGAAllocator().allocate(autopilot_module)
    src = VerilogBackend().compile(autopilot_module, plan)
    assert "module autopilot_step_pipeline" in src
    # Clamp lowered to the standard ternary chain on the actuator
    # output -- the actuator-limit safety gate.
    assert "ELEVATOR_MIN" in src and "ELEVATOR_MAX" in src
    assert "?" in src and ":" in src


# ── FPGA allocation ────────────────────────────────────────────────


def test_autopilot_fits_arty_a7_budget(autopilot_module):
    """The whole autopilot (3 fns, 1 trig unit, no exp/ln) must
    fit comfortably on an Arty A7-100."""
    plan = FPGAAllocator().allocate(autopilot_module)
    assert plan.target_device == "Arty A7-100"
    assert plan.estimated_luts < 5000   # design is small; budget is 63400
    assert plan.estimated_dsps < 50     # budget is 240


# ── Cert package files ─────────────────────────────────────────────


def test_do_178c_compliance_guide_exists():
    guide = AEROSPACE_DIR / "certification" / "DO_178C.md"
    assert guide.exists()
    text = guide.read_text(encoding="utf-8")
    assert "DO-178C" in text
    # Mentions the autopilot example
    assert "autopilot" in text.lower()
    # Maps forge artifacts to evidence categories
    assert "Source Code" in text
    assert "Object Code" in text


def test_lean_templates_present():
    """The cert guide references three template files."""
    tmpl_dir = AEROSPACE_DIR / "certification" / "lean_templates"
    for name in ("precision_bound", "domain_safety", "overflow_check"):
        path = tmpl_dir / f"{name}.lean.j2"
        assert path.exists(), f"missing cert template: {path}"
        # Each is a Jinja-style template referencing `theorem_name`.
        assert "{{ theorem_name }}" in path.read_text(encoding="utf-8")
