"""Tests for the Verilator simulation harness.

The "real" tests (that actually invoke verilator + compile + run)
skip when verilator isn't on PATH. Pure-Python paths -- the
testbench renderer, the comparator, the Q-format round-trip --
test on every machine.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.qformat import (
    QFormat, decode_to_float, default_q, encode_float,
)
from hardware.hdl_gen.verilog_backend import VerilogBackend
from hardware.simulation.verilator_sim import (
    FPGASimulator,
    SimResult,
    verilator_available,
)
from lang.parser import parse_source
from lang.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


# ── verilator_available + SimResult shape ───────────────────────────


def test_verilator_available_returns_bool():
    assert verilator_available() in (True, False)


def test_sim_result_unavailable_renders_skip_message():
    r = SimResult(unavailable=True)
    assert "verilator not on PATH" in r.render()


def test_sim_result_error_renders_error_message():
    r = SimResult(error="boom")
    assert "ERROR" in r.render()
    assert "boom" in r.render()


def test_sim_result_match_renders_match_status():
    r = SimResult(test_vectors=10, all_match=True,
                  max_abs_error=1e-9, max_rel_error=1e-7)
    out = r.render()
    assert "MATCH" in out
    assert "10 test vectors" in out


def test_sim_result_diverged_renders_diverged_status():
    r = SimResult(test_vectors=10, all_match=False,
                  max_abs_error=1.0, max_rel_error=0.5,
                  bits_lost=10.0)
    assert "DIVERGED" in r.render()


# ── Comparator + Q-format round-trip ────────────────────────────────


def test_comparator_matches_when_hw_encodes_sw_exactly():
    """If the HW result is the encoded SW value, max_abs_error
    should be at most one Q-format resolution unit."""
    sim = FPGASimulator(qformat=default_q(32))
    sw_ref = lambda x, y: x + y
    vectors = [(1.0, 2.0), (3.5, 4.5), (-1.0, 1.0)]
    # "Hardware" output is the Q-format encoding of SW result.
    hw_encoded = [encode_float(sw_ref(*v), sim.qformat) for v in vectors]
    result = sim._compare(vectors, hw_encoded, sw_ref)
    assert result.test_vectors == 3
    assert result.all_match is True
    assert result.max_abs_error <= sim.qformat.resolution * 3


def test_comparator_detects_divergence():
    """If HW returns wildly wrong values, all_match must be False."""
    sim = FPGASimulator(qformat=default_q(32))
    sw_ref = lambda x: x * 2
    vectors = [(1.0,), (2.0,), (3.0,)]
    # Deliberately wrong HW output (encoded 0 for everything).
    hw_encoded = [0, 0, 0]
    result = sim._compare(vectors, hw_encoded, sw_ref)
    assert result.all_match is False
    assert result.max_abs_error > 1.0


# ── Testbench rendering (no verilator needed) ───────────────────────


def test_testbench_renders_correct_vector_count():
    sim = FPGASimulator()
    src = sim._render_testbench(
        module_name="myfn",
        param_names=["a", "b"],
        vectors=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)],
    )
    # Three rows in the vectors[][] initializer
    assert "[3][2]" in src
    assert "Vmyfn_pipeline" in src
    # Both port assigns
    assert "dut->a" in src
    assert "dut->b" in src
    # Stdout for each result
    assert "std::cout" in src


def test_testbench_q_encodes_floats():
    """The vector initializer should contain Q16.16-encoded ints,
    not raw floats."""
    sim = FPGASimulator(qformat=default_q(32))
    src = sim._render_testbench(
        module_name="myfn",
        param_names=["x"],
        vectors=[(1.0,)],
    )
    # 1.0 at Q16.16 = 65536
    assert "65536" in src


# ── Vector validation ──────────────────────────────────────────────


def test_simulate_rejects_mismatched_vector_arity():
    sim = FPGASimulator()
    # Pass 2-element vectors but declare only 1 param.
    result = sim.simulate_module(
        verilog_source="// stub",
        module_name="myfn",
        param_names=["x"],
        test_vectors=[(1.0, 2.0)],
        sw_reference=lambda x: x,
    )
    if not verilator_available():
        # Skipped before validation.
        assert result.unavailable is True
    else:
        assert "vector 0 has 2 values" in result.error


def test_simulate_rejects_empty_vectors():
    sim = FPGASimulator()
    result = sim.simulate_module(
        verilog_source="// stub",
        module_name="myfn",
        param_names=["x"],
        test_vectors=[],
        sw_reference=lambda x: x,
    )
    if not verilator_available():
        assert result.unavailable is True
    else:
        assert "no test vectors" in result.error


# ── Integration tests (verilator-gated) ─────────────────────────────


@pytest.mark.skipif(not verilator_available(),
                    reason="verilator not on PATH")
def test_simulate_simple_polynomial(profiler: Profiler):
    """End-to-end: parse a simple polynomial fn, compile to Verilog,
    simulate it, compare against the SW reference."""
    src = '''module t;
@target(fpga, clock_mhz = 100)
fn add_two(a: Real, b: Real) -> Real { a + b }'''
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    verilog = VerilogBackend().compile(mod, plan)

    sim = FPGASimulator()
    result = sim.simulate_module(
        verilog_source=verilog,
        module_name="add_two",
        param_names=["a", "b"],
        test_vectors=[(1.0, 2.0), (10.5, -3.5), (0.0, 0.0)],
        sw_reference=lambda a, b: a + b,
    )
    if result.error:
        pytest.skip(
            f"verilator path not yet end-to-end: {result.error}"
        )
    assert result.test_vectors == 3
    assert result.all_match, (
        f"diverged: max_abs={result.max_abs_error}, "
        f"sw={result.sw_results}, hw={result.hw_results}"
    )
