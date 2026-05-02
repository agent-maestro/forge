"""Tests for the Solidity Foundry test scaffolder
(`software.backends.solidity_foundry`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.profiler import Profiler

from software.backends.solidity_backend import SolidityBackend
from software.backends.solidity_foundry import (
    FoundryScaffold,
    emit_foundry_scaffold,
)
from software.backends.solidity_spec import build_spec


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


def _scaffold(filename: str, profiler: Profiler) -> FoundryScaffold:
    backend = SolidityBackend()
    mod = parse_file(EXAMPLES_DIR / filename)
    profiler.profile_module(mod)
    backend.compile(mod)
    spec = build_spec(mod, backend=backend)
    return emit_foundry_scaffold(
        spec=spec,
        override_contract=f"{spec['contract']}WithPRBMath",
    )


# ── Envelope ─────────────────────────────────────────────────────────


def test_test_contract_name_matches_module(profiler: Profiler):
    s = _scaffold("hello.eml", profiler)
    assert s.test_contract_name == "HelloTest"
    assert "contract HelloTest is Test" in s.test_source


def test_imports_forge_std_and_override_contract(profiler: Profiler):
    s = _scaffold("hello.eml", profiler)
    assert 'import { Test } from "forge-std/Test.sol";' in s.test_source
    assert "HelloWithPRBMath" in s.test_source


def test_setUp_deploys_kernel(profiler: Profiler):
    s = _scaffold("hello.eml", profiler)
    assert "function setUp() public {" in s.test_source
    assert "kernel = new" in s.test_source


# ── Per-function rendering ──────────────────────────────────────────


def test_internal_helper_gets_gas_snapshot_test(profiler: Profiler):
    """`hello.answer` is internal -> a gas-snapshot test is generated
    that calls the harness pass-through wrapper."""
    s = _scaffold("hello.eml", profiler)
    assert "function test_gas_answer() public view {" in s.test_source
    assert "kernel.harness_answer(" in s.test_source
    assert "gasleft()" in s.test_source


def test_harness_subcontract_emitted_when_internals_exist(
    profiler: Profiler,
):
    s = _scaffold("hello.eml", profiler)
    assert "contract HelloHarness is HelloWithPRBMath {" in s.test_source
    assert "function harness_answer(" in s.test_source


def test_verified_function_gets_fuzz_test(profiler: Profiler):
    """motor_control's `safe_pid` is @verify-annotated -> a fuzz test
    is generated with vm.assume()s for each precondition."""
    s = _scaffold("motor_control.eml", profiler)
    assert "function testFuzz_safePid(" in s.test_source
    # The fuzz test should call the function on the kernel.
    assert "kernel.safePid(" in s.test_source


def test_verified_function_test_mentions_theorem(profiler: Profiler):
    s = _scaffold("motor_control.eml", profiler)
    # The motor_control theorem is named pid_bounded.
    assert "pid_bounded" in s.test_source


def test_vpd_kernel_lifts_preconditions_into_vm_assume(
    profiler: Profiler,
):
    eml_path = (
        REPO_ROOT / "industries" / "agriculture" / "greenhouse"
        / "vpd_control.eml"
    )
    if not eml_path.is_file():
        pytest.skip("vpd_control kernel not present (Forge-private path)")
    backend = SolidityBackend()
    mod = parse_file(eml_path)
    profiler.profile_module(mod)
    backend.compile(mod)
    spec = build_spec(mod, backend=backend)
    s = emit_foundry_scaffold(
        spec=spec, override_contract="VpdControlWithPRBMath",
    )
    # vpd_safe is verified -> fuzz test -> vm.assume the requires
    # clauses (humidity > 0, humidity < 100) become vm.assume() calls.
    assert "function testFuzz_vpdSafe(" in s.test_source
    assert "vm.assume((humidityPct > 0))" in s.test_source
    assert "vm.assume((humidityPct < 100))" in s.test_source


# ── foundry.toml ────────────────────────────────────────────────────


def test_foundry_toml_pins_solc_and_fuzz_runs(profiler: Profiler):
    s = _scaffold("hello.eml", profiler)
    assert 'solc       = "0.8.20"' in s.foundry_toml
    assert "[fuzz]" in s.foundry_toml
    assert "runs       = 256" in s.foundry_toml


def test_foundry_toml_mentions_install_step(profiler: Profiler):
    s = _scaffold("hello.eml", profiler)
    assert "forge install" in s.foundry_toml
    assert "forge-std" in s.foundry_toml
    assert "prb-math" in s.foundry_toml


# ── Verified-without-postconditions edge case ──────────────────────


def test_verified_fn_without_postconditions_still_compiles(
    profiler: Profiler,
):
    """If a verified function declares no `ensures`, the fuzz test
    body should still call the function and rely on no-revert as
    the implicit assertion (rather than emit zero asserts)."""
    s = _scaffold("motor_control.eml", profiler)
    # Search for any fuzz function and confirm the body has either
    # an assertTrue or a "no spec postconditions" comment.
    assert (
        "// no spec postconditions; absence of revert is the test."
        in s.test_source
        or "assertTrue(" in s.test_source
    )
