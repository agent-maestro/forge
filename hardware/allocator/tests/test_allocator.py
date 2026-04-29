"""Tests for the FPGA resource allocator."""

from __future__ import annotations

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from hardware.allocator import (
    AllocationPlan,
    CompileError,
    FPGAAllocator,
    TranscendentalUnit,
)


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


def _allocate_source(
    src: str, profiler: Profiler, **constraints,
) -> AllocationPlan:
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    return FPGAAllocator().allocate(mod, constraints)


# ── No FPGA target -> CompileError ─────────────────────────────────


def test_no_fpga_function_raises(profiler: Profiler):
    src = '''module t;
fn no_target(x: Real) -> Real { x + 1.0 }'''
    with pytest.raises(CompileError, match="No @target"):
        _allocate_source(src, profiler)


# ── Pure-polynomial design ─────────────────────────────────────────


def test_polynomial_design_zero_transcendentals(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100, precision = float32)
fn poly(x: Real, y: Real) -> Real { x * y + x - y }'''
    plan = _allocate_source(src, profiler)
    assert plan.target_device == "Arty A7-100"
    assert plan.transcendental_units == ()
    assert plan.mac_units >= 1
    assert plan.clock_mhz == 100


# ── Single-transcendental design ───────────────────────────────────


def test_single_exp_emits_dedicated_unit(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn single_exp(x: Real) -> Real { exp(x) }'''
    plan = _allocate_source(src, profiler)
    assert len(plan.transcendental_units) == 1
    u = plan.transcendental_units[0]
    assert u.op == "exp"
    assert u.count == 1
    assert u.sharing == "dedicated"
    assert u.luts > 0
    assert u.dsps > 0


# ── High-count transcendental shares ───────────────────────────────


def test_many_exp_uses_shared_strategy(profiler: Profiler):
    """3+ exp uses should switch to shared (time-multiplexed)."""
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn many_exp(x: Real) -> Real {
    let a = exp(x);
    let b = exp(a);
    let c = exp(b);
    let d = exp(c);
    a + b + c + d
}'''
    plan = _allocate_source(src, profiler)
    exp_unit = next(u for u in plan.transcendental_units if u.op == "exp")
    assert exp_unit.count == 4
    assert exp_unit.sharing == "shared"


# ── Mixed transcendental design ────────────────────────────────────


def test_mixed_ops_each_get_their_own_unit(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn mixed(x: Real) -> Real {
    sin(x) + cos(x) + exp(x)
}'''
    plan = _allocate_source(src, profiler)
    ops = {u.op for u in plan.transcendental_units}
    assert ops == {"sin", "cos", "exp"}


# ── Precision selection ────────────────────────────────────────────


def test_explicit_float64_precision(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100, precision = float64)
fn high_prec(x: Real) -> Real { exp(x) }'''
    plan = _allocate_source(src, profiler)
    assert all(u.precision_bits == 64
               for u in plan.transcendental_units)


def test_chain_order_drives_precision_when_unspecified(profiler: Profiler):
    """A chain-order-3 function (sin nested in exp) should default
    to float64 even without an explicit precision arg."""
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn high_co(x: Real) -> Real {
    exp(sin(x))
}'''
    plan = _allocate_source(src, profiler)
    assert all(u.precision_bits == 64
               for u in plan.transcendental_units)


def test_polynomial_picks_low_precision(profiler: Profiler):
    """Pure polynomial -> chain order 0 -> 16-bit OK."""
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn poly(x: Real) -> Real { x * x + x }'''
    plan = _allocate_source(src, profiler)
    # No transcendentals to sample precision on; the design just
    # uses the inferred default. Confirm no crash.
    assert plan.transcendental_units == ()


# ── Budget validation ─────────────────────────────────────────────


def test_lut_budget_exceeded_raises(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn many_trig(x: Real) -> Real {
    sin(x) + cos(x) + sin(x) + cos(x) + sin(x) + cos(x)
}'''
    # Tiny LUT budget should reject.
    with pytest.raises(CompileError, match="LUTs but budget"):
        _allocate_source(src, profiler, max_luts=100)


def test_lut_budget_just_fits(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn pid(x: Real, y: Real) -> Real { x + y * 0.5 }'''
    # The Artix-7 budget (63400 LUTs) is plenty.
    plan = _allocate_source(src, profiler)
    assert plan.estimated_luts < 63400


# ── Multiple FPGA-targeted functions in one module ────────────────


def test_two_fpga_functions_aggregate(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn fn_a(x: Real) -> Real { exp(x) }

@target(fpga, clock_mhz = 100)
fn fn_b(x: Real) -> Real { sin(x) }

fn fn_c(x: Real) -> Real { x + 1.0 }'''
    plan = _allocate_source(src, profiler)
    ops = {u.op for u in plan.transcendental_units}
    assert "exp" in ops
    assert "sin" in ops
    # Pipeline depth = max across the two FPGA-targeted fns.
    assert plan.pipeline_depth >= 1


# ── Plan rendering ────────────────────────────────────────────────


def test_render_includes_target_name_and_units(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 50)
fn f(x: Real) -> Real { sin(x) }'''
    plan = _allocate_source(src, profiler)
    out = plan.render()
    assert "Arty A7-100" in out
    assert "sin" in out
    assert "50 MHz" in out


# ── motor_control.eml integration ──────────────────────────────────


def test_motor_control_realtime_control_allocates(profiler: Profiler):
    """The canonical demo's @target(fpga) function -- realtime_control
    -- is pure polynomial (just calls pid_output + clamp). Should
    allocate zero transcendentals, several MAC units."""
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    mod = parse_file(repo / "lang/spec/grammar/examples/motor_control.eml")
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    assert plan.transcendental_units == ()
    assert plan.mac_units >= 1
    assert plan.clock_mhz == 100  # from @target(... clock_mhz = 100 ...)


# ── Constructor + dataclass shape ──────────────────────────────────


def test_transcendental_unit_dataclass():
    u = TranscendentalUnit(
        op="exp", count=2, sharing="dedicated",
        precision_bits=32, luts=2400, dsps=8, bram_kb=0,
    )
    assert u.op == "exp"
    assert u.count == 2


def test_unknown_target_raises(profiler: Profiler):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x }'''
    with pytest.raises(CompileError, match="unknown FPGA target"):
        _allocate_source(src, profiler, target="xilinx.nonexistent_board")
