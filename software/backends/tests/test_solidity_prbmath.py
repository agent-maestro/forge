"""Tests for the Solidity PRBMath override emitter
(`software.backends.solidity_prbmath`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.parser.ast_nodes import NodeKind
from lang.profiler import Profiler

from software.backends.solidity_backend import SolidityBackend
from software.backends.solidity_prbmath import (
    PRBMathOverride,
    emit_prbmath_override,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


# ── Standalone emitter ──────────────────────────────────────────────


def test_no_builtins_emits_minimal_contract():
    """When the parent uses zero PRBMath-supported builtins, the
    override is a near-empty inheritance shell (compiles, just
    nothing to override)."""
    out = emit_prbmath_override(
        parent_name="Hello", used_builtins=set(),
    )
    assert isinstance(out, PRBMathOverride)
    assert out.contract_name == "HelloWithPRBMath"
    assert out.parent_name == "Hello"
    assert out.overridden == ()
    assert out.unsupported == ()
    assert "contract HelloWithPRBMath is Hello" in out.source
    assert "// No PRBMath-supported builtins" in out.source
    # Parent import is wired to the conventional sibling path.
    assert 'import "./Hello.sol";' in out.source


def test_exp_usage_emits_exp_override():
    out = emit_prbmath_override(
        parent_name="Arrhenius", used_builtins={NodeKind.EXP},
    )
    assert NodeKind.EXP in out.overridden
    assert "function _exp(int256 x) internal pure override" in out.source
    assert "return unwrap(exp(sd(x)));" in out.source
    # Imports include the exp function from PRBMath SD59x18 Math.sol.
    assert (
        'import { exp } from "@prb/math/src/sd59x18/Math.sol";'
        in out.source
    )


def test_pow_override_uses_two_arg_signature():
    out = emit_prbmath_override(
        parent_name="Demo", used_builtins={NodeKind.POW},
    )
    assert "function _pow(int256 base, int256 exp_) internal pure override" in out.source
    assert "return unwrap(pow(sd(base), sd(exp_)));" in out.source


def test_trig_is_routed_via_trig_library():
    """SIN is not in PRBMath SD59x18, so it routes through the
    companion TrigSD59x18 library — not left as a parent revert stub."""
    out = emit_prbmath_override(
        parent_name="Wave", used_builtins={NodeKind.SIN, NodeKind.EXP},
    )
    # Trig goes via the trig library; PRBMath-supported go direct.
    assert NodeKind.SIN in out.via_trig_library
    assert NodeKind.EXP in out.overridden
    assert NodeKind.SIN not in out.unsupported
    # Source imports the trig library and emits an override for _sin.
    assert 'import { TrigSD59x18 } from "./TrigSD59x18.sol";' in out.source
    assert "function _sin(int256 x) internal pure override" in out.source
    assert "TrigSD59x18.sin(sd(x))" in out.source
    # PRBMath route still works for EXP.
    assert "function _exp" in out.source


def test_full_trig_set_routes_through_trig_library():
    trig = {
        NodeKind.SIN, NodeKind.COS, NodeKind.TAN,
        NodeKind.ASIN, NodeKind.ACOS, NodeKind.ATAN,
        NodeKind.SINH, NodeKind.COSH, NodeKind.TANH,
    }
    out = emit_prbmath_override(
        parent_name="X", used_builtins=trig,
    )
    assert set(out.via_trig_library) == trig
    assert out.overridden == ()
    assert out.unsupported == ()
    # Each trig builtin gets a routed override.
    for kind in trig:
        assert f"function _{kind.name.lower()}(int256 x)" in out.source
        assert f"TrigSD59x18.{kind.name.lower()}(sd(x))" in out.source


def test_all_supported_emit_overrides():
    supported = {
        NodeKind.EXP, NodeKind.LN, NodeKind.SQRT,
        NodeKind.ABS, NodeKind.POW,
    }
    out = emit_prbmath_override(
        parent_name="X", used_builtins=supported,
    )
    assert set(out.overridden) == supported
    for kind in supported:
        assert f"function _{kind.name.lower()}" in out.source


# ── Integration: round-trip through the Solidity backend ───────────


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


def test_arrhenius_kernel_picks_up_exp_override(profiler: Profiler):
    """Compile arrhenius.eml, then build the override from the
    backend's recorded `_used_builtins`. The override must include
    the EXP override since the kernel reaches for exp()."""
    backend = SolidityBackend()
    mod = parse_file(EXAMPLES_DIR / "arrhenius.eml")
    profiler.profile_module(mod)
    backend.compile(mod)
    assert NodeKind.EXP in backend._used_builtins
    out = emit_prbmath_override(
        parent_name="Arrhenius",
        used_builtins=set(backend._used_builtins),
    )
    assert NodeKind.EXP in out.overridden
    assert "function _exp" in out.source


def test_hello_kernel_uses_no_builtins(profiler: Profiler):
    """A pure-arithmetic kernel like hello has no transcendentals;
    the override should be empty."""
    backend = SolidityBackend()
    mod = parse_file(EXAMPLES_DIR / "hello.eml")
    profiler.profile_module(mod)
    backend.compile(mod)
    assert backend._used_builtins == set()
    out = emit_prbmath_override(
        parent_name="Hello",
        used_builtins=set(backend._used_builtins),
    )
    assert out.overridden == ()
    assert out.unsupported == ()


# ── Source shape ────────────────────────────────────────────────────


def test_emitted_source_pins_solidity_pragma():
    out = emit_prbmath_override(
        parent_name="X", used_builtins={NodeKind.EXP},
    )
    assert "// SPDX-License-Identifier: MIT" in out.source
    assert "pragma solidity ^0.8.20;" in out.source


def test_parent_path_template_filled_in():
    """The {parent} placeholder in `parent_path` is filled with the
    parent contract name so the override can sit in any directory."""
    out = emit_prbmath_override(
        parent_name="Foo",
        used_builtins=set(),
        parent_path="../src/{parent}.sol",
    )
    assert 'import "../src/Foo.sol";' in out.source
