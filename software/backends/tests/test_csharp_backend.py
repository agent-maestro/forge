"""Tests for the C# (Unity-ready) backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.csharp_backend import (
    CSharpBackend,
    CompileError as CsErr,
    _budget_hint,
    _xml_escape,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SPRING = REPO_ROOT / "industries" / "gaming" / "physics" / "spring.eml"
FRESNEL = REPO_ROOT / "industries" / "gaming" / "rendering" / "fresnel.eml"


def _profile(path: Path):
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return mod


def _profile_source(src: str):
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return mod


# ── Structural properties ──────────────────────────────────────


class TestCSharpStructure:
    def test_namespace_and_class(self):
        out = CSharpBackend().compile(_profile(SPRING))
        assert "namespace Forge" in out
        assert "public static class Spring" in out

    def test_required_using_directives(self):
        out = CSharpBackend().compile(_profile(SPRING))
        assert "using System;" in out
        assert "using System.Runtime.CompilerServices;" in out

    def test_methods_have_aggressive_inlining(self):
        out = CSharpBackend().compile(_profile(SPRING))
        # Every public static method gets the attribute.
        # Spring has 3 functions; expect at least 3 occurrences.
        count = out.count("[MethodImpl(MethodImplOptions.AggressiveInlining)]")
        assert count >= 3

    def test_constants_use_const_for_literals(self):
        out = CSharpBackend().compile(_profile(SPRING))
        assert "public const double ZERO = 0.0;" in out
        assert "public const double POS_MAX = 10000.0;" in out

    def test_static_class_declaration(self):
        out = CSharpBackend().compile(_profile(FRESNEL))
        assert "public static class Fresnel" in out


class TestCSharpMath:
    def test_math_routines_use_pascal_case(self):
        out = CSharpBackend().compile(_profile(SPRING))
        # exp, cos, sqrt all appear in damped_position_offset.
        assert "Math.Exp(" in out
        assert "Math.Cos(" in out
        assert "Math.Sqrt(" in out
        # Lowercase forms must NOT appear (would be wrong API surface).
        assert "Math.exp(" not in out
        assert "Math.cos(" not in out

    def test_pow_is_math_pow(self):
        out = CSharpBackend().compile(_profile(FRESNEL))
        assert "Math.Pow(" in out

    def test_clamp_uses_math_clamp(self):
        src = (
            "module clamp_demo;\n"
            "fn clip(x: Real, lo: Real, hi: Real) -> Real { clamp(x, lo, hi) }\n"
        )
        out = CSharpBackend().compile(_profile_source(src))
        assert "Math.Clamp(" in out

    def test_eml_lowering(self):
        src = (
            "module eml_demo;\n"
            "fn f(x: Real, y: Real) -> Real { eml(x, y) }\n"
        )
        out = CSharpBackend().compile(_profile_source(src))
        assert "Math.Exp(" in out and "Math.Log(" in out


class TestCSharpDocComments:
    def test_xml_doc_summary_and_remarks(self):
        out = CSharpBackend().compile(_profile(SPRING))
        assert "/// <summary>" in out
        assert "/// </summary>" in out
        assert "/// <remarks>" in out
        assert "Pfaffian profile:" in out
        assert "Unity hint:" in out

    def test_param_and_returns_tags(self):
        out = CSharpBackend().compile(_profile(SPRING))
        assert '/// <param name="x">' in out
        assert "/// <returns>" in out

    def test_xml_escaping_of_comparison_operators(self):
        # The requires clauses use `<=` / `>=` which would be invalid
        # raw XML inside a doc-comment. Backend must escape them.
        out = CSharpBackend().compile(_profile(SPRING))
        # Raw `<=` inside an XML-tagged remarks block would fail
        # CS1570; assert escaping landed.
        assert "&lt;=" in out
        assert "&gt;=" in out
        # And the raw form is NOT inside <remarks> blocks.
        # (We allow `<=` / `>=` in code bodies, just not in doc XML.)
        # Conservative check: the literal "(stiffness >= ZERO)" must
        # not appear ANYWHERE -- it would only appear inside a doc
        # string, where it should now be escaped.
        assert "(stiffness >= ZERO)" not in out

    def test_verify_annotation_in_remarks(self):
        out = CSharpBackend().compile(_profile(SPRING))
        assert "forge.verify: lean theorem=spring_step_velocity_bounded" in out


class TestCSharpExpressionBody:
    def test_simple_function_uses_expression_body(self):
        out = CSharpBackend().compile(_profile(FRESNEL))
        # schlick_fresnel is a single-expression function with no
        # `let` bindings. It should land as `=> expr;`.
        assert "=> " in out


class TestBudgetHint:
    def test_chain_zero_hint_format(self):
        h = _budget_hint(0)
        assert "chain=0" in h
        assert "ns/call" in h
        assert "1000 calls" in h

    def test_chain_high_hint_extrapolates(self):
        h = _budget_hint(7)
        assert "chain=7" in h
        # Synthesised cost should grow with chain order.
        assert "ns/call" in h

    def test_unknown_chain_does_not_crash(self):
        h = _budget_hint(None)
        assert "chain=?" in h


class TestXmlEscape:
    def test_lt_gt_amp(self):
        assert _xml_escape("a < b") == "a &lt; b"
        assert _xml_escape("a > b") == "a &gt; b"
        assert _xml_escape("a & b") == "a &amp; b"

    def test_amp_first_to_avoid_double_escape(self):
        assert _xml_escape("&lt;") == "&amp;lt;"


# ── Corpus-wide compilation matrix ─────────────────────────────


def _collect_corpus_eml() -> list[Path]:
    industries = list((REPO_ROOT / "industries").rglob("*.eml"))
    stdlib = list((REPO_ROOT / "lang" / "spec" / "stdlib").glob("*.eml"))
    return sorted(industries + stdlib)


@pytest.mark.parametrize("eml_path", _collect_corpus_eml())
def test_corpus_eml_compiles_to_csharp(eml_path: Path):
    """Every .eml file in industries/ + stdlib/ must produce valid
    C# source (structural check). Catches regressions where a new
    NodeKind shows up that the backend hasn't lowered yet."""
    mod = _profile(eml_path)
    out = CSharpBackend().compile(mod)
    # Required tokens for any non-empty module.
    assert "using System;" in out
    assert "namespace Forge" in out
    assert "public static class" in out
    # Every module either defines methods with the inlining attribute
    # OR has only constants. If functions exist, attribute must too.
    if mod.functions and not all(fn.is_extern for fn in mod.functions):
        assert "[MethodImpl(MethodImplOptions.AggressiveInlining)]" in out
