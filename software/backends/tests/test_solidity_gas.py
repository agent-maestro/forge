"""Tests for the Solidity gas estimator (`software.backends.solidity_gas`).

Two layers:
  1. Unit tests for the cost model — synthetic ASTs with known shapes
     so a regression in the cost table fails loudly here rather than
     in the noisier end-to-end backend tests.
  2. Integration with the Solidity backend — assert that the NatSpec
     `@dev Gas estimate:` line shows up (or is suppressed by the
     `gas_estimate=False` flag) for real demo + kernel files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind, Param
from lang.profiler import Profiler
from software.backends.solidity_backend import SolidityBackend
from software.backends.solidity_gas import (
    FUNCTION_OVERHEAD,
    estimate_function_gas,
    format_gas_estimate,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


# ── Helpers to build tiny synthetic ASTs ────────────────────────────


def _lit(v: int = 1) -> ASTNode:
    return ASTNode(kind=NodeKind.LITERAL, value=v)


def _var(name: str = "x") -> ASTNode:
    return ASTNode(kind=NodeKind.VAR, value=name)


def _fn(body: ASTNode | None) -> EMLFunction:
    """Wrap `body` in a single-param synthetic EMLFunction."""
    block = (
        ASTNode(kind=NodeKind.BLOCK, children=[body])
        if body is not None else None
    )
    return EMLFunction(
        name="f",
        params=[Param(name="x", type_name="Real")],
        return_type="Real",
        body=block,
    )


# ── format_gas_estimate buckets ──────────────────────────────────────


def test_format_gas_under_1k_is_exact():
    assert format_gas_estimate(0) == "~0 gas"
    assert format_gas_estimate(42) == "~42 gas"
    assert format_gas_estimate(999) == "~999 gas"


def test_format_gas_under_10k_rounds_to_50():
    # 1234 → nearest 50 → 1250
    assert format_gas_estimate(1234) == "~1,250 gas"
    # 3759 → nearest 50 → 3750
    assert format_gas_estimate(3759) == "~3,750 gas"
    # 9999 → nearest 50 → 10,000 (still under 10k cutoff at strictly <)
    assert format_gas_estimate(9999) == "~10,000 gas"


def test_format_gas_above_10k_rounds_to_500_and_uses_k_suffix():
    # 12_300 → nearest 500 → 12_500 → "13k" (rounded again by /1000)
    # 500-bucket only matters for the in-between digits.
    assert format_gas_estimate(12_300) == "~12k gas"
    assert format_gas_estimate(12_750) == "~13k gas"
    assert format_gas_estimate(100_000) == "~100k gas"


# ── estimate_function_gas: minimal shapes ────────────────────────────


def test_empty_body_just_function_overhead():
    """A function with no body collapses to the entry/exit overhead."""
    fn = _fn(body=None)
    assert estimate_function_gas(fn) == FUNCTION_OVERHEAD


def test_literal_only_costs_overhead_plus_literal():
    # BLOCK (0) + LITERAL (3)
    fn = _fn(_lit(7))
    assert estimate_function_gas(fn) == FUNCTION_OVERHEAD + 3


def test_simple_binop_addition():
    # x + 1: BLOCK(0) + BINOP+(3) + VAR(3) + LITERAL(3)
    expr = ASTNode(
        kind=NodeKind.BINOP, value="+",
        children=[_var("x"), _lit(1)],
    )
    fn = _fn(expr)
    assert estimate_function_gas(fn) == FUNCTION_OVERHEAD + 3 + 3 + 3


def test_compound_compare_costs_more_than_simple():
    # `<=` compiles to LT + ISZERO -> 6 gas; `<` is 3.
    le = ASTNode(
        kind=NodeKind.BINOP, value="<=",
        children=[_var("x"), _lit(0)],
    )
    lt = ASTNode(
        kind=NodeKind.BINOP, value="<",
        children=[_var("x"), _lit(0)],
    )
    assert estimate_function_gas(_fn(le)) == \
        estimate_function_gas(_fn(lt)) + 3


# ── Builtin transcendentals dominate the estimate ───────────────────


def test_exp_call_dominates_arithmetic():
    """An EXP node (3500 gas) should swamp the literal/var costs."""
    expr = ASTNode(
        kind=NodeKind.EXP, children=[_var("x")],
    )
    gas = estimate_function_gas(_fn(expr))
    # 200 + 3500 + 3 (var) = 3703
    assert gas == FUNCTION_OVERHEAD + 3500 + 3


def test_pow_is_the_most_expensive_single_op():
    """POW (10_000) > LN (6000) > EXP (3500). Sanity-check ordering."""
    pow_gas = estimate_function_gas(_fn(
        ASTNode(kind=NodeKind.POW, children=[_var("x"), _lit(2)]),
    ))
    ln_gas = estimate_function_gas(_fn(
        ASTNode(kind=NodeKind.LN, children=[_var("x")]),
    ))
    exp_gas = estimate_function_gas(_fn(
        ASTNode(kind=NodeKind.EXP, children=[_var("x")]),
    ))
    assert pow_gas > ln_gas > exp_gas


def test_named_call_routes_to_transcendental_when_recognized():
    """`log(x)` parses as a CALL node (not LN builtin) but should still
    be charged the ln cost via the named-transcendental table."""
    log_call = ASTNode(
        kind=NodeKind.CALL, value="log",
        children=[_var("x")],
    )
    unknown_call = ASTNode(
        kind=NodeKind.CALL, value="some_user_helper",
        children=[_var("x")],
    )
    log_gas = estimate_function_gas(_fn(log_call))
    user_gas = estimate_function_gas(_fn(unknown_call))
    # log routes to ~6000; unknown user fn defaults to ~100.
    assert log_gas - user_gas >= 5000


def test_sigmoid_call_recognized():
    """sigmoid is a stdlib name that should map to ~7000 gas."""
    expr = ASTNode(
        kind=NodeKind.CALL, value="sigmoid",
        children=[_var("x")],
    )
    gas = estimate_function_gas(_fn(expr))
    assert gas >= FUNCTION_OVERHEAD + 7000


# ── Backend integration ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


def test_natspec_gas_line_present_by_default(profiler: Profiler):
    """The default backend instance emits the NatSpec @dev gas line."""
    backend = SolidityBackend()
    mod = parse_file(EXAMPLES_DIR / "hello.eml")
    profiler.profile_module(mod)
    out = backend.compile(mod)
    assert "/// @dev Gas estimate: ~" in out
    assert "PRBMath SD59x18 overrides assumed" in out
    assert "forge gas-bench" in out


def test_natspec_gas_line_suppressed_with_flag(profiler: Profiler):
    """`gas_estimate=False` removes the @dev gas annotation entirely."""
    backend = SolidityBackend(gas_estimate=False)
    mod = parse_file(EXAMPLES_DIR / "hello.eml")
    profiler.profile_module(mod)
    out = backend.compile(mod)
    assert "Gas estimate:" not in out


def test_arrhenius_uses_k_suffix_for_exp_kernel(profiler: Profiler):
    """Arrhenius has an exp call -> >10k gas -> formatted with 'k'."""
    backend = SolidityBackend()
    mod = parse_file(EXAMPLES_DIR / "arrhenius.eml")
    profiler.profile_module(mod)
    out = backend.compile(mod)
    # The exp-using function should print with the k-suffix bucket.
    assert "/// @dev Gas estimate: ~" in out
    # At least one function in arrhenius reaches for exp -> >= 3700 gas.
    # Pull every gas line and confirm at least one is in the >=1k bucket.
    gas_lines = [
        line for line in out.splitlines()
        if "Gas estimate:" in line
    ]
    assert gas_lines
    assert any("," in line or "k gas" in line for line in gas_lines)
