"""Automotive vertical integration tests.

Confirms `industries/automotive/powertrain/motor_foc.eml` flows
through every backend + the FPGA allocator, and that the
ISO 26262 cert package + ASIL mapping doc are in place.
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
AUTOMOTIVE_DIR = REPO_ROOT / "industries" / "automotive"
FOC_FILE = AUTOMOTIVE_DIR / "powertrain" / "motor_foc.eml"


@pytest.fixture(scope="module")
def foc_module():
    mod = parse_file(FOC_FILE)
    Profiler().profile_module(mod)
    return mod


# ── Source presence ────────────────────────────────────────────────


def test_motor_foc_source_exists():
    assert FOC_FILE.exists(), f"missing FOC example: {FOC_FILE}"


# ── Parse + profile ────────────────────────────────────────────────


def test_motor_foc_parses_and_profiles(foc_module):
    """Module parses cleanly with the expected function/const set."""
    assert foc_module.name == "motor_foc_automotive"
    fn_names = {f.name for f in foc_module.functions}
    assert {"park", "clarke", "pi_step", "foc_d_axis"} == fn_names
    for fn in foc_module.functions:
        assert fn.profile is not None


def test_park_chain_order_2(foc_module):
    """Park transform uses sin + cos -> chain order 2."""
    fn = next(f for f in foc_module.functions if f.name == "park")
    # Park returns a tuple; chain_order is the worst element.
    assert fn.profile["chain_order"] == 2


def test_clarke_chain_order_0(foc_module):
    """Clarke transform is pure arithmetic."""
    fn = next(f for f in foc_module.functions if f.name == "clarke")
    assert fn.profile["chain_order"] == 0


def test_foc_d_axis_carries_verify_annotation(foc_module):
    fn = next(f for f in foc_module.functions if f.name == "foc_d_axis")
    verify = [a for a in fn.annotations if a.kind == "verify"]
    assert len(verify) == 1
    assert verify[0].args.get("theorem") == "vd_command_within_inverter_limits"


def test_foc_d_axis_meets_asil_c_chain_order_bound(foc_module):
    """ASIL-C upper bound is chain_order <= 2 (per ASIL_mapping.md).
    The d-axis controller is pure PI -> chain 0 -> safely ASIL-D.
    Lock the bound as a regression guard."""
    fn = next(f for f in foc_module.functions if f.name == "foc_d_axis")
    assert fn.profile["chain_order"] <= 2, (
        f"foc_d_axis chain_order {fn.profile['chain_order']} "
        f"exceeds ASIL-C bound (<= 2)"
    )


def test_foc_d_axis_has_safety_clauses(foc_module):
    """3 requires + 1 ensures (per ISO 26262 §6.4.2)."""
    fn = next(f for f in foc_module.functions if f.name == "foc_d_axis")
    assert len(fn.requires) == 3
    assert len(fn.ensures) == 1


# ── All four backends compile cleanly ──────────────────────────────


def test_compiles_to_c(foc_module):
    src = CBackend().compile(foc_module)
    assert "double foc_d_axis(" in src
    # The Park transform shows up as a tuple-return struct
    assert "park_result_t" in src
    assert "mg_clamp(" in src


def test_compiles_to_rust(foc_module):
    src = RustBackend().compile(foc_module)
    assert "pub fn foc_d_axis(" in src
    assert "ParkResult" in src
    assert "mg_clamp(" in src


def test_compiles_to_lean(foc_module):
    src = LeanBackend().compile_module(foc_module)
    assert "theorem vd_command_within_inverter_limits" in src
    # The ensures clause's `result` rewrites to the function call
    assert "(foc_d_axis i_d_setpoint i_d_measured i_d_integral)" in src


def test_compiles_to_verilog(foc_module):
    plan = FPGAAllocator().allocate(foc_module)
    src = VerilogBackend().compile(foc_module, plan)
    assert "module foc_d_axis_pipeline" in src
    # Inner PI controller as a sub-pipeline call
    assert "pi_step_pipeline" in src
    # Clamp lowered to ternary on the actuator output
    assert "?" in src and ":" in src


# ── FPGA allocation fits a small EV-grade FPGA ────────────────────


def test_motor_foc_fits_arty_a7_budget(foc_module):
    """The FOC d-axis (chain 0, no transcendentals on the verified
    path) must fit comfortably on an Arty A7-100."""
    plan = FPGAAllocator().allocate(foc_module)
    assert plan.target_device == "Arty A7-100"
    assert plan.estimated_luts < 10_000
    assert plan.estimated_dsps < 100


# ── Cert package files ────────────────────────────────────────────


def test_iso_26262_compliance_guide_exists():
    guide = AUTOMOTIVE_DIR / "certification" / "ISO_26262.md"
    assert guide.exists()
    text = guide.read_text(encoding="utf-8")
    assert "ISO 26262" in text
    assert "ASIL" in text
    # References the FOC example
    assert "motor_foc" in text.lower()
    # Maps forge artifacts to ISO 26262 sections
    assert "6.7.4" in text


def test_asil_mapping_doc_exists():
    doc = AUTOMOTIVE_DIR / "certification" / "ASIL_mapping.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    # Mentions every ASIL level (the doc uses "ASIL-X" hyphenation
    # in prose; the table column header is just "ASIL").
    for asil in ("ASIL-A", "ASIL-B", "ASIL-C", "ASIL-D", "QM"):
        assert asil in text, f"missing ASIL reference: {asil}"
    # Includes the chain-order ↔ ASIL mapping
    assert "chain_order" in text
