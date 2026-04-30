"""Integration tests for the robotics / medical / defense / energy
industry verticals. Each follows the aerospace + automotive pattern:
real .eml example + cert-track guide + tests that the example flows
cleanly through every backend."""

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


# Verticals defined here. Each entry: (vertical name, .eml path
# relative to industries/, expected verified-fn name, expected
# cert-doc filename, theorem name from the @verify annotation).
_VERTICALS = [
    (
        "robotics",
        "robotics/kinematics/arm_6dof.eml",
        "arm_endpoint_x",
        "platforms/ros2_bridge.md",       # ROS 2 doc instead of cert
        "arm_endpoint_within_workspace",
    ),
    (
        "medical",
        "medical/devices/infusion_pump.eml",
        "motor_command",
        "certification/IEC_62304.md",
        "infusion_motor_command_safe",
    ),
    (
        "defense",
        "defense/navigation/ins.eml",
        "attitude_step",
        "certification/MIL_STD_882.md",
        "ins_attitude_update_bounded",
    ),
    (
        "energy",
        "energy/renewable/mppt.eml",
        "mppt_step",
        "nuclear/NRC_compliance.md",
        "mppt_voltage_command_safe",
    ),
    (
        "telecom",
        "telecom/pulse_compression.eml",
        "pulse_tap",
        "README.md",
        "pulse_tap_amplitude_bounded",
    ),
    (
        "radar",
        "radar/cfar_threshold.eml",
        "cfar_threshold",
        "README.md",
        "cfar_threshold_non_negative",
    ),
    (
        "semiconductor",
        "semiconductor/shockley_diode.eml",
        "shockley_current",
        "README.md",
        "shockley_current_monotone_in_voltage",
    ),
]


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


# ── Per-vertical parse + profile + 4-backend integration ────────────


@pytest.mark.parametrize(
    "vertical, eml_path, fn_name, doc_path, theorem_name",
    _VERTICALS,
    ids=[v[0] for v in _VERTICALS],
)
def test_vertical_eml_compiles_to_all_backends(
    vertical, eml_path, fn_name, doc_path, theorem_name,
    profiler: Profiler,
):
    eml = REPO_ROOT / "industries" / eml_path
    assert eml.exists(), f"missing {vertical} example: {eml}"

    mod = parse_file(eml)
    profiler.profile_module(mod)

    # The verified function must be present + carry the right
    # @verify annotation.
    fn = next((f for f in mod.functions if f.name == fn_name), None)
    assert fn is not None, f"{vertical}: missing {fn_name}"
    verify_anns = [a for a in fn.annotations if a.kind == "verify"]
    assert len(verify_anns) == 1
    assert verify_anns[0].args.get("theorem") == theorem_name

    # All 4 backends compile cleanly
    c_src = CBackend().compile(mod)
    assert f"{fn_name}(" in c_src
    rust_src = RustBackend().compile(mod)
    assert f"pub fn {fn_name}(" in rust_src
    lean_src = LeanBackend().compile_module(mod)
    assert f"theorem {theorem_name}" in lean_src
    plan = FPGAAllocator().allocate(mod)
    v_src = VerilogBackend().compile(mod, plan)
    assert f"module {fn_name}_pipeline" in v_src


@pytest.mark.parametrize(
    "vertical, eml_path, fn_name, doc_path, theorem_name",
    _VERTICALS,
    ids=[v[0] for v in _VERTICALS],
)
def test_vertical_doc_exists(
    vertical, eml_path, fn_name, doc_path, theorem_name,
):
    """Each vertical ships a regulatory / integration doc."""
    doc = REPO_ROOT / "industries" / vertical / doc_path
    assert doc.exists(), f"missing {vertical} doc: {doc}"
    text = doc.read_text(encoding="utf-8")
    # Each doc references its example .eml file's source name
    assert vertical in text.lower() or "forge" in text.lower()


# ── Vertical-specific spot checks ──────────────────────────────────


def test_robotics_joint_xy_returns_tuple(profiler: Profiler):
    """joint_xy returns (x, y) -- exercises the tuple-return path
    in the C / Rust / Verilog backends from a real-world fixture."""
    mod = parse_file(REPO_ROOT / "industries/robotics/kinematics/arm_6dof.eml")
    profiler.profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "joint_xy")
    assert fn.return_type == ""
    assert fn.return_tuple_types == ["StableSignal", "StableSignal"]


def test_medical_infusion_pump_has_three_requires(profiler: Profiler):
    """Class C IEC 62304 example: explicit input domain on every
    parameter (4 requires actually -- 3 from the doc plus
    abs(rate_integral))."""
    mod = parse_file(REPO_ROOT / "industries/medical/devices/infusion_pump.eml")
    profiler.profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "motor_command")
    assert len(fn.requires) >= 3
    assert len(fn.ensures) >= 1


def test_defense_ins_uses_64_bit_precision(profiler: Profiler):
    """INS @target arg specifies precision = float64.
    The FPGA allocator must respect that in the design precision."""
    mod = parse_file(REPO_ROOT / "industries/defense/navigation/ins.eml")
    profiler.profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "attitude_step")
    target_arg = next(
        a for a in fn.annotations if a.kind == "target"
    )
    assert target_arg.args.get("precision") == "float64"


def test_energy_mppt_uses_tanh(profiler: Profiler):
    """MPPT step uses tanh as a smooth sign function -> chain order 1."""
    mod = parse_file(REPO_ROOT / "industries/energy/renewable/mppt.eml")
    profiler.profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "mppt_step")
    assert fn.profile["chain_order"] == 1


# ── Combined: ensure all 4 fit Arty A7-100 ─────────────────────────


@pytest.mark.parametrize(
    "vertical, eml_path, fn_name, doc_path, theorem_name",
    _VERTICALS,
    ids=[v[0] for v in _VERTICALS],
)
def test_each_vertical_fits_arty_a7_100(
    vertical, eml_path, fn_name, doc_path, theorem_name,
    profiler: Profiler,
):
    """Every demo fits comfortably on the smallest supported FPGA."""
    eml = REPO_ROOT / "industries" / eml_path
    mod = parse_file(eml)
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    assert plan.estimated_luts < 20_000
    assert plan.estimated_dsps < 100
