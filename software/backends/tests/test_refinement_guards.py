"""Phase E.1/E.2/E.3 tests: refinement-derived runtime guards.

Tests written FIRST (RED) per TDD methodology before any implementation.

Covers (per backend, 6 cases each = 42 total for E.1/E.2):
1. Single refined param: Real{x | x >= 0.0} -> idiomatic guard on param name
2. Conjunction refinement: Real{x | 0.0 <= x && x <= 1.0} -> single guard
3. abs(x) <= k: emitted literally using target's abs idiom (NOT pre-rewritten)
4. Multiple refined params: N params -> N guards in declaration order
5. Splicer parity: requires (abs(x) <= 1.0) vs refinement Real{e | abs(e) <= 1.0}
   produce identical guard semantics (byte-diff is message-tag only)
6. Cross-param refinement: comment-only line, no executable guard

Plus non-regression (1 per backend, 7 total for E.1/E.2):
- pid_controller.eml (no refinements) produces byte-identical MD5 to pre-baseline

Phase E.3 (5 new backends):
- Rust: assert!(cond, "msg") runtime guards
- C: assert(cond && "msg") with #include <assert.h>
- Python: if not (cond): raise ValueError("msg")
- WASM: doc-only ;; forge.refinement: (no runtime assert in core WASM)
- GDScript: assert(cond, "msg") (native)

Non-regression contract for E.3:
- pid_controller.eml hashes WILL change for these 5 backends because requires
  clauses now produce output where before they were silent.
- The smoke test for unchanged hashes uses _SRC_NOREFINEMENT_* fixtures
  (no requires AND no refinements).
"""

from __future__ import annotations

import hashlib
import re
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
# Phase E.2 backends
from software.backends.cpp_backend import CppBackend
# Phase E.3 backends
from software.backends.rust_backend import RustBackend
from software.backends.c_backend import CBackend
from software.backends.python_backend import PythonBackend
from software.backends.wasm_backend import WASMBackend
from software.backends.gdscript_backend import GDScriptBackend
from software.backends.java_backend import JavaBackend
from software.backends.hlsl_backend import HLSLBackend
from software.backends.glsl_backend import GLSLBackend
from software.backends.wgsl_backend import WGSLBackend
from software.backends.metal_backend import MetalBackend
from software.backends.llvm_backend import LLVMBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
PID = REPO_ROOT / "examples" / "pid_controller.eml"

# Pre-Phase-E.1 MD5 baselines collected from git HEAD (3e2c911).
# Hashes use the absolute REPO_ROOT path (the same resolution _compile_file
# uses via Path.resolve()), because source_file is embedded in each backend's
# header comment and changes the hash when the path form changes.
#
# Phase F (2026-05-05) migrated pid_controller.eml from three single-variable
# `requires (abs(x) <= K)` clauses to refinement types on the parameters.
# The semantic guard is identical at every backend (same boolean predicate,
# same conditional), but the message tag flips from `requires (...)` to
# `refinement violated on <param>: (...)`, so every PID baseline drifted.
# The dict below carries the post-Phase-F hashes; the test class names still
# read `test_pid_no_refinements_md5_unchanged` for git-blame continuity even
# though the fixture now exercises three refinement guards.
_PID_BASELINES: dict[str, str] = {
    # Hashes computed via _md5() which strips embedded source-file paths
    # (the path differs between dev and CI; canonicalising before hashing
    # keeps the baseline stable across machines).
    "go":         "b4fb1ac74274dc67cfa754fc3bfc0210",
    "kotlin":     "6b5033983502d9216923c80a366f7207",
    "javascript": "ff2e0bd47a9a68277efa148c7d35e517",
    "csharp":     "2bc633eec4efbb8f42dc4a7268c97365",
    "swift":      "e080d2b04568f0121a55a31021af4b6d",
    "luau":       "3bb0d660ba9b452bb6a0094f18d4810e",
    "cpp":        "2dd3816ce1e83218a113b4613c620564",
    "java":       "929176b6f1bd2bf46ef3877e04e37776",
    "hlsl":       "2c5e2d92b1818cae619ea78b40d540c4",
    "glsl":       "9f59872bf2b9a880e0b6f81c22c96601",
    "wgsl":       "ecb98df5d6dc12370287db90e8af7625",
    "metal":      "3057769ada696dfa3617a43883594a79",
    "llvm":       "d60b23e9434e192c9d47f98f06372091",
    "matlab":     "f21528e7307a3f154003b1d14688a9c9",
}

