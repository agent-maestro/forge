"""Tests for the GLSL shader backend (desktop 330 core + ES 300)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.glsl_backend import (
    GLSLBackend,
    CompileError as GlslErr,
    _DRIFT_WARN_CHAIN_FLOOR,
    _struct_name,
    _wants_drift_warning,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"
DOPPLER = REPO_ROOT / "industries" / "gaming" / "audio" / "doppler.eml"
PERLIN = REPO_ROOT / "industries" / "gaming" / "procedural" / "perlin.eml"


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Flavor selection / version directives ─────────────────────


class TestFlavorVersionDirective:
    def test_desktop_emits_330_core(self):
        out = GLSLBackend(flavor="desktop").compile(_profile(SPRING))
        # Version directive must be the very first non-empty line.
        first_nonempty = next(
            ln for ln in out.split("\n") if ln.strip()
        )
        assert first_nonempty == "#version 330 core"

    def test_es_emits_300_es_with_precision_header(self):
        out = GLSLBackend(flavor="es").compile(_profile(SPRING))
        lines = out.split("\n")
        first_nonempty = next(ln for ln in lines if ln.strip())
        assert first_nonempty == "#version 300 es"
        # Precision header is mandatory in ES.
        assert "precision highp float;" in out
        assert "precision highp int;" in out

    def test_desktop_does_not_emit_precision_header(self):
        out = GLSLBackend(flavor="desktop").compile(_profile(SPRING))
        assert "precision highp" not in out
        assert "precision mediump" not in out

    def test_invalid_flavor_raises(self):
        with pytest.raises(ValueError, match="flavor must be one of"):
            GLSLBackend(flavor="vulkan")

    def test_default_flavor_is_desktop(self):
        out = GLSLBackend().compile(_profile(SPRING))
        assert "#version 330 core" in out


class TestGLSLStructure:
    def test_no_static_keyword_on_constants(self):
        # GLSL uses `const`, NOT `static const` (which is HLSL).
        out = GLSLBackend().compile(_profile(SPRING))
        assert "const float ZERO = 0.0;" in out
        assert "static const" not in out

    def test_no_namespace_or_class_wrappers(self):
        out = GLSLBackend().compile(_profile(SPRING))
        assert "namespace " not in out
        assert "public static class" not in out

    def test_function_library_no_entry_point(self):
        out = GLSLBackend().compile(_profile(SPRING))
        # No vertex / fragment / compute entry point.
        assert "void main(" not in out
        assert "gl_Position" not in out
        assert "gl_FragCoord" not in out

    def test_no_double_keyword(self):
        for path in [SPRING, FRESNEL, DOPPLER, PERLIN]:
            out = GLSLBackend().compile(_profile(path))
            assert " double " not in out, (
                f"unexpected double keyword in {path.name}"
            )


class TestGLSLLiterals:
    def test_float_literals_have_no_f_suffix(self):
        # GLSL 330 core / GLSL ES 300: plain `1.0` is unambiguously
        # float (no `double` exists in these profiles). The HLSL
        # `f` suffix is a portability hazard here.
        src = "module lit;\nfn f(x: Real) -> Real { x * 0.5 + 1.0 }\n"
        out = GLSLBackend().compile(_profile_source(src))
        # Must contain bare 0.5 and 1.0 (no f-suffix).
        assert "0.5" in out
        assert "1.0" in out
        # Must NOT contain `f`-suffixed forms.
        assert "0.5f" not in out
        assert "1.0f" not in out
        # Sanity: not literally "double" either.
        assert "0.5d" not in out


class TestGLSLMath:
    def test_intrinsics_lowercase_no_namespace(self):
        out = GLSLBackend().compile(_profile(SPRING))
        assert "exp(" in out
        assert "cos(" in out
        assert "sqrt(" in out
        assert "Math." not in out

    def test_pow_lowered_to_pow(self):
        out = GLSLBackend().compile(_profile(FRESNEL))
        assert "pow(" in out

    def test_clamp_lowered_to_clamp(self):
        # GLSL has no saturate; we always emit clamp(x, lo, hi).
        src = (
            "module clamp_demo;\n"
            "fn clip(x: Real, lo: Real, hi: Real) -> Real { clamp(x, lo, hi) }\n"
        )
        out = GLSLBackend().compile(_profile_source(src))
        assert "clamp(" in out
        assert "saturate(" not in out

    def test_eml_lowering(self):
        src = (
            "module eml_demo;\n"
            "fn f(x: Real, y: Real) -> Real { eml(x, y) }\n"
        )
        out = GLSLBackend().compile(_profile_source(src))
        assert "exp(" in out and "log(" in out

    def test_exp10_synthesises_helper(self):
        src = (
            "module exp10_demo;\n"
            "fn f(x: Real) -> Real { exp10(x) }\n"
        )
        out = GLSLBackend().compile(_profile_source(src))
        assert "_forge_exp10" in out
        assert "pow(10.0, x)" in out

    def test_log10_lowers_to_log_division(self):
        # GLSL 330 core has no log10. Backend rewrites it as
        # `(log(x) / log(10.0))` inline.
        src = (
            "module log10_demo;\n"
            "fn f(x: Real) -> Real { log10(x) }\n"
        )
        out = GLSLBackend().compile(_profile_source(src))
        assert "log(10.0)" in out
        # Should NOT call `log10(...)` directly.
        assert "log10(" not in out

    def test_arcsin_lowers_to_asin(self):
        src = (
            "module arcsin_demo;\n"
            "fn f(x: Real) -> Real { arcsin(x) }\n"
        )
        out = GLSLBackend().compile(_profile_source(src))
        assert "asin(" in out
        assert "arcsin(" not in out


class TestGLSLDriftWarnings:
    def test_chain_4_function_emits_warning(self):
        out = GLSLBackend().compile(_profile(SPRING))
        assert "WARNING: float32 precision drift risk" in out
        assert "chain_order=4" in out

    def test_chain_0_function_does_not_emit_warning(self):
        out = GLSLBackend().compile(_profile(DOPPLER))
        assert "WARNING: float32 precision drift risk" not in out

    def test_drift_warning_helper(self):
        ok, _ = _wants_drift_warning({"chain_order": 0,
                                       "fp16_drift_risk": "LOW"})
        assert not ok
        ok, why = _wants_drift_warning({"chain_order": 2,
                                          "fp16_drift_risk": "LOW"})
        assert ok and "chain_order=2" in why
        ok, why = _wants_drift_warning({"chain_order": 0,
                                          "fp16_drift_risk": "HIGH"})
        assert ok and "drift_risk=HIGH" in why
        ok, _ = _wants_drift_warning({"status": "complex_body",
                                       "chain_order": 99})
        assert not ok

    def test_drift_floor_constant(self):
        assert _DRIFT_WARN_CHAIN_FLOOR == 2

    def test_drift_warning_appears_in_both_flavors(self):
        for flavor in ("desktop", "es"):
            out = GLSLBackend(flavor=flavor).compile(_profile(SPRING))
            assert "WARNING: float32 precision drift risk" in out


class TestGLSLHelpers:
    def test_struct_name_pascal_cases(self):
        assert _struct_name("foo") == "FooResult"
        assert _struct_name("foo_bar_baz") == "FooBarBazResult"

    def test_in_module_call_renaming_is_consistent(self):
        # If a module defines a function in _GLSL_RESERVED, both the
        # function definition AND any in-module CALL into it should
        # carry the same trailing-underscore mangling. We pass
        # optimize=False because the inliner would otherwise replace
        # the call with the callee's body and we'd never test the
        # rename path at the call site.
        src = (
            "module rename_demo;\n"
            "fn step(x: Real) -> Real { x + 1.0 }\n"
            "fn caller(x: Real) -> Real { step(x) }\n"
        )
        out = GLSLBackend(optimize=False).compile(_profile_source(src))
        assert "float step_(float x)" in out
        assert "step_(x)" in out

    def test_external_call_to_intrinsic_passes_through(self):
        # GLSL has its own `mix` intrinsic; if the user calls `mix`
        # WITHOUT defining it, the backend should NOT rename it.
        src = (
            "module passthrough;\n"
            "fn f(a: Real, b: Real, t: Real) -> Real { mix(a, b, t) }\n"
        )
        out = GLSLBackend().compile(_profile_source(src))
        assert "mix(a, b, t)" in out
        assert "mix_(" not in out


# ── Corpus-wide compilation matrix (both flavors) ─────────────


def _collect_corpus_eml() -> list[Path]:
    industries = list((REPO_ROOT / "industries").rglob("*.eml"))
    stdlib = list((REPO_ROOT / "lang" / "spec" / "stdlib").glob("*.eml"))
    return sorted(industries + stdlib)


@pytest.mark.parametrize("eml_path", _collect_corpus_eml())
def test_corpus_compiles_to_glsl_desktop(eml_path: Path):
    mod = _profile(eml_path)
    out = GLSLBackend(flavor="desktop").compile(mod)
    assert "#version 330 core" in out
    if mod.functions and not all(fn.is_extern for fn in mod.functions):
        assert "float " in out or "int " in out


@pytest.mark.parametrize("eml_path", _collect_corpus_eml())
def test_corpus_compiles_to_glsl_es(eml_path: Path):
    mod = _profile(eml_path)
    out = GLSLBackend(flavor="es").compile(mod)
    assert "#version 300 es" in out
    assert "precision highp float;" in out
    if mod.functions and not all(fn.is_extern for fn in mod.functions):
        assert "float " in out or "int " in out
