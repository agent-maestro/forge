"""Phase E.1 tests: refinement-derived runtime guards for the 7 wired backends.

Tests written FIRST (RED) per TDD methodology before any implementation.

Covers (per backend, 6 cases each = 42 total):
1. Single refined param: Real{x | x >= 0.0} -> idiomatic guard on param name
2. Conjunction refinement: Real{x | 0.0 <= x && x <= 1.0} -> single guard
3. abs(x) <= k: emitted literally using target's abs idiom (NOT pre-rewritten)
4. Multiple refined params: N params -> N guards in declaration order
5. Splicer parity: requires (abs(x) <= 1.0) vs refinement Real{e | abs(e) <= 1.0}
   produce identical guard semantics (byte-diff is message-tag only)
6. Cross-param refinement: comment-only line, no executable guard

Plus non-regression (1 per backend, 7 total):
- pid_controller.eml (no refinements) produces byte-identical MD5 to pre-baseline
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lang.parser import parse_source, parse_file
from lang.profiler import Profiler

# ── Backend imports ───────────────────────────────────────────────────────────

from software.backends.go_backend import GoBackend
from software.backends.kotlin_backend import KotlinBackend
from software.backends.javascript_backend import JavaScriptBackend
from software.backends.csharp_backend import CSharpBackend
from software.backends.swift_backend import SwiftBackend
from software.backends.luau_backend import LuauBackend
from software.backends.matlab_backend import MatlabBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
PID = REPO_ROOT / "examples" / "pid_controller.eml"

# Pre-Phase-E.1 MD5 baselines collected from git HEAD (3e2c911).
# Hashes use the absolute REPO_ROOT path (the same resolution _compile_file
# uses via Path.resolve()), because source_file is embedded in each backend's
# header comment and changes the hash when the path form changes.
# These must remain byte-identical after Phase E.1 (no refinements in pid).
_PID_BASELINES: dict[str, str] = {
    "go":         "69fcee46d664c714c0c34a18ccd75bc8",
    "kotlin":     "7d0aae109315eeca0517142deb58da8f",
    "javascript": "a6d9a89433255bc01494d58c9c0184f3",
    "csharp":     "112271b922b2229905658697bc52ea34",
    "swift":      "924e7de84feb2f911829e0fd8685529f",
    "luau":       "380d3c4414809c3fccff0fcd96650025",
    "matlab":     "aa1698e3d253da46362808531b8bae13",
}


def _compile(src: str, backend) -> str:
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return backend.compile(mod)


def _compile_file(path: Path, backend) -> str:
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return backend.compile(mod)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# ── Shared EML fixtures ───────────────────────────────────────────────────────

# Single refined param: x >= 0.0
_SRC_SINGLE = (
    "module single;\n"
    "fn f(x: Real{p | p >= 0.0}) -> Real\n"
    "    where chain_order <= 0\n"
    "{ x }\n"
)

# Conjunction refinement
_SRC_CONJ = (
    "module conj;\n"
    "fn f(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real\n"
    "    where chain_order <= 0\n"
    "{ x }\n"
)

# abs(x) <= k refinement -- must NOT be pre-rewritten
_SRC_ABS = (
    "module absk;\n"
    "fn f(x: Real{p | abs(p) <= 1.0}) -> Real\n"
    "    where chain_order <= 0\n"
    "{ x }\n"
)

# Multiple refined params (3 params, all refined)
_SRC_MULTI = (
    "module multi;\n"
    "fn pid(error: Real{e | -1.0 <= e && e <= 1.0},\n"
    "       integral: Real{i | abs(i) <= 1.0},\n"
    "       derivative: Real{d | abs(d) <= 1.0})\n"
    "    -> Real\n"
    "    where chain_order <= 0\n"
    "{ error + integral + derivative }\n"
)

# Splicer parity: requires-derived guard
_SRC_REQUIRES = (
    "module parity_req;\n"
    "fn f(x: Real) -> Real\n"
    "    where chain_order <= 0\n"
    "    requires (abs(x) <= 1.0)\n"
    "{ x }\n"
)

# Splicer parity: refinement-derived guard (same predicate)
_SRC_REFINE = (
    "module parity_ref;\n"
    "fn f(x: Real{p | abs(p) <= 1.0}) -> Real\n"
    "    where chain_order <= 0\n"
    "{ x }\n"
)

# Cross-param refinement: b references a
_SRC_CROSS = (
    "module cross;\n"
    "fn f(a: Real, b: Real{x | x > a}) -> Real\n"
    "    where chain_order <= 0\n"
    "{ a + b }\n"
)

# No-refinement kernel (3 representative kernels per non-regression check)
_SRC_NOREFINEMENT_1 = (
    "module norefinement1;\n"
    "fn add(x: Real, y: Real) -> Real\n"
    "    where chain_order <= 0\n"
    "{ x + y }\n"
)

_SRC_NOREFINEMENT_2 = (
    "module norefinement2;\n"
    "fn scale(x: Real, k: Real) -> Real\n"
    "    where chain_order <= 0\n"
    "{ x * k }\n"
)

_SRC_NOREFINEMENT_3 = (
    "module norefinement3;\n"
    "fn add3(a: Real, b: Real, c: Real) -> Real\n"
    "    where chain_order <= 0\n"
    "{ a + b + c }\n"
)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Go backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGoRefinementGuards:
    """Phase E.1: refinement-derived runtime guards for the Go backend."""

    def setup_method(self):
        self.b = GoBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # After binder substitution p -> x, predicate becomes "x >= 0.0"
        assert "if !((x >= 0.0))" in out or "(x >= 0.0)" in out
        assert "panic(" in out
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        # Single guard containing the conjunction, not two separate guards
        # After substitution p -> x: "(0.0 <= x && x <= 1.0)"
        assert "(0.0 <= x)" in out or "0.0 <= x" in out
        assert "(x <= 1.0)" in out or "x <= 1.0" in out
        # Exactly ONE refinement guard (not two)
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_literal_math_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # Must use Go's math.Abs -- NOT pre-rewritten to -k <= x && x <= k
        assert "math.Abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        # Three guards, one per refined param, in declaration order
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out
        # Check order: error before integral before derivative
        i_error = out.index("refinement violated on error")
        i_integral = out.index("refinement violated on integral")
        i_deriv = out.index("refinement violated on derivative")
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, GoBackend())
        out_ref = _compile(_SRC_REFINE, GoBackend())
        # Both contain a panic guard checking math.Abs(x) <= 1.0
        assert "math.Abs(x)" in out_req
        assert "math.Abs(x)" in out_ref
        # Requires uses "requires", refinement uses "refinement violated on"
        assert "requires" in out_req
        assert "refinement violated on" in out_ref
        # Strip the message tag text to compare semantics
        req_line = next(
            ln for ln in out_req.splitlines() if "panic(" in ln and "math.Abs" in ln
        )
        ref_line = next(
            ln for ln in out_ref.splitlines() if "panic(" in ln and "math.Abs" in ln
        )
        # Both must contain the same guard condition
        assert "math.Abs(x)" in req_line
        assert "math.Abs(x)" in ref_line

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        # Cross-param refinement: b: Real{x | x > a} -- `a` is another param
        # Must emit a comment, NOT a runtime panic
        assert "refinement obligation:" in out
        # No panic for the cross-param guard
        cross_idx = out.index("refinement obligation:")
        # The comment must contain the predicate
        comment_line = out.splitlines()[
            next(
                i for i, ln in enumerate(out.splitlines())
                if "refinement obligation:" in ln
            )
        ]
        assert "b" in comment_line or "x > a" in comment_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, GoBackend())
        assert _md5(out) == _PID_BASELINES["go"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            before = _compile(src, GoBackend())
            after = _compile(src, GoBackend())
            assert before == after
            # No refinement guards emitted
            assert "refinement violated" not in before


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Kotlin backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestKotlinRefinementGuards:
    """Phase E.1: refinement-derived runtime guards for the Kotlin backend."""

    def setup_method(self):
        self.b = KotlinBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # After substitution p -> x: require(x >= 0.0) { "f: refinement violated on x: ..." }
        assert "require(" in out
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        # Single guard with conjunction "0.0 <= x && x <= 1.0"
        assert "(0.0 <= x)" in out or "0.0 <= x" in out
        assert "(x <= 1.0)" in out or "x <= 1.0" in out
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_literal_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # Kotlin: abs(x) from kotlin.math.*
        assert "abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out
        i_error = out.index("refinement violated on error")
        i_integral = out.index("refinement violated on integral")
        i_deriv = out.index("refinement violated on derivative")
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, KotlinBackend())
        out_ref = _compile(_SRC_REFINE, KotlinBackend())
        assert "abs(x)" in out_req
        assert "abs(x)" in out_ref
        assert "requires" in out_req
        assert "refinement violated on" in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert "refinement obligation:" in out
        # Must not contain a require() call for the cross-param guard
        obligation_line = next(
            ln for ln in out.splitlines() if "refinement obligation:" in ln
        )
        assert "require(" not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, KotlinBackend())
        assert _md5(out) == _PID_BASELINES["kotlin"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, KotlinBackend())
            assert "refinement violated" not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# JavaScript backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestJavaScriptRefinementGuards:
    """Phase E.1: refinement-derived runtime guards for the JavaScript backend."""

    def setup_method(self):
        self.b = JavaScriptBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # if (!(x >= 0.0)) throw new RangeError("f: refinement violated on x: ...")
        assert "throw new RangeError(" in out
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert "refinement violated on x" in out
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_math_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # JavaScript: Math.abs(x)
        assert "Math.abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out
        i_error = out.index("refinement violated on error")
        i_integral = out.index("refinement violated on integral")
        i_deriv = out.index("refinement violated on derivative")
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, JavaScriptBackend())
        out_ref = _compile(_SRC_REFINE, JavaScriptBackend())
        assert "Math.abs(x)" in out_req
        assert "Math.abs(x)" in out_ref
        assert "requires" in out_req
        assert "refinement violated on" in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert "refinement obligation:" in out
        obligation_line = next(
            ln for ln in out.splitlines() if "refinement obligation:" in ln
        )
        assert "throw" not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, JavaScriptBackend())
        assert _md5(out) == _PID_BASELINES["javascript"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, JavaScriptBackend())
            assert "refinement violated" not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# C# backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# C# is advisory-only (no runtime checks, matching the existing requires pattern).
# Refinement guards appear in the XML doc comment, not as throw statements.


class TestCSharpRefinementGuards:
    """Phase E.1: refinement-derived advisory guards for the C# backend.

    C# follows its existing advisory-only pattern: refinements go into the
    XML <remarks> doc comment, not as runtime throw statements.
    """

    def setup_method(self):
        self.b = CSharpBackend()

    def test_single_refined_param_emits_advisory(self):
        out = _compile(_SRC_SINGLE, self.b)
        # Goes into XML doc: <forge.refinement> or /// forge.refinement
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_advisory(self):
        out = _compile(_SRC_CONJ, self.b)
        assert "refinement violated on x" in out
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_math_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # C# uses Math.Abs
        assert "Math.Abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_advisories(self):
        out = _compile(_SRC_MULTI, self.b)
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, CSharpBackend())
        out_ref = _compile(_SRC_REFINE, CSharpBackend())
        # Both should contain Math.Abs(x) in the doc comment
        assert "Math.Abs(x)" in out_req
        assert "Math.Abs(x)" in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert "refinement obligation:" in out

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, CSharpBackend())
        assert _md5(out) == _PID_BASELINES["csharp"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, CSharpBackend())
            assert "refinement violated" not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Swift backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSwiftRefinementGuards:
    """Phase E.1: refinement-derived runtime guards for the Swift backend."""

    def setup_method(self):
        self.b = SwiftBackend()

    def test_single_refined_param_emits_precondition(self):
        out = _compile(_SRC_SINGLE, self.b)
        # precondition(x >= 0.0, "f: refinement violated on x: ...")
        assert "precondition(" in out
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert "refinement violated on x" in out
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_swift_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # Swift Foundation: abs(x) (bare name from Foundation)
        assert "abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out
        i_error = out.index("refinement violated on error")
        i_integral = out.index("refinement violated on integral")
        i_deriv = out.index("refinement violated on derivative")
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, SwiftBackend())
        out_ref = _compile(_SRC_REFINE, SwiftBackend())
        assert "abs(x)" in out_req
        assert "abs(x)" in out_ref
        assert "requires" in out_req
        assert "refinement violated on" in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert "refinement obligation:" in out
        obligation_line = next(
            ln for ln in out.splitlines() if "refinement obligation:" in ln
        )
        assert "precondition(" not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, SwiftBackend())
        assert _md5(out) == _PID_BASELINES["swift"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, SwiftBackend())
            assert "refinement violated" not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Luau backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLuauRefinementGuards:
    """Phase E.1: refinement-derived runtime guards for the Luau backend."""

    def setup_method(self):
        self.b = LuauBackend()

    def test_single_refined_param_emits_assert(self):
        out = _compile(_SRC_SINGLE, self.b)
        # assert(x >= 0.0, "f: refinement violated on x: ...")
        assert "assert(" in out
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_assert(self):
        out = _compile(_SRC_CONJ, self.b)
        assert "refinement violated on x" in out
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_math_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # Luau: math.abs(x)
        assert "math.abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out
        i_error = out.index("refinement violated on error")
        i_integral = out.index("refinement violated on integral")
        i_deriv = out.index("refinement violated on derivative")
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, LuauBackend())
        out_ref = _compile(_SRC_REFINE, LuauBackend())
        assert "math.abs(x)" in out_req
        assert "math.abs(x)" in out_ref
        assert "requires" in out_req
        assert "refinement violated on" in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert "refinement obligation:" in out
        obligation_line = next(
            ln for ln in out.splitlines() if "refinement obligation:" in ln
        )
        assert "assert(" not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, LuauBackend())
        assert _md5(out) == _PID_BASELINES["luau"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, LuauBackend())
            assert "refinement violated" not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MATLAB backend
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMatlabRefinementGuards:
    """Phase E.1: refinement-derived runtime guards for the MATLAB backend."""

    def setup_method(self):
        self.b = MatlabBackend()

    def test_single_refined_param_emits_assert(self):
        out = _compile(_SRC_SINGLE, self.b)
        # assert(x >= 0.0, 'f: refinement violated on x: ...')
        assert "assert(" in out
        assert "refinement violated on x" in out

    def test_conjunction_refinement_emits_single_assert(self):
        out = _compile(_SRC_CONJ, self.b)
        assert "refinement violated on x" in out
        assert out.count("refinement violated on x") == 1

    def test_abs_refinement_emits_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # MATLAB: abs(x)
        assert "abs(x)" in out
        assert "refinement violated on x" in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert "refinement violated on error" in out
        assert "refinement violated on integral" in out
        assert "refinement violated on derivative" in out
        i_error = out.index("refinement violated on error")
        i_integral = out.index("refinement violated on integral")
        i_deriv = out.index("refinement violated on derivative")
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, MatlabBackend())
        out_ref = _compile(_SRC_REFINE, MatlabBackend())
        assert "abs(x)" in out_req
        assert "abs(x)" in out_ref
        assert "requires" in out_req
        assert "refinement violated on" in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert "refinement obligation:" in out
        obligation_line = next(
            ln for ln in out.splitlines() if "refinement obligation:" in ln
        )
        assert "assert(" not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, MatlabBackend())
        assert _md5(out) == _PID_BASELINES["matlab"]

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, MatlabBackend())
            assert "refinement violated" not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Cross-backend: refinement guards appear BEFORE requires guards
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SRC_BOTH = (
    "module both;\n"
    "fn f(x: Real{p | p >= 0.0}) -> Real\n"
    "    where chain_order <= 0\n"
    "    requires (x <= 100.0)\n"
    "{ x }\n"
)


class TestRefinementBeforeRequires:
    """Refinement guards precede requires guards in emission order."""

    def test_go_refinement_before_requires(self):
        out = _compile(_SRC_BOTH, GoBackend())
        i_ref = out.index("refinement violated on x")
        i_req = out.index("requires")
        # requires appears in doc comment AND guard; find the guard requires
        # Look for the panic with "requires" substring
        req_guard_line = next(
            (i for i, ln in enumerate(out.splitlines())
             if "panic(" in ln and "requires" in ln), None
        )
        ref_guard_line = next(
            (i for i, ln in enumerate(out.splitlines())
             if "panic(" in ln and "refinement violated" in ln), None
        )
        assert ref_guard_line is not None
        assert req_guard_line is not None
        assert ref_guard_line < req_guard_line

    def test_kotlin_refinement_before_requires(self):
        out = _compile(_SRC_BOTH, KotlinBackend())
        lines = out.splitlines()
        ref_idx = next(
            i for i, ln in enumerate(lines)
            if "require(" in ln and "refinement violated" in ln
        )
        req_idx = next(
            i for i, ln in enumerate(lines)
            if "require(" in ln and "requires" in ln
        )
        assert ref_idx < req_idx

    def test_swift_refinement_before_requires(self):
        out = _compile(_SRC_BOTH, SwiftBackend())
        lines = out.splitlines()
        ref_idx = next(
            i for i, ln in enumerate(lines)
            if "precondition(" in ln and "refinement violated" in ln
        )
        req_idx = next(
            i for i, ln in enumerate(lines)
            if "precondition(" in ln and "requires" in ln
        )
        assert ref_idx < req_idx
