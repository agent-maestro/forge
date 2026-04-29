"""Tests for the Verilog backend (`hardware.hdl_gen.verilog_backend`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.verilog_backend import VerilogBackend
from lang.parser import parse_file, parse_source
from lang.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> VerilogBackend:
    return VerilogBackend()


def _allocate_and_compile(
    src: str, profiler: Profiler, backend: VerilogBackend,
) -> str:
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    return backend.compile(mod, plan)


# ── Header / structure ──────────────────────────────────────────────


def test_header_includes_target_device_and_throughput(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x * x }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "Target device: Arty A7-100" in out
    assert "Msamples/s" in out
    assert "`default_nettype none" in out


def test_module_has_standard_pipeline_interface(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x + 1.0 }'''
    out = _allocate_and_compile(src, profiler, backend)
    # Standard ports
    assert "input  wire             clk" in out
    assert "input  wire             rst" in out
    assert "input  wire             valid_in" in out
    assert "output reg              valid_out" in out
    assert "output reg signed [WIDTH-1:0] result" in out


def test_input_port_per_param(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(a: Real, b: Real, c: Real) -> Real { a + b * c }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "input  wire signed [WIDTH-1:0] a," in out
    assert "input  wire signed [WIDTH-1:0] b," in out
    assert "input  wire signed [WIDTH-1:0] c," in out


# ── Operators ───────────────────────────────────────────────────────


def test_arithmetic_chain_emits_assigns(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real, y: Real) -> Real { x + y * x }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "assign" in out
    # The mul operator comes through directly.
    assert "y * x" in out or "x * y" in out
    assert " + " in out


def test_unary_minus_emits_negation(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { -x }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "= -" in out


def test_clamp_emits_ternary_chain(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { clamp(x, -1.0, 1.0) }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "?" in out  # ternary operator
    assert ":" in out


def test_transcendental_op_instantiates_module(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { exp(x) }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "eml_exp" in out
    # Standard sub-instance ports
    assert ".clk(clk)" in out
    assert ".rst(rst)" in out


def test_sin_cos_get_distinct_modules(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { sin(x) + cos(x) }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "eml_sin" in out
    assert "eml_cos" in out


def test_eml_primitive_emits_exp_minus_ln(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real, y: Real) -> Real { eml(x, y) }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "eml_exp" in out
    assert "eml_ln" in out


# ── User function calls ─────────────────────────────────────────────


def test_user_function_call_emits_sub_pipeline(profiler, backend):
    src = '''module t;
fn helper(x: Real) -> Real { x * 2.0 }

@target(fpga, clock_mhz = 100)
fn caller(x: Real) -> Real { helper(x) + 1.0 }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "helper_pipeline" in out


# ── Output register ─────────────────────────────────────────────────


def test_output_is_registered_with_reset(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn f(x: Real) -> Real { x + x }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "always @(posedge clk)" in out
    assert "if (rst)" in out
    assert "valid_out <= 1'b0" in out


# ── motor_control.eml integration ──────────────────────────────────


def test_motor_control_realtime_control_compiles_to_verilog(
    profiler: Profiler, backend: VerilogBackend,
):
    """The canonical demo's @target(fpga) function emits a real
    Verilog module."""
    mod = parse_file(EXAMPLES_DIR / "motor_control.eml")
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    out = backend.compile(mod, plan)
    assert "module realtime_control_pipeline" in out
    # It calls pid_output internally
    assert "pid_output_pipeline" in out
    # Has the clamp ternary (since realtime_control uses clamp)
    assert "?" in out and ":" in out


# ── Width selection ────────────────────────────────────────────────


def test_design_with_no_transcendentals_defaults_to_32_bit(
    profiler, backend,
):
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn poly(x: Real, y: Real) -> Real { x + y }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "parameter WIDTH = 32" in out


def test_design_with_high_chain_order_uses_64_bit(profiler, backend):
    src = '''module t;
@target(fpga, clock_mhz = 100, precision = float64)
fn high(x: Real) -> Real { exp(sin(x)) }'''
    out = _allocate_and_compile(src, profiler, backend)
    assert "parameter WIDTH = 64" in out
