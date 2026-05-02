"""Tests for the Metal (MSL) backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.metal_backend import (
    MetalBackend,
    CompileError as MtlErr,
    _safe_ident,
    _metal_type,
    _wants_drift_warning,
    _METAL_RESERVED,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"
BREATHING = REPO_ROOT / "industries" / "gaming" / "animation" / "breathing.eml"
DIFFUSE = REPO_ROOT / "industries" / "gaming" / "rendering" / "diffuse.eml"
FBM_WARPED = REPO_ROOT / "industries" / "gaming" / "procedural" / "fbm_warped.eml"


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Type mapping ──────────────────────────────────────────────


class TestMetalTypeMapping:
    def test_real_lowers_to_float(self):
        assert _metal_type("Real") == "float"

    def test_f64_lowers_to_float_f32_safe_default(self):
        assert _metal_type("f64") == "float"

    def test_f16_lowers_to_half_native(self):
        # Metal has native `half` type -- use it when EML asks for f16.
        assert _metal_type("f16") == "half"

    def test_bool_passes_through(self):
        assert _metal_type("bool") == "bool"

    def test_unknown_falls_back_to_float(self):
        assert _metal_type("not_a_type") == "float"


# ── Structural properties ─────────────────────────────────────


class TestMetalStructure:
    def test_includes_metal_stdlib_and_using_namespace(self):
        out = MetalBackend().compile(_profile(SPRING))
        assert "#include <metal_stdlib>" in out
        assert "using namespace metal;" in out

    def test_no_entry_point_markers_for_function_library(self):
        out = MetalBackend().compile(_profile(SPRING))
        # Strip the leading documentation block (lines that start
        # with `//`) before checking that no actual function carries
        # an entry-point marker -- the docstring legitimately names
        # them while explaining we don't emit them.
        body = "\n".join(
            ln for ln in out.splitlines() if not ln.lstrip().startswith("//")
        )
        assert "[[kernel]]" not in body
        assert "[[vertex]]" not in body
        assert "[[fragment]]" not in body

    def test_constants_use_metal_constant_storage_qualifier(self):
        out = MetalBackend().compile(_profile(BREATHING))
        # `constant float NAME = ...;` is the Metal idiom for
        # file-scope numeric literals.
        assert "constant float ZERO = 0.0f;" in out
        assert "constant float T_MAX = 3600.0f;" in out

    def test_functions_use_inline(self):
        out = MetalBackend().compile(_profile(SPRING))
        # `inline` lets the Metal compiler fold the call --
        # mirrors the C# AggressiveInlining pattern.
        assert "inline " in out

    def test_breathing_signature_is_idiomatic_metal(self):
        out = MetalBackend().compile(_profile(BREATHING))
        sig = (
            "inline float breath_simple(float base, float amp, "
            "float omega, float phase, float t)"
        )
        assert sig in out


# ── Math name mapping ─────────────────────────────────────────


class TestMetalMath:
    def test_math_built_ins_after_using_namespace_no_prefix(self):
        out = MetalBackend().compile(_profile(SPRING))
        # `using namespace metal;` brings in the math names; emit
        # bare calls (`exp(...)`, not `metal::exp(...)`).
        assert "exp(" in out
        assert "cos(" in out
        assert "sqrt(" in out
        # Should NOT carry a CPU/host namespace prefix.
        assert "std::exp(" not in out
        assert "Math.Exp(" not in out
        assert "math.exp(" not in out

    def test_pow_is_built_in(self):
        out = MetalBackend().compile(_profile(FRESNEL))
        assert "pow(" in out

    def test_float_literals_have_f_suffix(self):
        out = MetalBackend().compile(_profile(BREATHING))
        # Metal's compiler infers float by default but the explicit
        # `f` suffix avoids any double-promotion warnings on host.
        assert "0.0f" in out


# ── Drift warning ─────────────────────────────────────────────


class TestMetalDriftWarning:
    def test_chain_2_emits_warning(self):
        out = MetalBackend().compile(_profile(BREATHING))
        assert "WARNING: float32 precision drift risk" in out
        assert "chain_order=2" in out

    def test_chain_6_emits_warning(self):
        out = MetalBackend().compile(_profile(FBM_WARPED))
        assert "WARNING: float32 precision drift risk" in out
        assert "chain_order=6" in out

    def test_wants_drift_warning_floor_is_two(self):
        emit, _ = _wants_drift_warning({
            "status": "ok", "chain_order": 1, "fp16_drift_risk": "LOW",
        })
        assert emit is False
        emit, why = _wants_drift_warning({
            "status": "ok", "chain_order": 2, "fp16_drift_risk": "LOW",
        })
        assert emit is True
        assert "chain_order=2" in why


# ── Identifier handling ───────────────────────────────────────


class TestMetalIdentifiers:
    def test_safe_ident_renames_metal_reserved(self):
        assert _safe_ident("kernel") == "kernel_"
        assert _safe_ident("device") == "device_"
        assert _safe_ident("constant") == "constant_"
        assert _safe_ident("thread") == "thread_"
        assert _safe_ident("texture2d") == "texture2d_"
        assert _safe_ident("regular_name") == "regular_name"

    def test_reserved_set_contains_metal_keywords(self):
        for word in (
            "kernel", "vertex", "fragment", "device", "constant",
            "thread", "threadgroup", "texture2d", "sampler",
            "float2", "float3", "float4", "half", "saturate",
        ):
            assert word in _METAL_RESERVED, f"{word!r} should be reserved"


# ── Tuple returns ─────────────────────────────────────────────


class TestMetalTuples:
    def test_tuple_return_emits_struct(self):
        src = """
        module test_tuple;
        fn pair(x: Real) -> (Real, Real)
            where chain_order <= 0
        {
            (x, x)
        }
        """
        out = MetalBackend().compile(_profile_source(src))
        assert "struct PairResult" in out
        assert "float e0;" in out
        assert "float e1;" in out
        # Aggregate-init form on return.
        assert "PairResult _r = { x, x };" in out
        assert "return _r;" in out


# ── End-to-end on every gaming kernel ──────────────────────────


GAMING_DIR = REPO_ROOT / "industries" / "gaming"


@pytest.mark.parametrize(
    "eml", sorted(GAMING_DIR.rglob("*.eml")), ids=lambda p: p.name,
)
def test_gaming_kernel_compiles_to_metal(eml: Path):
    """Every gaming .eml compiles to a non-empty Metal file."""
    out = MetalBackend().compile(_profile(eml))
    assert "#include <metal_stdlib>" in out
    assert "using namespace metal;" in out
    assert "inline " in out


# ── Optimizer flag ────────────────────────────────────────────


def test_no_optimize_flag_still_produces_valid_output():
    out = MetalBackend(optimize=False).compile(_profile(SPRING))
    assert "#include <metal_stdlib>" in out
    assert "inline " in out


# ── Forward declarations ──────────────────────────────────────


class TestMetalForwardDeclarations:
    def test_forward_decls_section_emitted(self):
        out = MetalBackend().compile(_profile(SPRING))
        assert "// Forward declarations" in out

    def test_externs_resolve_via_forward_decls(self):
        # Regression for Issue #2: aes.eml declares gf256_square as
        # `extern fn` AT THE BOTTOM of the file but calls it from
        # the body of gf256_inverse near the top. Without forward
        # decls the Metal C++ compiler fails with "use of undeclared
        # identifier 'gf256_square'".
        aes = REPO_ROOT / "industries" / "crypto" / "symmetric" / "aes.eml"
        out = MetalBackend().compile(_profile(aes))
        # The forward decl should appear before the first body that
        # references gf256_square.
        decl_idx = out.index("inline float gf256_square(float b);")
        first_use_idx = out.index("gf256_square(input)")
        assert decl_idx < first_use_idx, (
            "forward declaration must precede first use"
        )
