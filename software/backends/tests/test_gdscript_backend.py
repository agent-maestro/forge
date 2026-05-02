"""Tests for the GDScript (Godot 4.x) backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.gdscript_backend import (
    GDScriptBackend,
    CompileError as GdErr,
    _safe_ident,
    _GD_RESERVED,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"
BREATHING = REPO_ROOT / "industries" / "gaming" / "animation" / "breathing.eml"
FBM_WARPED = REPO_ROOT / "industries" / "gaming" / "procedural" / "fbm_warped.eml"
DIFFUSE = REPO_ROOT / "industries" / "gaming" / "rendering" / "diffuse.eml"


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Structural properties ──────────────────────────────────────


class TestGDScriptStructure:
    def test_extends_node_and_class_name(self):
        out = GDScriptBackend().compile(_profile(SPRING))
        assert "extends Node" in out
        assert "class_name Spring" in out

    def test_class_name_pascal_case_from_snake(self):
        out = GDScriptBackend().compile(_profile(FBM_WARPED))
        assert "class_name FbmWarped" in out

    def test_constants_use_const_with_float_type(self):
        out = GDScriptBackend().compile(_profile(BREATHING))
        assert "const ZERO: float = 0.0" in out
        assert "const T_MAX: float = 3600.0" in out

    def test_functions_are_static_func(self):
        out = GDScriptBackend().compile(_profile(SPRING))
        assert "static func " in out
        # Plain `func ` without `static` would be an instance method,
        # which isn't what an Autoload caller wants.
        for line in out.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("func "):
                pytest.fail(f"non-static func found: {line!r}")

    def test_functions_have_typed_params_and_return(self):
        out = GDScriptBackend().compile(_profile(BREATHING))
        # breath_simple takes 5 floats, returns float.
        assert (
            "static func breath_simple(base: float, amp: float, "
            "omega: float, phase: float, t: float) -> float:"
        ) in out


# ── Math name mapping ──────────────────────────────────────────


class TestGDScriptMath:
    def test_math_functions_are_global_no_module_prefix(self):
        out = GDScriptBackend().compile(_profile(SPRING))
        # GDScript: bare `exp(`, `cos(`, `sqrt(` -- not `math.exp(`.
        assert "exp(" in out
        assert "cos(" in out
        assert "sqrt(" in out
        assert "math.exp(" not in out
        assert "Math.Exp(" not in out
        assert "math.sin(" not in out

    def test_pow_is_global(self):
        out = GDScriptBackend().compile(_profile(FRESNEL))
        # Fresnel uses pow((1 - cos_theta), 5)
        assert "pow(" in out
        assert "math.pow(" not in out
        assert "Math.Pow(" not in out

    def test_burley_diffuse_no_prefix_pow(self):
        out = GDScriptBackend().compile(_profile(DIFFUSE))
        assert "pow(" in out
        assert "math.pow(" not in out


# ── Boolean + identifier handling ──────────────────────────────


class TestGDScriptIdentifiers:
    def test_lowercase_boolean_literals(self):
        src = """
        module test_bool;
        fn always_true() -> Real
            where chain_order <= 0
        {
            let x = true;
            1.0
        }
        """
        out = GDScriptBackend().compile(_profile_source(src))
        # GDScript uses `true`/`false` not Python's `True`/`False`.
        assert "True" not in out.replace("true", "")
        # quick sanity: literal `true` appears.
        assert "var x = true" in out

    def test_safe_ident_renames_gd_reserved(self):
        # Direct unit on the helper.
        assert _safe_ident("class") == "class_"
        assert _safe_ident("var") == "var_"
        assert _safe_ident("static") == "static_"
        assert _safe_ident("PI") == "PI_"  # GDScript built-in constant
        assert _safe_ident("regular_name") == "regular_name"

    def test_reserved_set_contains_gd_keywords(self):
        for word in ("func", "extends", "class_name", "var", "const",
                     "static", "true", "false", "PI", "TAU"):
            assert word in _GD_RESERVED, f"{word!r} should be reserved"


# ── Tuple returns ──────────────────────────────────────────────


class TestGDScriptTuples:
    def test_tuple_return_emits_array(self):
        # Find or construct a kernel that returns a tuple. We
        # construct one inline so the test isn't fragile to
        # gaming-vertical content.
        src = """
        module test_tuple;
        fn pair(x: Real) -> (Real, Real)
            where chain_order <= 0
        {
            (x, x)
        }
        """
        out = GDScriptBackend().compile(_profile_source(src))
        assert "-> Array:" in out
        # Tuple body emits as `[x, x]`.
        assert "return [x, x]" in out


# ── End-to-end: every gaming kernel must compile ───────────────


GAMING_DIR = REPO_ROOT / "industries" / "gaming"


@pytest.mark.parametrize("eml", sorted(GAMING_DIR.rglob("*.eml")), ids=lambda p: p.name)
def test_gaming_kernel_compiles_to_gdscript(eml: Path):
    """Every gaming .eml compiles to a non-empty GDScript file."""
    out = GDScriptBackend().compile(_profile(eml))
    assert "extends Node" in out
    assert "class_name " in out
    # Sanity: at least one static func per file.
    assert "static func " in out


# ── Optimizer flag ─────────────────────────────────────────────


def test_no_optimize_flag_still_produces_valid_output():
    """optimize=False bypasses the optimizer pipeline cleanly."""
    out = GDScriptBackend(optimize=False).compile(_profile(SPRING))
    assert "extends Node" in out
    assert "static func " in out


# ── Profile comments ───────────────────────────────────────────


def test_each_function_has_profile_comment():
    out = GDScriptBackend().compile(_profile(BREATHING))
    # The profile comment carries chain_order on the line above
    # the static func. Both kernels should have one.
    assert out.count("# Chain order:") >= 2