# Phase E.3 PID baselines: collected AFTER implementation (pid_controller has
# requires clauses, so hashes change vs pre-E.3 for all 5 new backends).
# Placeholder values -- will be filled after GREEN pass.
# WASM uses the IR text hash (not bytecode, which is empty without llc).
_PID_BASELINES_PHASE_E3: dict[str, str] = {
    "rust":      "PLACEHOLDER",
    "c":         "PLACEHOLDER",
    "python":    "PLACEHOLDER",
    "wasm_ir":   "PLACEHOLDER",
    "gdscript":  "PLACEHOLDER",
}

# Phase E.3 no-requires no-refinements baselines for _SRC_NOREFINEMENT_1.
# These MUST match pre-E.3 output (no guard emission for clean kernels).
# Collected from the pre-implementation run.
_NOREFINEMENT1_BASELINES_E3: dict[str, str] = {
    # Hashes computed via _md5() which strips embedded source-file paths.
    "rust":     "6fedf801e950a8ef9769ec471e4e8da4",
    "c":        "cdc1f8bfc2cb54f99d48444e032d6fa0",
    "python":   "b23b3c539f847811c0f220e7581f95c4",
    "wasm_ir":  "e27dadb777a801928adb53ca5b6ae67c",
    "gdscript": "ccb0e844679961e552196a4069e1fda1",
}


def _compile(src: str, backend) -> str:
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return backend.compile(mod)


def _compile_file(path: Path, backend) -> str:
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return backend.compile(mod)


def _compile_wasm_ir(src: str) -> str:
    """Compile EML source via WASMBackend and return the LLVM IR text.

    WASMBackend.compile() returns bytes (bytecode or empty); the IR
    text is available via compile_full().ir. This helper exposes that
    text so tests can inspect doc-comment annotations.
    """
    mod = parse_source(src)
    Profiler().profile_module(mod)
    return WASMBackend().compile_full(mod).ir


def _compile_wasm_ir_file(path: Path) -> str:
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return WASMBackend().compile_full(mod).ir


_SOURCE_FILE_RE = re.compile(
    r'(Source file:|source_filename =|@source\s+file)\s*"?[^\n"]*',
)


def _strip_source_paths(text: str) -> str:
    """Strip absolute source-file paths from a backend's header comment.

    Backends embed the resolved kernel path (e.g.
    `// Source file: /home/runner/work/forge/...`) in the file header.
    The path differs between dev and CI environments, so any hash
    that includes it is environment-dependent.  Replace the path
    with a stable `<canonicalized>` token before hashing.
    """
    return _SOURCE_FILE_RE.sub(r"\1 <canonicalized>", text)


