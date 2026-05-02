"""Tests for the HLSL shader backend (function library form)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.hlsl_backend import (
    HLSLBackend,
    CompileError as HlslErr,
    _DRIFT_WARN_CHAIN_FLOOR,
    _include_guard,
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


# ── Structural properties ──────────────────────────────────────


class TestHLSLStructure:
    def test_include_guard_present(self):
        out = HLSLBackend().compile(_profile(SPRING))
        assert "#ifndef FORGE_SPRING_HLSL" in out
        assert "#define FORGE_SPRING_HLSL" in out
        assert "#endif  // FORGE_SPRING_HLSL" in out

    def test_no_class_or_namespace(self):
        # HLSL is C-like and has no class/namespace; the file must
        # be flat function definitions.
        out = HLSLBackend().compile(_profile(SPRING))
        assert "namespace " not in out
        assert "public static class" not in out

    def test_function_library_no_entry_point(self):
        # Should NOT emit a vertex/fragment/compute shader entry.
        out = HLSLBackend().compile(_profile(SPRING))
        assert ":SV_Target" not in out
        assert ": SV_Target" not in out
        assert "[shader(" not in out
        assert "void main(" not in out

    def test_constants_use_static_const_with_f_suffix(self):
        out = HLSLBackend().compile(_profile(SPRING))
        assert "static const float ZERO = 0.0f;" in out
        assert "static const float POS_MAX = 10000.0f;" in out

    def test_no_double_keyword(self):
        # Even though EML 'Real' nominally maps to f64, the HLSL
        # backend forces float32 -- so 'double' must NOT appear in
        # the generated source for these kernels.
        for path in [SPRING, FRESNEL, DOPPLER, PERLIN]:
            out = HLSLBackend().compile(_profile(path))
            assert " double " not in out, f"unexpected double in {path.name}"


class TestHLSLMath:
    def test_intrinsics_are_lowercase_no_namespace(self):
        out = HLSLBackend().compile(_profile(SPRING))
        # HLSL is `exp(...)`, NOT `Math.Exp(...)` or `Math.exp(...)`.
        assert "exp(" in out
        assert "cos(" in out
        assert "sqrt(" in out
        # PascalCase forms (C# style) must NOT appear.
        assert "Math.Exp(" not in out
        assert "Math.Cos(" not in out
        # Math. prefix must NOT appear at all.
        assert "Math." not in out

    def test_pow_lowered_to_pow(self):
        out = HLSLBackend().compile(_profile(FRESNEL))
        assert "pow(" in out

    def test_clamp_lowered_to_clamp(self):
        src = (
            "module clamp_demo;\n"
            "fn clip(x: Real, lo: Real, hi: Real) -> Real { clamp(x, lo, hi) }\n"
        )
        out = HLSLBackend().compile(_profile_source(src))
        assert "clamp(" in out

    def test_eml_lowering(self):
        src = (
            "module eml_demo;\n"
            "fn f(x: Real, y: Real) -> Real { eml(x, y) }\n"
        )
        out = HLSLBackend().compile(_profile_source(src))
        # `log` is HLSL's natural log -- exactly what EML wants.
        assert "exp(" in out and "log(" in out


class TestHLSLDriftWarnings:
    def test_chain_4_function_emits_warning(self):
        # spring.eml's damped_position_offset is chain order 4
        # (sqrt nested under cos plus separate exp factor).
        out = HLSLBackend().compile(_profile(SPRING))
        # Warning header expected.
        assert "WARNING: float32 precision drift risk" in out
        # And the per-function profile line should call out the chain.
        assert "chain_order=4" in out

    def test_chain_0_function_does_not_emit_warning(self):
        # doppler.eml is chain order 0 -- no warning should fire.
        out = HLSLBackend().compile(_profile(DOPPLER))
        # Header still mentions chain 2+ floor (informational only)
        # but a per-function WARNING block should NOT appear.
        # The WARNING text appears only in two spots: the header
        # informational mention and per-function blocks. doppler has
        # no chain >= 2 fns and no MEDIUM/HIGH drift risk, so
        # neither header nor function-block warnings should exist.
        assert "WARNING: float32 precision drift risk" not in out

    def test_drift_warning_helper(self):
        # chain 0 -> no warning
        ok, why = _wants_drift_warning({"chain_order": 0,
                                         "fp16_drift_risk": "LOW"})
        assert not ok
        # chain 2+ -> warning regardless of drift_risk label
        ok, why = _wants_drift_warning({"chain_order": 2,
                                         "fp16_drift_risk": "LOW"})
        assert ok
        assert "chain_order=2" in why
        # drift_risk HIGH alone -> warning even at chain 0
        ok, why = _wants_drift_warning({"chain_order": 0,
                                         "fp16_drift_risk": "HIGH"})
        assert ok
        assert "drift_risk=HIGH" in why
        # complex_body status -> never emit (we don't have a profile)
        ok, why = _wants_drift_warning({"status": "complex_body",
                                         "chain_order": 99})
        assert not ok

    def test_drift_floor_constant(self):
        # The floor is documented and stable; if you change it,
        # this test is the sentinel that flags downstream wording.
        assert _DRIFT_WARN_CHAIN_FLOOR == 2


class TestHLSLLiteralAndIdentifier:
    def test_float_literals_have_f_suffix(self):
        src = "module lit;\nfn f(x: Real) -> Real { x * 0.5 + 1.0 }\n"
        out = HLSLBackend().compile(_profile_source(src))
        # No bare double-typed literal escapes; must end in `f`.
        assert "0.5f" in out
        assert "1.0f" in out

    def test_int_literals_no_suffix(self):
        src = "module ilit;\nfn f(n: i32) -> i32 { n + 3 }\n"
        out = HLSLBackend().compile(_profile_source(src))
        # Integer literals stay plain integers (no f suffix).
        # The expression should contain a bare `3`.
        assert "+ 3)" in out or "+ 3 " in out

    def test_snake_case_identifiers_preserved(self):
        out = HLSLBackend().compile(_profile(SPRING))
        # We deliberately keep snake_case to match Java/C#/C/Rust
        # source-to-source diffability.
        assert "spring_step_velocity" in out
        assert "x_target" in out


class TestHLSLHelpers:
    def test_include_guard_uppercases_module(self):
        assert _include_guard("foo") == "FORGE_FOO_HLSL"
        assert _include_guard("foo_bar_baz") == "FORGE_FOO_BAR_BAZ_HLSL"

    def test_struct_name_pascal_cases(self):
        assert _struct_name("foo") == "FooResult"
        assert _struct_name("foo_bar_baz") == "FooBarBazResult"


# ── Forward declarations ──────────────────────────────────────


class TestHLSLForwardDeclarations:
    def test_forward_decls_section_emitted(self):
        out = HLSLBackend().compile(_profile(SPRING))
        assert "// Forward declarations" in out

    def test_externs_resolve_via_forward_decls(self):
        # Regression for Issue #2: aes.eml declares gf256_square as
        # `extern fn` AT THE BOTTOM of the file but calls it from
        # the body of gf256_inverse near the top. Without forward
        # decls DXC fails with "use of undeclared identifier
        # 'gf256_square'".
        aes = REPO_ROOT / "industries" / "crypto" / "symmetric" / "aes.eml"
        out = HLSLBackend().compile(_profile(aes))
        # The forward decl should appear before the first body that
        # references gf256_square.
        decl_idx = out.index("float gf256_square(float b);")
        first_use_idx = out.index("gf256_square(input)")
        assert decl_idx < first_use_idx, (
            "forward declaration must precede first use"
        )


# ── Corpus-wide compilation matrix ─────────────────────────────


def _collect_corpus_eml() -> list[Path]:
    industries = list((REPO_ROOT / "industries").rglob("*.eml"))
    stdlib = list((REPO_ROOT / "lang" / "spec" / "stdlib").glob("*.eml"))
    return sorted(industries + stdlib)


@pytest.mark.parametrize("eml_path", _collect_corpus_eml())
def test_corpus_eml_compiles_to_hlsl(eml_path: Path):
    """Every .eml in industries/ + stdlib/ must produce HLSL with a
    valid include guard and at least one float-typed function (or be
    a constants-only module)."""
    mod = _profile(eml_path)
    out = HLSLBackend().compile(mod)
    guard = _include_guard(mod.name or "anon")
    assert f"#ifndef {guard}" in out
    assert f"#endif  // {guard}" in out
    # If the module has any function, at least one float signature
    # must appear.
    if mod.functions and not all(fn.is_extern for fn in mod.functions):
        assert "float " in out or "half " in out or "int " in out
