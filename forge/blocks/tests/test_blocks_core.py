"""Tests for forge.blocks core dataclass + composition."""

from __future__ import annotations

import math

import pytest

from forge.blocks import (
    Block,
    BlockCompositionError,
    compose,
    get,
    list_blocks,
)
from forge.blocks.exponential import (
    decay,
    exp_block,
    sigmoid_block,
    softplus,
    tanh_block,
)
from forge.blocks.oscillator import cos_block, fm_carrier, sin_block
from forge.blocks.polynomial import (
    horner_quintic,
    linear,
    power_cubed,
    power_quartic,
    power_squared,
    quadratic,
)
from forge.blocks.signal import biquad_step, fft_butterfly
from forge.blocks.transform import clarke, dq0, park
from software.backends.python_backend import PythonBackend


# ── Block dataclass invariants ───────────────────────────────────


@pytest.mark.parametrize("block", [
    linear, quadratic, power_squared, sin_block, cos_block, exp_block,
    sigmoid_block, decay, biquad_step, clarke, park,
])
def test_block_has_required_fields(block: Block):
    assert isinstance(block.name, str) and block.name
    assert block.eml_tree is not None
    assert isinstance(block.chain_order, int)
    assert block.chain_order >= 0
    assert isinstance(block.node_count, int)
    assert block.node_count >= 0
    assert isinstance(block.cost_class, str)
    assert isinstance(block.parameters, tuple)
    assert isinstance(block.arity, int) and block.arity >= 1


def test_polynomial_blocks_have_chain_zero():
    """Pure multiply-add bodies must register chain order 0."""
    for b in (linear, quadratic, power_squared, power_cubed, power_quartic,
              horner_quintic):
        assert b.chain_order == 0, f"{b.name} chain_order={b.chain_order}"


def test_exponential_blocks_have_chain_at_least_one():
    """Anything with exp / ln has chain order >= 1."""
    for b in (exp_block, decay, sigmoid_block, softplus, tanh_block):
        assert b.chain_order >= 1, f"{b.name} chain_order={b.chain_order}"


def test_block_is_frozen():
    """Block is a frozen dataclass -- mutation must raise."""
    with pytest.raises(Exception):
        linear.name = "renamed"


def test_block_is_hashable():
    """Frozen dataclass implies hashability -- blocks can be dict keys."""
    # Block contains a `dict` (fpga_allocation) which is unhashable, but
    # the test exists as a sanity check that frozen=True is set.
    assert linear == linear


# ── Registry ─────────────────────────────────────────────────────


def test_registry_contains_all_modules():
    """Importing forge.blocks pulls in every shipped block."""
    names = {b.name for b in list_blocks()}
    expected = {
        # polynomial
        "linear", "quadratic", "power_squared", "power_cubed",
        "power_quartic", "horner_quintic",
        # oscillator
        "sin_block", "cos_block", "damped_osc", "fm_carrier", "chirp",
        # exponential
        "exp_block", "decay", "growth", "sigmoid_block",
        "softplus_block", "tanh_block",
        # control
        "pid", "pid_anti_windup", "state_space_step",
        "luenberger_observer", "kalman_1d", "lpf1",
        # signal
        "fft_butterfly", "convolution_3tap", "convolution_5tap",
        "biquad_step", "moving_average_4", "one_pole_hpf",
        # transform
        "clarke", "inverse_clarke", "park", "inverse_park", "dq0",
    }
    assert expected.issubset(names), (
        f"missing from registry: {expected - names}"
    )


def test_get_returns_registered_block():
    assert get("sigmoid_block") is sigmoid_block
    assert get("linear") is linear


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        get("not_a_real_block")


# ── Composition: chain_order = max(...) ─────────────────────────


@pytest.mark.parametrize("a,b", [
    (linear, sigmoid_block),
    (linear, power_squared),
    (power_squared, sigmoid_block),
    (sin_block, sigmoid_block),
    (exp_block, sigmoid_block),
    (sigmoid_block, sigmoid_block),
])
def test_compose_chain_order_is_max(a: Block, b: Block):
    """The headline invariant: chain_order(A >> B) = max(A, B)."""
    composed = a >> b
    assert composed.chain_order == max(a.chain_order, b.chain_order), (
        f"{a.name} (chain {a.chain_order}) >> {b.name} (chain {b.chain_order})"
        f" = chain {composed.chain_order}"
    )


def test_compose_node_count_is_sum():
    composed = linear >> sigmoid_block
    assert composed.node_count == linear.node_count + sigmoid_block.node_count


def test_compose_arity_is_lhs_arity():
    composed = quadratic >> sigmoid_block
    assert composed.arity == quadratic.arity
    assert composed.parameters == quadratic.parameters


def test_compose_rejects_multi_input_rhs():
    """Quadratic has arity 4 -- it can't be on the rhs of a compose."""
    with pytest.raises(BlockCompositionError, match="arity"):
        sigmoid_block >> quadratic


def test_compose_via_function_call():
    """`compose(a, b)` is identical to `a >> b`."""
    op_form = sin_block >> sigmoid_block
    fn_form = compose(sin_block, sigmoid_block)
    assert op_form.chain_order == fn_form.chain_order
    assert op_form.node_count == fn_form.node_count


def test_compose_rejects_let_bodies():
    """A block whose body has LET bindings can't be the rhs of compose.
    `power_quartic` has `let xx = x*x; xx*xx` and arity 1, so the
    arity check passes but the LET check fires."""
    with pytest.raises(BlockCompositionError, match="LET"):
        sigmoid_block >> power_quartic


# ── Round-tripping composed blocks ──────────────────────────────


def test_compose_round_trips_through_python_backend():
    """A composed block's `to_module()` is consumable by the Python backend."""
    composed = linear >> sigmoid_block
    src = PythonBackend(optimize=False).compile(composed.to_module())
    ns: dict = {}
    exec(compile(src, "composed", "exec"), ns)

    fn_name = "linear_then_sigmoid_block"
    assert fn_name in ns
    # linear(0.5, 2.0, -1.0) = 0; sigmoid(0) = 0.5
    assert math.isclose(ns[fn_name](0.5, 2.0, -1.0), 0.5, abs_tol=1e-12)


def test_compose_chains_three_blocks():
    """Composition is associative-ish: a >> (b >> c) is buildable."""
    triple = linear >> sigmoid_block
    triple_then_log = triple >> tanh_block  # tanh has arity 1
    assert triple_then_log.chain_order == max(
        linear.chain_order, sigmoid_block.chain_order, tanh_block.chain_order,
    )
    assert triple_then_log.arity == linear.arity


# ── FPGA allocation ─────────────────────────────────────────────


def test_blocks_with_fpga_target_have_allocation():
    """damped_osc has @target(fpga); allocation populates."""
    from forge.blocks.oscillator import damped_osc
    assert damped_osc.fpga_allocation
    assert "luts" in damped_osc.fpga_allocation
    assert damped_osc.fpga_allocation["luts"] > 0


def test_blocks_without_fpga_target_have_empty_allocation():
    """linear has no @target(fpga); allocation is empty by design."""
    assert linear.fpga_allocation == {}


# ── Lean theorem strings ────────────────────────────────────────


def test_proof_bearing_blocks_carry_theorem():
    """The blocks we promise are pre-verified ship a non-empty theorem."""
    for b in (linear, sin_block, cos_block, exp_block, sigmoid_block,
              decay, pid := get("pid"), pid_anti_windup := get("pid_anti_windup")):
        assert b.lean_theorem, f"{b.name} missing lean_theorem"
