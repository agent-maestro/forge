"""Tests for the SystemVerilog backend (`hardware.hdl_gen.systemverilog_backend`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.systemverilog_backend import SystemVerilogBackend
from lang.parser import parse_file, parse_source
from lang.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"
AUTOPILOT = REPO_ROOT / "industries" / "aerospace" / "flight_control" / "autopilot.eml"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> SystemVerilogBackend:
    return SystemVerilogBackend()


def _allocate_and_compile(
    src: str, profiler: Profiler, backend: SystemVerilogBackend,
) -> str:
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    return backend.compile(mod, plan)


def _allocate_and_compile_file(
    path: Path, profiler: Profiler, backend: SystemVerilogBackend,
) -> str:
    mod = parse_file(path)
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    return backend.compile(mod, plan)


# ── Modern SV style ────────────────────────────────────────────


def test_uses_logic_not_wire_or_reg(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x + 1.0 }'''
    out = _allocate_and_compile(src, profiler, backend)
    # Module ports use `logic` exclusively.
    assert "input  logic" in out
    assert "output logic" in out
    # No legacy wire/reg in port declarations.
    for ln in out.splitlines():
        if "input  wire" in ln or "output reg" in ln:
            pytest.fail(f"legacy port style leaked: {ln!r}")
    # Wire decls use `logic signed` too.
    assert "logic signed [WIDTH-1:0]" in out


def test_uses_always_ff(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x + 1.0 }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "always_ff @(posedge clk)" in out
    assert "always @(posedge clk)" not in out  # legacy form gone


def test_header_has_timescale(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "`timescale" in out


def test_parameter_uses_int_typed_form(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "parameter int WIDTH" in out


# ── SVA assertions from requires/ensures ───────────────────────


def test_autopilot_emits_sva_properties(profiler, backend):
    out = _allocate_and_compile_file(AUTOPILOT, profiler, backend)

    # Three requires → three assume properties.
    assert "property pre_autopilot_step_1" in out
    assert "property pre_autopilot_step_2" in out
    assert "property pre_autopilot_step_3" in out
    assert out.count("assume property") >= 3

    # One ensures → one assert property.
    assert "property post_autopilot_step_1" in out
    assert "assert property (post_autopilot_step_1)" in out
    assert "$error(\"autopilot_step: ensures #1 violated\")" in out

    # Clocking is derived from the design clock.
    assert "@(posedge clk) disable iff (rst)" in out

    # Pre uses valid_in, Post uses valid_out (different antecedents).
    assert "valid_in |->" in out
    assert "valid_out |->" in out


def test_sva_abs_lowers_to_signed_dollar_abs(profiler, backend):
    out = _allocate_and_compile_file(AUTOPILOT, profiler, backend)
    # `abs(...)` in a contract becomes `$abs($signed(...))` so
    # Verilator stays quiet about signedness.
    assert "$abs($signed(pitch_setpoint))" in out
    assert "$abs($signed(pitch_measured))" in out
    assert "$abs($signed(pitch_integral))" in out


def test_ensures_references_registered_result_not_combinational(
    profiler, backend,
):
    """The post property must fire when valid_out is high — at
    that cycle, `result` carries the registered value, not the
    combinational wire `_w<N>`. Substituting `result` for the EML
    `result` keyword is what makes the assertion meaningful."""
    out = _allocate_and_compile_file(AUTOPILOT, profiler, backend)
    # Find the post block.
    post_lines = []
    in_post = False
    for ln in out.splitlines():
        if "property post_autopilot_step_1" in ln:
            in_post = True
        if in_post:
            post_lines.append(ln)
        if in_post and "endproperty" in ln:
            break
    body = "\n".join(post_lines)
    # The body should reference `result`, not a combinational
    # wire like `_w9`.
    assert "$abs($signed(result))" in body
    assert not any(f"_w{n}" in body for n in range(20))


# ── No-contract function still emits cleanly ───────────────────


def test_function_without_contracts_has_no_sva_block(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x * 2.0 }'''
    out = _allocate_and_compile(src, profiler, backend)
    # No assume/assert when no requires/ensures.
    assert "assume property" not in out
    assert "assert property" not in out


# ── Industrial verticals that have @target(fpga) compile ──────


VERTICAL_FPGA_FILES: list[str] = [
    "industries/aerospace/flight_control/autopilot.eml",
    "industries/automotive/powertrain/motor_foc.eml",
    "industries/defense/navigation/ins.eml",
    "industries/energy/renewable/mppt.eml",
    "industries/medical/devices/infusion_pump.eml",
    "industries/robotics/kinematics/arm_6dof.eml",
]


@pytest.mark.parametrize("relpath", VERTICAL_FPGA_FILES)
def test_vertical_compiles(relpath, profiler, backend):
    path = REPO_ROOT / relpath
    if not path.is_file():
        pytest.skip(f"vertical not present: {relpath}")
    out = _allocate_and_compile_file(path, profiler, backend)
    assert "Generated by EML-lang SystemVerilog backend" in out
    assert "always_ff @(posedge clk)" in out
    assert "module " in out and "_pipeline" in out
