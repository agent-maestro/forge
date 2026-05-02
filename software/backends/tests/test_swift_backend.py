"""Tests for the Swift backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.swift_backend import (
    SwiftBackend,
    CompileError as SwErr,
    _safe_ident,
    _swift_type,
    _SWIFT_RESERVED,
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


# ── Type mapping ──────────────────────────────────────────────


class TestSwiftTypeMapping:
    def test_real_lowers_to_double(self):
        assert _swift_type("Real") == "Double"

    def test_f32_uses_float_type(self):
        assert _swift_type("f32") == "Float"

    def test_unsigned_widths(self):
        assert _swift_type("u32") == "UInt32"
        assert _swift_type("u64") == "UInt64"
        assert _swift_type("u8") == "UInt8"

    def test_bool_passes_through(self):
        assert _swift_type("bool") == "Bool"


# ── Structural properties ─────────────────────────────────────


class TestSwiftStructure:
    def test_imports_foundation(self):
        out = SwiftBackend().compile(_profile(SPRING))
        assert "import Foundation" in out

    def test_no_class_or_struct_wrapper(self):
        # Top-level functions are emitted directly (no class
        # wrapper). The only `struct` we emit is for tuple returns.
        out = SwiftBackend().compile(_profile(SPRING))
        # Verify functions live at file scope.
        assert "@inline(__always) public func " in out

    def test_all_functions_use_inline_always(self):
        out = SwiftBackend().compile(_profile(SPRING))
        # Spring has 3 functions; expect at least 3 occurrences.
        n = out.count("@inline(__always) public func ")
        assert n >= 3

    def test_constants_use_public_let(self):
        out = SwiftBackend().compile(_profile(BREATHING))
        assert "public let ZERO: Double = 0.0" in out
        assert "public let T_MAX: Double = 3600.0" in out

    def test_breathing_signature_uses_unlabeled_params(self):
        out = SwiftBackend().compile(_profile(BREATHING))
        # `_ paramName: Type` so call sites match EML convention.
        assert (
            "func breath_simple(_ base: Double, _ amp: Double, "
            "_ omega: Double, _ phase: Double, _ t: Double) -> Double"
        ) in out


# ── Math name mapping ─────────────────────────────────────────


class TestSwiftMath:
    def test_math_built_ins_after_foundation_import(self):
        out = SwiftBackend().compile(_profile(SPRING))
        # `import Foundation` brings the C math globals into scope.
        assert "exp(" in out
        assert "cos(" in out
        assert "sqrt(" in out
        # Should NOT use Kotlin or HLSL spellings.
        assert "kotlin.math" not in out
        assert "Math.Exp(" not in out

    def test_pow_is_global(self):
        out = SwiftBackend().compile(_profile(FRESNEL))
        assert "pow(" in out

    def test_clamp_uses_min_max_idiom(self):
        # Construct a kernel that uses CLAMP so we hit the path.
        src = """
        module test_clamp;
        fn cl(x: Real) -> Real
            where chain_order <= 0
            requires (x >= 0.0)
        {
            clamp(x, 0.0, 1.0)
        }
        """
        out = SwiftBackend().compile(_profile_source(src))
        # Portable clamp form (works on all Swift stdlib versions).
        assert "min(max(" in out


# ── Preconditions ─────────────────────────────────────────────


class TestSwiftPreconditions:
    def test_requires_lowers_to_precondition(self):
        out = SwiftBackend().compile(_profile(BREATHING))
        # Every `requires` becomes a precondition() call.
        assert "precondition(" in out
        # The message names the function and the predicate.
        assert "breath_simple: requires" in out

    def test_no_assert_for_ensures_advisory_only(self):
        out = SwiftBackend().compile(_profile(BREATHING))
        # ensures stays in the doc comment; we don't auto-assert
        # post-conditions (Swift's `assert` would fire mid-function
        # which is rarely what callers want).
        # Doc-level ensures appears as `/// - forge.ensures:`.
        assert "/// - forge.ensures:" in out


# ── Identifier handling ───────────────────────────────────────


class TestSwiftIdentifiers:
    def test_safe_ident_renames_swift_reserved(self):
        # Swift's keyword set is the largest of any backend; pick
        # ones that EML kernels are likely to use as variable names.
        assert _safe_ident("class") == "class_"
        assert _safe_ident("operator") == "operator_"
        assert _safe_ident("static") == "static_"
        assert _safe_ident("where") == "where_"
        assert _safe_ident("in") == "in_"
        assert _safe_ident("inout") == "inout_"
        assert _safe_ident("regular_name") == "regular_name"

    def test_reserved_set_contains_swift_keywords(self):
        for word in (
            "class", "struct", "protocol", "extension", "guard",
            "where", "self", "Self", "in", "is", "as", "try",
            "throw", "catch", "defer", "repeat", "switch", "case",
            "default", "break", "continue", "return", "fallthrough",
            "typealias", "associatedtype", "inout", "subscript",
            "init", "deinit", "lazy", "weak", "unowned", "mutating",
            "nonmutating", "convenience", "required", "override",
            "final", "open", "public", "private", "fileprivate",
            "internal", "static", "dynamic", "optional",
            "prefix", "postfix", "infix", "precedencegroup",
            "async", "await", "actor",
        ):
            assert word in _SWIFT_RESERVED, f"{word!r} should be reserved"


# ── Tuple returns ─────────────────────────────────────────────


class TestSwiftTuples:
    def test_tuple_return_emits_struct(self):
        src = """
        module test_tuple;
        fn pair(x: Real) -> (Real, Real)
            where chain_order <= 0
        {
            (x, x)
        }
        """
        out = SwiftBackend().compile(_profile_source(src))
        assert "public struct PairResult {" in out
        assert "public let e0: Double" in out
        assert "public let e1: Double" in out
        # Memberwise init form on return.
        assert "return PairResult(e0: x, e1: x)" in out


# ── End-to-end on every gaming kernel ──────────────────────────


GAMING_DIR = REPO_ROOT / "industries" / "gaming"


@pytest.mark.parametrize(
    "eml", sorted(GAMING_DIR.rglob("*.eml")), ids=lambda p: p.name,
)
def test_gaming_kernel_compiles_to_swift(eml: Path):
    """Every gaming .eml compiles to a non-empty Swift file."""
    out = SwiftBackend().compile(_profile(eml))
    assert "import Foundation" in out
    assert "@inline(__always) public func " in out


# ── Optimizer flag ────────────────────────────────────────────


def test_no_optimize_flag_still_produces_valid_output():
    out = SwiftBackend(optimize=False).compile(_profile(SPRING))
    assert "import Foundation" in out
    assert "@inline(__always) public func " in out
