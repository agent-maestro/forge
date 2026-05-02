"""Tests for the Solidity TrigSD59x18 library emitter
(`software.backends.solidity_trig`)."""

from __future__ import annotations

import pytest

from lang.parser.ast_nodes import NodeKind
from software.backends.solidity_trig import (
    TRIG_BUILTINS,
    TrigLibrary,
    emit_trig_library,
    overrides_supported_by_trig,
    trig_function_name,
)


# ── Coverage map ────────────────────────────────────────────────────


def test_every_trig_builtin_has_a_library_function():
    """The 9 trig NodeKinds (sin/cos/tan/asin/acos/atan + 3 hyperbolics)
    must each map to a TrigSD59x18 library function name."""
    expected = {
        NodeKind.SIN, NodeKind.COS, NodeKind.TAN,
        NodeKind.ASIN, NodeKind.ACOS, NodeKind.ATAN,
        NodeKind.SINH, NodeKind.COSH, NodeKind.TANH,
    }
    assert TRIG_BUILTINS == expected
    for kind in expected:
        assert trig_function_name(kind) == kind.name.lower()


def test_overrides_supported_filters_to_trig_only():
    used = {NodeKind.EXP, NodeKind.SIN, NodeKind.LN, NodeKind.TANH}
    supported = overrides_supported_by_trig(used)
    assert supported == {NodeKind.SIN, NodeKind.TANH}


# ── emit_trig_library ───────────────────────────────────────────────


def test_no_trig_returns_none():
    """If the kernel doesn't use any trig, no library is emitted."""
    assert emit_trig_library(set()) is None
    assert emit_trig_library({NodeKind.EXP, NodeKind.LN}) is None


def test_single_trig_emits_library():
    out = emit_trig_library({NodeKind.SIN})
    assert isinstance(out, TrigLibrary)
    assert out.library_name == "TrigSD59x18"
    assert out.overridden == (NodeKind.SIN,)
    # The library is the same source regardless of which trig is used
    # — it's a complete library, not per-function carving.
    assert "library TrigSD59x18" in out.source
    assert "function sin(SD59x18 x)" in out.source


def test_full_trig_overridden_set():
    out = emit_trig_library(set(TRIG_BUILTINS))
    assert set(out.overridden) == TRIG_BUILTINS


# ── Library source structure ────────────────────────────────────────


def test_library_imports_prbmath_exp_for_hyperbolics():
    out = emit_trig_library({NodeKind.SINH})
    assert 'import { exp, sqrt } from "@prb/math/src/sd59x18/Math.sol";' in out.source


def test_library_pins_solidity_pragma_and_spdx():
    out = emit_trig_library({NodeKind.SIN})
    assert "// SPDX-License-Identifier: MIT" in out.source
    assert "pragma solidity ^0.8.20;" in out.source


def test_library_declares_canonical_constants():
    """SD59x18 PI / TWO_PI / HALF_PI must be present so the range
    reduction logic can use them."""
    out = emit_trig_library({NodeKind.SIN})
    assert "PI         = 3_141592653589793238" in out.source
    assert "TWO_PI     = 6_283185307179586477" in out.source
    assert "HALF_PI    = 1_570796326794896619" in out.source


@pytest.mark.parametrize("fn_name", [
    "sin", "cos", "tan", "asin", "acos", "atan",
    "sinh", "cosh", "tanh",
])
def test_library_exposes_each_trig_function(fn_name: str):
    out = emit_trig_library(set(TRIG_BUILTINS))
    sig = f"function {fn_name}(SD59x18 x) internal pure returns (SD59x18)"
    assert sig in out.source, (
        f"expected library to declare `{sig}`"
    )


def test_tan_guards_against_singularity():
    out = emit_trig_library({NodeKind.TAN})
    assert "tan() singularity" in out.source


def test_asin_guards_input_range():
    out = emit_trig_library({NodeKind.ASIN})
    assert "asin |x|>1" in out.source


# ── Library source is deterministic ────────────────────────────────


def test_library_source_is_stable_across_calls():
    """Two calls with the same input must yield byte-identical source
    so the audit-bundle manifest hash stays stable."""
    a = emit_trig_library({NodeKind.SIN}).source
    b = emit_trig_library({NodeKind.SIN}).source
    assert a == b
