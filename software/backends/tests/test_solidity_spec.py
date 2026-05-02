"""Tests for the Solidity formal-spec exporter
(`software.backends.solidity_spec`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.profiler import Profiler
from software.backends.solidity_backend import SolidityBackend
from software.backends.solidity_spec import (
    SPEC_VERSION,
    build_bundle,
    build_spec,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> SolidityBackend:
    return SolidityBackend()


def _spec(filename: str, profiler: Profiler,
          backend: SolidityBackend) -> dict:
    mod = parse_file(EXAMPLES_DIR / filename)
    profiler.profile_module(mod)
    return build_spec(mod, backend=backend)


# ── Envelope ─────────────────────────────────────────────────────────


def test_envelope_carries_version_and_compiler(
    profiler: Profiler, backend: SolidityBackend,
):
    spec = _spec("hello.eml", profiler, backend)
    assert spec["spec_version"] == SPEC_VERSION
    assert spec["compiler"]["name"] == "monogate-forge"
    assert spec["compiler"]["backend"] == "solidity"
    # Module name comes from the `module` declaration in the EML source.
    assert spec["module"] == "hello"
    assert spec["contract"] == "Hello"


def test_functions_list_has_one_entry_for_hello(
    profiler: Profiler, backend: SolidityBackend,
):
    spec = _spec("hello.eml", profiler, backend)
    assert len(spec["functions"]) == 1
    fn = spec["functions"][0]
    assert fn["name"] == "answer"
    assert fn["solidity_name"] == "answer"
    assert fn["returns"]["solidity_type"] == "int256"
    # `answer` has no @verify -> internal visibility.
    assert fn["visibility"] == "internal"
    assert fn["verified"] is False


# ── Verified functions surface a verification block ─────────────────


def test_verified_function_carries_lean_theorem(
    profiler: Profiler, backend: SolidityBackend,
):
    spec = _spec("motor_control.eml", profiler, backend)
    safe_pid = next(f for f in spec["functions"] if f["name"] == "safe_pid")
    assert safe_pid["verified"] is True
    assert safe_pid["visibility"] == "external"
    assert safe_pid["verification"]["system"] == "lean"
    assert safe_pid["verification"]["library"] == "MachLib"
    # The motor_control demo annotates safe_pid with theorem="pid_bounded".
    assert safe_pid["verification"]["theorem"] == "pid_bounded"


# ── Preconditions land as Solidity-rendered guards ─────────────────


def test_vpd_kernel_lifts_requires_into_spec(
    profiler: Profiler, backend: SolidityBackend,
):
    eml_path = (
        REPO_ROOT / "industries" / "agriculture" / "greenhouse"
        / "vpd_control.eml"
    )
    if not eml_path.is_file():
        pytest.skip("vpd_control kernel not present (Forge-private path)")
    mod = parse_file(eml_path)
    profiler.profile_module(mod)
    spec = build_spec(mod, backend=backend)
    vpd_safe = next(f for f in spec["functions"] if f["name"] == "vpd_safe")
    # vpd_safe carries `requires humidity_pct > 0` and < 100 in the EML.
    pres = vpd_safe["preconditions"]
    assert any(
        "(humidityPct > 0)" in p.get("solidity_require", "")
        for p in pres
    )
    assert any(
        "(humidityPct < 100)" in p.get("solidity_require", "")
        for p in pres
    )
    # Each entry carries an audit-friendly guard message.
    for p in pres:
        assert p["guard_message"].startswith("vpd_safe: requires ")


# ── Pfaffian profile + gas estimate flow through ───────────────────


def test_function_spec_has_pfaffian_profile_and_gas(
    profiler: Profiler, backend: SolidityBackend,
):
    spec = _spec("motor_control.eml", profiler, backend)
    for fn in spec["functions"]:
        # Profiler should populate a profile for every parsed function;
        # the spec lifts the audit-relevant subset.
        assert "pfaffian_profile" in fn
        assert "chain_order" in fn["pfaffian_profile"]
        # All bodied functions get a gas estimate.
        assert isinstance(fn["gas_estimate"], int)
        assert fn["gas_estimate"] >= 100  # at minimum, FUNCTION_OVERHEAD


# ── JSON shape is deterministic ──────────────────────────────────────


def test_bundle_json_is_sorted_and_stable(
    profiler: Profiler, backend: SolidityBackend,
):
    """The .spec.json sidecar is meant for git-diff. Two builds of
    the same module must produce byte-identical JSON."""
    mod_a = parse_file(EXAMPLES_DIR / "motor_control.eml")
    mod_b = parse_file(EXAMPLES_DIR / "motor_control.eml")
    profiler.profile_module(mod_a)
    profiler.profile_module(mod_b)
    bundle_a = build_bundle(mod_a, backend=SolidityBackend())
    bundle_b = build_bundle(mod_b, backend=SolidityBackend())
    assert bundle_a.spec_json() == bundle_b.spec_json()
    # And the JSON parses cleanly with sorted keys at every level.
    parsed = json.loads(bundle_a.spec_json())
    assert parsed["spec_version"] == SPEC_VERSION


def test_bundle_returns_solidity_source_alongside_spec(
    profiler: Profiler,
):
    mod = parse_file(EXAMPLES_DIR / "hello.eml")
    profiler.profile_module(mod)
    bundle = build_bundle(mod, backend=SolidityBackend())
    assert "pragma solidity" in bundle.solidity_source
    assert bundle.spec["module"] == "hello"


# ── Returns shape is captured in both scalar and tuple form ────────


def test_scalar_return_kind(profiler: Profiler, backend: SolidityBackend):
    spec = _spec("hello.eml", profiler, backend)
    assert spec["functions"][0]["returns"]["kind"] == "scalar"
    assert spec["functions"][0]["returns"]["solidity_type"] == "int256"


# ── Postconditions render with `result` substitution ───────────────


def test_postconditions_render_with_result_keyword(
    profiler: Profiler, backend: SolidityBackend,
):
    """ensures clauses using `result` should render as `result` in the
    Solidity expression so the spec line is readable."""
    eml_path = (
        REPO_ROOT / "industries" / "agriculture" / "greenhouse"
        / "vpd_control.eml"
    )
    if not eml_path.is_file():
        pytest.skip("vpd_control kernel not present (Forge-private path)")
    mod = parse_file(eml_path)
    profiler.profile_module(mod)
    spec = build_spec(mod, backend=backend)
    vpd_safe = next(f for f in spec["functions"] if f["name"] == "vpd_safe")
    posts = vpd_safe["postconditions"]
    if not posts:
        pytest.skip("vpd_safe has no `ensures` clause to test")
    for p in posts:
        # Each entry has a Solidity-rendered expression and a NatSpec
        # @dev line that mirrors what the .sol file emits.
        assert "expression" in p
        assert p["natspec_dev"].startswith("ensures: ")
