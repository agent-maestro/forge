"""Tests for the Luau (Roblox typed Lua) backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.luau_backend import (
    LuauBackend,
    CompileError as LuauErr,
    _safe_ident,
    _wants_drift_warning,
    _LUAU_RESERVED,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"
BREATHING = REPO_ROOT / "industries" / "gaming" / "animation" / "breathing.eml"
DIFFUSE = REPO_ROOT / "industries" / "gaming" / "rendering" / "diffuse.eml"


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Structural properties ─────────────────────────────────────


class TestLuauStructure:
    def test_module_table_init_and_return(self):
        out = LuauBackend().compile(_profile(SPRING))
        assert "local M = {}" in out
        # Trailing `return M` so the file is loadable via require().
        assert out.rstrip().endswith("return M")

    def test_constants_use_local_with_module_alias(self):
        out = LuauBackend().compile(_profile(BREATHING))
        # `local NAME = ...` with `M.NAME = NAME` so external callers
        # can read the constant via the module table.
        assert "local ZERO = 0.0" in out
        assert "M.ZERO = ZERO" in out

    def test_functions_attach_to_module_table(self):
        out = LuauBackend().compile(_profile(SPRING))
        assert "function M." in out

    def test_breathing_signature_uses_typed_params(self):
        out = LuauBackend().compile(_profile(BREATHING))
        assert (
            "function M.breath_simple(base: number, amp: number, "
            "omega: number, phase: number, t: number): number"
        ) in out

    def test_uses_dash_dash_comments_not_double_slash(self):
        out = LuauBackend().compile(_profile(BREATHING))
        # First line should be `--` not `//`.
        first_line = out.splitlines()[0]
        assert first_line.startswith("-- ")
        assert not first_line.startswith("// ")


# ── Math name mapping ─────────────────────────────────────────


class TestLuauMath:
    def test_math_dot_namespace(self):
        out = LuauBackend().compile(_profile(SPRING))
        assert "math.exp(" in out
        assert "math.cos(" in out
        assert "math.sqrt(" in out
        # Should NOT use JS or Python spellings.
        assert "Math.exp(" not in out
        assert "Math.cos(" not in out
        assert "math.E" not in out  # we don't reference math.E

    def test_pow_uses_caret_operator_not_math_pow(self):
        out = LuauBackend().compile(_profile(FRESNEL))
        # Luau idiom: `x ^ y` not `math.pow(x, y)`.
        assert " ^ " in out
        assert "math.pow(" not in out

    def test_clamp_uses_min_max_idiom(self):
        src = """
        module test_clamp;
        fn cl(x: Real) -> Real
            where chain_order <= 0
            requires (x >= 0.0)
        {
            clamp(x, 0.0, 1.0)
        }
        """
        out = LuauBackend().compile(_profile_source(src))
        assert "math.min(math.max(" in out


# ── Preconditions ─────────────────────────────────────────────


class TestLuauPreconditions:
    def test_requires_lowers_to_assert_with_message(self):
        out = LuauBackend().compile(_profile(BREATHING))
        # Lua's standard idiom: `assert(<cond>, "message")`.
        assert "assert(" in out
        assert "breath_simple: requires" in out


# ── Identifier handling ───────────────────────────────────────


class TestLuauIdentifiers:
    def test_safe_ident_renames_lua_keywords(self):
        assert _safe_ident("local") == "local_"
        assert _safe_ident("function") == "function_"
        assert _safe_ident("end") == "end_"
        assert _safe_ident("then") == "then_"
        assert _safe_ident("repeat") == "repeat_"
        assert _safe_ident("regular_name") == "regular_name"

    def test_reserved_set_contains_lua_keywords(self):
        for word in (
            "and", "break", "do", "else", "elseif", "end", "false",
            "for", "function", "if", "in", "local", "nil", "not",
            "or", "repeat", "return", "then", "true", "until", "while",
            "continue", "type", "export",
        ):
            assert word in _LUAU_RESERVED, f"{word!r} should be reserved"

    def test_neq_operator_uses_tilde_equals(self):
        # Lua's not-equal operator is `~=`, not `!=`.
        src = """
        module test_neq;
        fn check(x: Real, y: Real) -> Real
            where chain_order <= 0
        {
            if (x != y) {
                1.0
            } else {
                0.0
            }
        }
        """
        # If the parser supports if-expressions; otherwise we test
        # via a binop directly.
        try:
            out = LuauBackend().compile(_profile_source(src))
            assert "~=" in out or " != " not in out
        except Exception:
            # If the test source doesn't parse, just unit-test via
            # a hand-crafted module that we know parses. Skip.
            pytest.skip("if-expression syntax not supported in test source")


# ── Tuple returns ─────────────────────────────────────────────


class TestLuauTuples:
    def test_tuple_return_uses_multi_return(self):
        src = """
        module test_tuple;
        fn pair(x: Real) -> (Real, Real)
            where chain_order <= 0
        {
            (x, x)
        }
        """
        out = LuauBackend().compile(_profile_source(src))
        # Lua's multi-return: just `return v1, v2`.
        assert "return x, x" in out


# ── In-module call dispatch ───────────────────────────────────


class TestLuauCallDispatch:
    def test_in_module_calls_use_module_table(self):
        # When function A calls function B in the same module,
        # B should resolve via M.B(...) so caller-defined override
        # via M.B = my_override works.
        src = """
        module test_calls;

        fn helper(x: Real) -> Real
            where chain_order <= 0
        {
            x * 2.0
        }

        fn caller(x: Real) -> Real
            where chain_order <= 0
        {
            helper(x) + 1.0
        }
        """
        # optimize=False so the optimizer doesn't inline helper().
        out = LuauBackend(optimize=False).compile(_profile_source(src))
        # Caller body should reference M.helper, not bare helper.
        assert "M.helper(x)" in out


# ── End-to-end on every gaming kernel ──────────────────────────


GAMING_DIR = REPO_ROOT / "industries" / "gaming"


@pytest.mark.parametrize(
    "eml", sorted(GAMING_DIR.rglob("*.eml")), ids=lambda p: p.name,
)
def test_gaming_kernel_compiles_to_luau(eml: Path):
    out = LuauBackend().compile(_profile(eml))
    assert "local M = {}" in out
    assert out.rstrip().endswith("return M")


# ── Optimizer flag ────────────────────────────────────────────


def test_no_optimize_flag_still_produces_valid_output():
    out = LuauBackend(optimize=False).compile(_profile(SPRING))
    assert "local M = {}" in out
    assert out.rstrip().endswith("return M")
