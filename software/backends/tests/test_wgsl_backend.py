"""Tests for the WGSL (WebGPU) backend."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.wgsl_backend import (
    WGSLBackend,
    CompileError as WgslErr,
    _safe_ident,
    _wgsl_type,
    _wants_drift_warning,
    _WGSL_RESERVED,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"
BREATHING = REPO_ROOT / "industries" / "gaming" / "animation" / "breathing.eml"
DIFFUSE = REPO_ROOT / "industries" / "gaming" / "rendering" / "diffuse.eml"
FBM_WARPED = REPO_ROOT / "industries" / "gaming" / "procedural" / "fbm_warped.eml"

NAGA = shutil.which("naga")


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Type mapping ──────────────────────────────────────────────


class TestWGSLTypeMapping:
    def test_real_lowers_to_f32(self):
        assert _wgsl_type("Real") == "f32"

    def test_f64_lowers_to_f32(self):
        assert _wgsl_type("f64") == "f32"

    def test_f16_lowers_to_f32_safe_default(self):
        # f16 is an extension; default to f32 for portability.
        assert _wgsl_type("f16") == "f32"

    def test_integer_widths_normalize(self):
        for t in ("u8", "u16", "u32", "u64"):
            assert _wgsl_type(t) == "u32"
        for t in ("i8", "i16", "i32", "i64"):
            assert _wgsl_type(t) == "i32"

    def test_bool_passes_through(self):
        assert _wgsl_type("bool") == "bool"

    def test_unknown_falls_back_to_f32(self):
        assert _wgsl_type("not_a_type") == "f32"


# ── Structural properties ─────────────────────────────────────


class TestWGSLStructure:
    def test_no_include_guard_or_preprocessor(self):
        out = WGSLBackend().compile(_profile(SPRING))
        # WGSL has no preprocessor.
        assert "#ifndef" not in out
        assert "#define" not in out
        assert "#include" not in out

    def test_no_entry_point_emitted_for_function_library(self):
        out = WGSLBackend().compile(_profile(SPRING))
        # We're a function library; no @compute / @vertex / @fragment.
        assert "@compute" not in out
        assert "@vertex" not in out
        assert "@fragment" not in out

    def test_constants_use_const_with_f32_type(self):
        out = WGSLBackend().compile(_profile(BREATHING))
        assert "const ZERO: f32 = 0.0;" in out
        assert "const T_MAX: f32 = 3600.0;" in out

    def test_functions_use_fn_keyword_with_arrow_return(self):
        out = WGSLBackend().compile(_profile(SPRING))
        # Rust-like function syntax.
        assert "fn " in out
        assert " -> f32 {" in out
        # No old-school C-style return type before name.
        assert "f32 spring" not in out  # would indicate HLSL/C-style emit

    def test_breathing_signature_is_idiomatic_wgsl(self):
        out = WGSLBackend().compile(_profile(BREATHING))
        sig = (
            "fn breath_simple(base: f32, amp: f32, omega: f32, "
            "phase: f32, t: f32) -> f32 {"
        )
        assert sig in out


# ── Math name mapping ─────────────────────────────────────────


class TestWGSLMath:
    def test_math_built_ins_lowercase_no_namespace(self):
        out = WGSLBackend().compile(_profile(SPRING))
        # Bare names; no `Math.`, no `math.`, no `glm::`.
        assert "exp(" in out
        assert "cos(" in out
        assert "sqrt(" in out
        assert "Math.Exp(" not in out
        assert "Math.Cos(" not in out
        assert "math.exp(" not in out

    def test_pow_is_built_in(self):
        out = WGSLBackend().compile(_profile(FRESNEL))
        assert "pow(" in out
        # Not the synthesized helper -- pow IS native in WGSL.
        assert "_forge_pow" not in out

    def test_log_is_natural_log_no_log10_unless_used(self):
        out = WGSLBackend().compile(_profile(SPRING))
        # log() in WGSL is natural log by spec, same as GLSL/HLSL.
        # log10 doesn't appear unless the EML kernel uses it.
        assert "_forge_log10" not in out


# ── Drift warning ─────────────────────────────────────────────


class TestWGSLDriftWarning:
    def test_chain_2_emits_warning(self):
        out = WGSLBackend().compile(_profile(BREATHING))
        # breath_simple is chain 2 -> WARNING line should appear.
        assert "WARNING: float32 precision drift risk" in out
        assert "chain_order=2" in out

    def test_chain_6_emits_warning(self):
        out = WGSLBackend().compile(_profile(FBM_WARPED))
        # warp_depth_3 is chain 6 -> warning still emitted.
        assert "WARNING: float32 precision drift risk" in out
        assert "chain_order=6" in out

    def test_wants_drift_warning_floor_is_two(self):
        # chain 1 -> no warning
        emit, _ = _wants_drift_warning({
            "status": "ok", "chain_order": 1, "fp16_drift_risk": "LOW",
        })
        assert emit is False
        # chain 2 -> warning
        emit, why = _wants_drift_warning({
            "status": "ok", "chain_order": 2, "fp16_drift_risk": "LOW",
        })
        assert emit is True
        assert "chain_order=2" in why


# ── Identifier handling ───────────────────────────────────────


class TestWGSLIdentifiers:
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
        out = WGSLBackend().compile(_profile_source(src))
        # WGSL: `true` / `false` lowercase. Make sure we don't leak
        # Python's `True` / `False`.
        assert "True" not in out
        assert "False" not in out
        assert "true" in out

    def test_safe_ident_renames_wgsl_reserved(self):
        assert _safe_ident("fn") == "fn_"
        assert _safe_ident("var") == "var_"
        assert _safe_ident("let") == "let_"
        assert _safe_ident("step") == "step_"  # WGSL built-in
        assert _safe_ident("smoothstep") == "smoothstep_"
        assert _safe_ident("regular_name") == "regular_name"

    def test_reserved_set_contains_wgsl_keywords(self):
        for word in (
            "fn", "let", "var", "const", "struct", "return",
            "if", "else", "for", "while", "loop", "break",
            "continue", "f32", "i32", "u32", "bool",
            "true", "false", "private", "uniform", "storage",
        ):
            assert word in _WGSL_RESERVED, f"{word!r} should be reserved"


# ── Statement lowering ────────────────────────────────────────


class TestWGSLStatements:
    def test_let_uses_let_keyword(self):
        out = WGSLBackend().compile(_profile(DIFFUSE))
        # diffuse.eml has `let f90 = ...`
        assert "let f90: f32 =" in out

    def test_no_static_storage_on_constants(self):
        # WGSL has no `static`; the GDScript word should not leak
        # if someone copy-pasted a backend.
        out = WGSLBackend().compile(_profile(BREATHING))
        assert "static const " not in out
        assert "static " not in out


# ── Tuple returns ─────────────────────────────────────────────


class TestWGSLTuples:
    def test_tuple_return_emits_struct_and_constructor(self):
        src = """
        module test_tuple;
        fn pair(x: Real) -> (Real, Real)
            where chain_order <= 0
        {
            (x, x)
        }
        """
        out = WGSLBackend().compile(_profile_source(src))
        assert "struct PairResult {" in out
        assert "e0: f32," in out
        assert "e1: f32," in out
        # WGSL constructor form: StructName(arg0, arg1).
        assert "return PairResult(x, x);" in out


# ── Naga validation (real) ────────────────────────────────────


@pytest.mark.skipif(NAGA is None, reason="naga-cli not installed")
@pytest.mark.parametrize("eml", [SPRING, FRESNEL, BREATHING, DIFFUSE, FBM_WARPED],
                         ids=lambda p: p.name)
def test_naga_validates_gaming_kernel(eml: Path):
    """Generated WGSL passes naga's validator."""
    out = WGSLBackend().compile(_profile(eml))
    with tempfile.NamedTemporaryFile(
        "w", suffix=".wgsl", delete=False, encoding="utf-8",
    ) as f:
        f.write(out)
        path = f.name
    try:
        result = subprocess.run(
            [NAGA, path], capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"naga validation failed for {eml.name}:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}\n"
            f"---WGSL---\n{out}"
        )
    finally:
        os.unlink(path)


# ── End-to-end: every gaming kernel must compile ──────────────


GAMING_DIR = REPO_ROOT / "industries" / "gaming"


@pytest.mark.parametrize(
    "eml", sorted(GAMING_DIR.rglob("*.eml")), ids=lambda p: p.name,
)
def test_gaming_kernel_compiles_to_wgsl(eml: Path):
    """Every gaming .eml compiles to a non-empty WGSL file."""
    out = WGSLBackend().compile(_profile(eml))
    # Sanity: at least one fn definition per file.
    assert "fn " in out
    # Header always present.
    assert "Generated by EML-lang WGSL backend" in out


# ── Optimizer flag ────────────────────────────────────────────


def test_no_optimize_flag_still_produces_valid_output():
    """optimize=False bypasses the optimizer cleanly."""
    out = WGSLBackend(optimize=False).compile(_profile(SPRING))
    assert "fn " in out
    assert "Generated by EML-lang WGSL backend" in out