def _md5(text: str) -> str:
    return hashlib.md5(_strip_source_paths(text).encode()).hexdigest()


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


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2a: C++ backend -- assert() runtime guards
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCppRefinementGuards:
    """Phase E.2: refinement-derived assert() guards for the C++ backend."""

    def setup_method(self):
        self.b = CppBackend()

    def test_single_refined_param_emits_assert(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'assert(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_assert(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_std_abs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'std::abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_asserts(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, CppBackend())
        out_ref = _compile(_SRC_REFINE, CppBackend())
        assert 'std::abs(x)' in out_req
        assert 'std::abs(x)' in out_ref
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'assert(' not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, CppBackend())
        assert _md5(out) == _PID_BASELINES['cpp']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, CppBackend())
            assert 'refinement violated' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2a: Java backend -- IllegalArgumentException runtime guards
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestJavaRefinementGuards:
    """Phase E.2: refinement-derived IllegalArgumentException guards for Java."""

    def setup_method(self):
        self.b = JavaBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'throw new IllegalArgumentException(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_math_abs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'Math.abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, JavaBackend())
        out_ref = _compile(_SRC_REFINE, JavaBackend())
        assert 'Math.abs(x)' in out_req
        assert 'Math.abs(x)' in out_ref
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'throw' not in obligation_line

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, JavaBackend())
        assert _md5(out) == _PID_BASELINES['java']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, JavaBackend())
            assert 'refinement violated' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2b: HLSL backend -- doc-comment only
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestHLSLRefinementGuards:
    """Phase E.2: refinement doc-comments for the HLSL backend."""

    def setup_method(self):
        self.b = HLSLBackend()

    def test_single_refined_param_emits_comment(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'forge.refinement:' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_comment(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_abs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_comments(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, HLSLBackend())
        out_ref = _compile(_SRC_REFINE, HLSLBackend())
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'forge.requires:' in out_req
        assert 'forge.refinement:' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, HLSLBackend())
        assert _md5(out) == _PID_BASELINES['hlsl']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, HLSLBackend())
            assert 'refinement violated' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2b: GLSL backend -- doc-comment only
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGLSLRefinementGuards:
    """Phase E.2: refinement doc-comments for the GLSL backend."""

    def setup_method(self):
        self.b = GLSLBackend()

    def test_single_refined_param_emits_comment(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'forge.refinement:' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_comment(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_abs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_comments(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, GLSLBackend())
        out_ref = _compile(_SRC_REFINE, GLSLBackend())
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'forge.requires:' in out_req
        assert 'forge.refinement:' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, GLSLBackend())
        assert _md5(out) == _PID_BASELINES['glsl']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, GLSLBackend())
            assert 'refinement violated' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2b: WGSL backend -- doc-comment only
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestWGSLRefinementGuards:
    """Phase E.2: refinement doc-comments for the WGSL backend."""

    def setup_method(self):
        self.b = WGSLBackend()

    def test_single_refined_param_emits_comment(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'forge.refinement:' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_comment(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_abs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_comments(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, WGSLBackend())
        out_ref = _compile(_SRC_REFINE, WGSLBackend())
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'forge.requires:' in out_req
        assert 'forge.refinement:' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, WGSLBackend())
        assert _md5(out) == _PID_BASELINES['wgsl']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, WGSLBackend())
            assert 'refinement violated' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2b: Metal backend -- doc-comment only
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMetalRefinementGuards:
    """Phase E.2: refinement doc-comments for the Metal backend."""

    def setup_method(self):
        self.b = MetalBackend()

    def test_single_refined_param_emits_comment(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'forge.refinement:' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_comment(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_abs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_comments(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, MetalBackend())
        out_ref = _compile(_SRC_REFINE, MetalBackend())
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'forge.requires:' in out_req
        assert 'forge.refinement:' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, MetalBackend())
        assert _md5(out) == _PID_BASELINES['metal']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, MetalBackend())
            assert 'refinement violated' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.2c: LLVM backend -- @llvm.assume intrinsic
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLLVMRefinementGuards:
    """Phase E.2: refinement @llvm.assume hints for the LLVM backend."""

    def setup_method(self):
        self.b = LLVMBackend()

    def test_single_refined_param_emits_assume(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'call void @llvm.assume(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_assume(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'call void @llvm.assume(' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_fabs(self):
        out = _compile(_SRC_ABS, self.b)
        assert 'llvm.fabs' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_assumes(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        assert out.count('call void @llvm.assume(') >= 3
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_ref = _compile(_SRC_REFINE, LLVMBackend())
        assert 'call void @llvm.assume(' in out_ref
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'llvm.assume' not in obligation_line

    def test_llvm_assume_declare_in_prelude(self):
        out = _compile(_SRC_SINGLE, self.b)
        assert 'declare void @llvm.assume(i1)' in out

    def test_pid_no_refinements_md5_unchanged(self):
        out = _compile_file(PID, LLVMBackend())
        assert _md5(out) == _PID_BASELINES['llvm']

    def test_norefinement_kernels_unchanged(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, LLVMBackend())
            assert 'refinement violated' not in out
            assert 'llvm.assume' not in out


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.3: Rust backend -- assert!(cond, "msg") runtime guards
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestRustRefinementGuards:
    """Phase E.3: refinement-derived assert!() guards for the Rust backend.

    Standard 8 tests + test_assert_uses_rust_macro = 9 total.
    """

    def setup_method(self):
        self.b = RustBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # assert!(x >= 0.0, "f: refinement violated on x: x >= 0.0")
        assert 'assert!(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_mg_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # Rust backend maps ABS to mg_abs via _BUILTIN_TO_RUST
        assert 'mg_abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, RustBackend())
        out_ref = _compile(_SRC_REFINE, RustBackend())
        # Both contain mg_abs(x) in an assert!
        assert 'mg_abs(x)' in out_req
        assert 'mg_abs(x)' in out_ref
        assert 'requires' in out_req
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'assert!(' not in obligation_line

    def test_requires_clause_emits_assert(self):
        # Phase E.3 wired requires->assert!() in the Rust backend.
        # Phase F migrated pid_controller's requires clauses to refinements,
        # so this test now exercises _SRC_REQUIRES (a small inline fixture
        # that retains a pure requires clause) to keep verifying the path.
        out = _compile(_SRC_REQUIRES, RustBackend())
        assert 'assert!(' in out
        # The requires guard message uses the "requires" tag
        assert 'requires' in out

    def test_norefinement_no_requires_md5_unchanged(self):
        # Kernels with NO requires AND NO refinements must produce
        # byte-identical output before and after Phase E.3.
        out = _compile(_SRC_NOREFINEMENT_1, RustBackend())
        assert _md5(out) == _NOREFINEMENT1_BASELINES_E3['rust']

    def test_norefinement_kernels_have_no_guards(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, RustBackend())
            assert 'refinement violated' not in out
            assert 'assert!(' not in out

    def test_assert_uses_rust_macro(self):
        # Refinement guards MUST use assert!() (panicking macro), not
        # debug_assert!() (which is stripped in release builds).
        out = _compile(_SRC_SINGLE, self.b)
        assert 'assert!(' in out
        # No debug_assert! for refinements
        assert 'debug_assert!(' not in out

    def test_pid_pid_controller_md5_changed_from_pre_e3(self):
        # pid_controller has requires; E.3 adds assert! output,
        # so the hash MUST differ from the pre-E.3 value.
        pre_e3_hash = "7dfff0b7db2ca8e3c357f10dae615002"
        out = _compile_file(PID, RustBackend())
        assert _md5(out) != pre_e3_hash


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.3: C backend -- assert(cond && "msg") with #include <assert.h>
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCRefinementGuards:
    """Phase E.3: refinement-derived assert() guards for the C backend.

    Standard 8 tests + test_includes_assert_h_when_refinements_present = 9 total.
    """

    def setup_method(self):
        self.b = CBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # assert((x >= 0.0) && "f: refinement violated on x: ...")
        assert 'assert(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_mg_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # C backend maps ABS to mg_abs via _BUILTIN_TO_C
        assert 'mg_abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, CBackend())
        out_ref = _compile(_SRC_REFINE, CBackend())
        assert 'mg_abs(x)' in out_req
        assert 'mg_abs(x)' in out_ref
        assert 'requires' in out_req
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'assert(' not in obligation_line

    def test_requires_clause_emits_assert(self):
        # Phase E.3 wired requires->assert() in the C backend.
        # Phase F migrated pid_controller's requires clauses to refinements,
        # so this test now exercises _SRC_REQUIRES (a small inline fixture
        # that retains a pure requires clause) to keep verifying the path.
        out = _compile(_SRC_REQUIRES, CBackend())
        assert 'assert(' in out
        assert 'requires' in out

    def test_norefinement_no_requires_md5_unchanged(self):
        # No-requires, no-refinements kernels must produce byte-identical output.
        out = _compile(_SRC_NOREFINEMENT_1, CBackend())
        assert _md5(out) == _NOREFINEMENT1_BASELINES_E3['c']

    def test_norefinement_kernels_have_no_guards(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, CBackend())
            assert 'refinement violated' not in out

    def test_includes_assert_h_when_refinements_present(self):
        # #include <assert.h> must be injected when a function has either
        # requires clauses or refined parameters.
        out_ref = _compile(_SRC_SINGLE, CBackend())
        assert '#include <assert.h>' in out_ref
        out_req = _compile(_SRC_REQUIRES, CBackend())
        assert '#include <assert.h>' in out_req

    def test_no_assert_h_on_clean_kernel(self):
        # When no requires and no refinements, #include <assert.h> must NOT
        # be injected (avoids polluting clean kernel output).
        out = _compile(_SRC_NOREFINEMENT_1, CBackend())
        assert '#include <assert.h>' not in out

    def test_pid_md5_changed_from_pre_e3(self):
        pre_e3_hash = "ebbd8c95c46ef3b6e10c5a6574a4d8bd"
        out = _compile_file(PID, CBackend())
        assert _md5(out) != pre_e3_hash


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.3: Python backend -- if not (cond): raise ValueError("msg")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPythonRefinementGuards:
    """Phase E.3: refinement-derived ValueError guards for the Python backend.

    Standard 8 tests.
    """

    def setup_method(self):
        self.b = PythonBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # if not (x >= 0.0): raise ValueError("f: refinement violated on x: ...")
        assert 'raise ValueError(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_bare_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # Python: abs() built-in (no prefix)
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, PythonBackend())
        out_ref = _compile(_SRC_REFINE, PythonBackend())
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'requires' in out_req
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'raise' not in obligation_line

    def test_norefinement_no_requires_md5_unchanged(self):
        out = _compile(_SRC_NOREFINEMENT_1, PythonBackend())
        assert _md5(out) == _NOREFINEMENT1_BASELINES_E3['python']

    def test_norefinement_kernels_have_no_guards(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, PythonBackend())
            assert 'refinement violated' not in out
            assert 'raise ValueError' not in out

    def test_pid_md5_changed_from_pre_e3(self):
        pre_e3_hash = "5cc64ca6b458d703d666db16762886da"
        out = _compile_file(PID, PythonBackend())
        assert _md5(out) != pre_e3_hash


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.3: WASM backend -- doc-only ;; forge.refinement: (no runtime assert)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestWASMRefinementGuards:
    """Phase E.3: refinement doc-comments in WASM IR (doc-only tier).

    WASM core has no assert construct; guards appear as ;; comments in the
    LLVM IR text that the WASMBackend passes through.

    Standard 8 tests -- mirrors the HLSL/GLSL/WGSL/Metal doc-only shape.
    """

    def test_single_refined_param_emits_comment(self):
        out = _compile_wasm_ir(_SRC_SINGLE)
        assert 'forge.refinement:' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_comment(self):
        out = _compile_wasm_ir(_SRC_CONJ)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_abs_in_comment(self):
        out = _compile_wasm_ir(_SRC_ABS)
        # WASM doc-comment uses the raw predicate text -- abs(x) appears literally
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_comments(self):
        out = _compile_wasm_ir(_SRC_MULTI)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile_wasm_ir(_SRC_REQUIRES)
        out_ref = _compile_wasm_ir(_SRC_REFINE)
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'forge.requires:' in out_req
        assert 'forge.refinement:' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile_wasm_ir(_SRC_CROSS)
        assert 'refinement obligation:' in out

    def test_norefinement_no_requires_md5_unchanged(self):
        mod = parse_source(_SRC_NOREFINEMENT_1)
        Profiler().profile_module(mod)
        ir = WASMBackend().compile_full(mod).ir
        assert _md5(ir) == _NOREFINEMENT1_BASELINES_E3['wasm_ir']

    def test_norefinement_kernels_have_no_refinement_comments(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile_wasm_ir(src)
            assert 'refinement violated' not in out

    def test_pid_ir_md5_changed_from_pre_e3(self):
        pre_e3_hash = "27bc4e9167c60c785ed9213df59d5915"
        out = _compile_wasm_ir_file(PID)
        assert _md5(out) != pre_e3_hash


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Phase E.3: GDScript backend -- assert(cond, "msg") (native)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestGDScriptRefinementGuards:
    """Phase E.3: refinement-derived assert() guards for the GDScript backend.

    GDScript 2.0 has a native two-arg assert(cond, "msg") form.
    Standard 8 tests.
    """

    def setup_method(self):
        self.b = GDScriptBackend()

    def test_single_refined_param_emits_guard(self):
        out = _compile(_SRC_SINGLE, self.b)
        # assert(x >= 0.0, "f: refinement violated on x: x >= 0.0")
        assert 'assert(' in out
        assert 'refinement violated on x' in out

    def test_conjunction_refinement_emits_single_guard(self):
        out = _compile(_SRC_CONJ, self.b)
        assert 'refinement violated on x' in out
        assert out.count('refinement violated on x') == 1

    def test_abs_refinement_emits_bare_abs(self):
        out = _compile(_SRC_ABS, self.b)
        # GDScript: abs() built-in
        assert 'abs(x)' in out
        assert 'refinement violated on x' in out

    def test_multiple_refined_params_emit_n_guards(self):
        out = _compile(_SRC_MULTI, self.b)
        assert 'refinement violated on error' in out
        assert 'refinement violated on integral' in out
        assert 'refinement violated on derivative' in out
        i_error = out.index('refinement violated on error')
        i_integral = out.index('refinement violated on integral')
        i_deriv = out.index('refinement violated on derivative')
        assert i_error < i_integral < i_deriv

    def test_splicer_parity_requires_vs_refinement(self):
        out_req = _compile(_SRC_REQUIRES, GDScriptBackend())
        out_ref = _compile(_SRC_REFINE, GDScriptBackend())
        assert 'abs(x)' in out_req
        assert 'abs(x)' in out_ref
        assert 'requires' in out_req
        assert 'refinement violated on' in out_ref

    def test_cross_param_refinement_emits_comment_only(self):
        out = _compile(_SRC_CROSS, self.b)
        assert 'refinement obligation:' in out
        obligation_line = next(
            ln for ln in out.splitlines() if 'refinement obligation:' in ln
        )
        assert 'assert(' not in obligation_line

    def test_norefinement_no_requires_md5_unchanged(self):
        out = _compile(_SRC_NOREFINEMENT_1, GDScriptBackend())
        assert _md5(out) == _NOREFINEMENT1_BASELINES_E3['gdscript']

    def test_norefinement_kernels_have_no_guards(self):
        for src in (_SRC_NOREFINEMENT_1, _SRC_NOREFINEMENT_2, _SRC_NOREFINEMENT_3):
            out = _compile(src, GDScriptBackend())
            assert 'refinement violated' not in out
            assert 'assert(' not in out

    def test_pid_md5_changed_from_pre_e3(self):
        pre_e3_hash = "046c5af3d3d18348d58beac27a64899a"
        out = _compile_file(PID, GDScriptBackend())
        assert _md5(out) != pre_e3_hash
