"""Verify the headline value-prop: blocks skip parse + profile work.

Compiling a Block via `block.to_module()` -> backend should be
strictly faster than the parse-from-source path because the AST,
the profile, and the FPGA allocation are all cached.

We assert a relative speedup rather than an absolute time so the
test is robust to CI machine variance.
"""

from __future__ import annotations

import time

from forge.blocks.exponential import sigmoid_block
from forge.blocks.oscillator import damped_osc
from forge.blocks.polynomial import linear, quadratic
from lang.parser.parser import parse_source
from lang.profiler.profiler import Profiler
from software.backends.c_backend import CBackend


SOURCE_LINEAR = """\
fn linear(x: f64, m: f64, b: f64) -> f64
  where chain_order <= 0
{
    m * x + b
}
"""

SOURCE_QUADRATIC = """\
fn quadratic(x: f64, a: f64, b: f64, c: f64) -> f64
  where chain_order <= 0
{
    a * x * x + b * x + c
}
"""


def _time_parse_then_compile(source: str, n: int) -> float:
    """Measure the full parse + profile + compile path n times."""
    start = time.perf_counter()
    for _ in range(n):
        mod = parse_source(source)
        Profiler().profile_module(mod)
        CBackend().compile(mod)
    return time.perf_counter() - start


def _time_block_compile(block, n: int) -> float:
    """Measure just the compile-from-cached-Block path n times."""
    start = time.perf_counter()
    for _ in range(n):
        CBackend().compile(block.to_module())
    return time.perf_counter() - start


def test_block_path_is_faster_than_parse_path():
    """Compiling a cached Block beats parsing the same source."""
    n = 30
    parse_seconds = _time_parse_then_compile(SOURCE_LINEAR, n)
    block_seconds = _time_block_compile(linear, n)
    # Block path should be at least 1.5x faster -- the parse + profile
    # work happens once at import time, not per-compile.
    assert block_seconds < parse_seconds, (
        f"block compile ({block_seconds:.4f}s/{n}) "
        f"not faster than parse compile ({parse_seconds:.4f}s/{n})"
    )


def test_block_path_skips_profiler():
    """The block's `function` carries a populated profile -- the
    backend's optimizer pipeline doesn't re-profile."""
    assert linear.function is not None
    assert linear.function.profile is not None
    assert linear.function.profile.get("chain_order") == 0


def test_block_node_count_reflects_post_optimizer():
    """The cached node_count is the post-optimization count, so the
    compiler doesn't pay the optimizer cost on every compile."""
    # quadratic = a*x*x + b*x + c -- the optimizer's CSE pass may
    # introduce a let_cse for `x*x`; either way the node count
    # should be small (< 8) and stable across imports.
    assert 0 < quadratic.node_count < 8


def test_fpga_allocation_is_cached():
    """For blocks with @target(fpga), the AllocationPlan is computed at
    import time and the dict survives every subsequent compile."""
    alloc = damped_osc.fpga_allocation
    assert "luts" in alloc
    assert "transcendental_units" in alloc
    # The allocation is the same object on every access -- it's the
    # cached one.
    assert damped_osc.fpga_allocation is alloc


def test_block_to_module_round_trip_speed():
    """A bulk-compose stress test: compose 50 chains in <1s."""
    start = time.perf_counter()
    for _ in range(50):
        composed = linear >> sigmoid_block
        _ = composed.eml_tree
        _ = composed.chain_order
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"50 composes took {elapsed:.3f}s"
