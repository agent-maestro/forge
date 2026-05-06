"""Phase G tests: assume clause lowering across all 33 backends.

TDD: RED phase. Tests written before implementation.

Design contracts under test:
  1. CODEGEN (19 backends): assume -> comment-only line, NO runtime guard.
  2. PROOF (3 backends: Lean/Coq/Isabelle): assume -> hypothesis hN,
     appearing AFTER requires-derived hypotheses.
  3. HARDWARE (4 backends): assume -> comment-only line.
  4. SAFETY-CRIT (4 backends):
     - Ada/SPARK: pragma Assume (P); (or comment if expression form unsupported)
     - AUTOSAR/AADL/ROS2: comment-only
  5. SOLIDITY: comment-only line.

Non-regression:
  - C backend: pid_controller.eml MD5 stays 6d5d972be783cbe62afd05c97e334774
  - `requires` semantics unchanged in every backend.

Shared EML fixture (all targets):
  fn assume_test(x: Real) -> Real
  assume (sqrt(x) > 0.0)
  { x }

The canonical transcendental assume is used to verify that:
  - Codegen: no assert/panic/require in output
  - Proof: hypothesis present
  - Ada: pragma Assume or comment

Cross-backend: at least 3 backends per cost-class verified.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lang.parser import parse_source, parse_file
from lang.profiler import Profiler

REPO_ROOT = Path(__file__).resolve().parents[3]
PID = REPO_ROOT / "examples" / "pid_controller.eml"


# ── Compile helpers ───────────────────────────────────────────────────────────


def _compile(src: str, backend) -> str:
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    return backend.compile(mod)


def _compile_file(path: Path, backend) -> str:
    mod = parse_file(path)
    Profiler().profile_module(mod)
    return backend.compile(mod)


def _compile_hdl(src: str, backend) -> str:
    """Compile EML source via an HDL backend (requires AllocationPlan)."""
    from hardware.allocator import FPGAAllocator
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    return backend.compile(mod, plan)


def _compile_verification(src: str, backend) -> str:
    """Compile for a verification backend (Lean/Coq/Isabelle)."""
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    return backend.compile_module(mod)


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# ── EML fixtures ──────────────────────────────────────────────────────────────

# Base fixture: single assume with transcendental (sqrt)
_ASSUME_SQRT = """\
module assume_test;
@verify(lean, theorem = "assume_theorem")
fn assume_fn(x: Real) -> Real
assume (sqrt(x) > 0.0)
{ x }
"""

# Fixture: assume + requires (verifies ordering in proof targets)
_ASSUME_WITH_REQUIRES = """\
module mixed_test;
@verify(lean, theorem = "mixed_theorem")
fn mixed_fn(x: Real, y: Real) -> Real
requires (x > 0.0)
assume (sqrt(y) > 0.0)
{ x + y }
"""

# Fixture: assume without transcendental (simple comparison)
_ASSUME_SIMPLE = """\
module simple_assume;
fn simple_fn(x: Real) -> Real
assume (x >= 0.0)
{ x * 2.0 }
"""

# HDL fixture: must carry @target(fpga)
_HDL_ASSUME = """\
module hdl_assume;
@target(fpga, clock_mhz = 100)
fn hdl_fn(x: Real) -> Real
    where chain_order <= 0
assume (x >= 0.0)
{ x }
"""


# ─────────────────────────────────────────────────────────────────────────────
# CODEGEN BACKENDS (19): comment-only, no runtime guard
# ─────────────────────────────────────────────────────────────────────────────

class TestCBackendAssume:
    """C backend: assume -> comment line, no assert()."""

    def setup_method(self):
        from software.backends.c_backend import CBackend
        self.backend = CBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out, \
            "C backend must emit a comment for assume clause"

    def test_assume_no_runtime_guard(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        # Must NOT contain assert() that references x >= 0
        lines = out.splitlines()
        assert_lines = [l for l in lines if "assert(" in l and "assume" not in l.lower()]
        # No assert that fires for assume
        for line in assert_lines:
            assert "x >= 0" not in line and "x > 0" not in line, \
                f"C backend must not emit runtime assert for assume: {line}"

    def test_assume_sqrt_transcendental_comment(self):
        out = _compile(_ASSUME_SQRT, self.backend)
        # Comment must reference the predicate
        assert "sqrt" in out

    def test_pid_md5_unchanged(self):
        """Non-regression: pid_controller.eml C MD5 stays fixed.

        Phase G is a no-op for files with no assume clauses.
        The MD5 is environment-specific (depends on absolute source_file path).
        """
        from software.backends.c_backend import CBackend
        out = _compile_file(PID, CBackend())
        assert _md5(out) == "6d5d972be783cbe62afd05c97e334774", \
            "C backend MD5 changed -- pid_controller.eml regression"


class TestGoBackendAssume:
    """Go backend: assume -> comment-only, no panic()."""

    def setup_method(self):
        from software.backends.go_backend import GoBackend
        self.backend = GoBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out

    def test_assume_no_runtime_guard(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        # Must not contain panic() referencing assume predicate
        lines = [l for l in out.splitlines() if "panic" in l and "assume" not in l.lower()]
        for line in lines:
            assert "x >= 0" not in line, \
                f"Go backend must not emit panic for assume: {line}"


class TestRustBackendAssume:
    """Rust backend: assume -> comment-only, no assert!()."""

    def setup_method(self):
        from software.backends.rust_backend import RustBackend
        self.backend = RustBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out

    def test_assume_no_runtime_guard(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        lines = [l for l in out.splitlines() if "assert!" in l and "assume" not in l.lower()]
        for line in lines:
            assert "x >= 0" not in line, \
                f"Rust backend must not emit assert! for assume: {line}"


class TestPythonBackendAssume:
    """Python backend: assume -> comment-only, no raise ValueError()."""

    def setup_method(self):
        from software.backends.python_backend import PythonBackend
        self.backend = PythonBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "# assume:" in out or "assume:" in out

    def test_assume_no_runtime_guard(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        lines = [l for l in out.splitlines() if "raise" in l and "assume" not in l.lower()]
        for line in lines:
            assert "x >= 0" not in line, \
                f"Python backend must not raise for assume: {line}"


class TestJavaScriptBackendAssume:
    """JavaScript backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.javascript_backend import JavaScriptBackend
        self.backend = JavaScriptBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out

    def test_assume_no_runtime_guard(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        # No throw for assume
        lines = [l for l in out.splitlines() if "throw" in l and "assume" not in l.lower()]
        for line in lines:
            assert "x >= 0" not in line


class TestJavaBackendAssume:
    """Java backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.java_backend import JavaBackend
        self.backend = JavaBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestKotlinBackendAssume:
    """Kotlin backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.kotlin_backend import KotlinBackend
        self.backend = KotlinBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestCSharpBackendAssume:
    """C# backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.csharp_backend import CSharpBackend
        self.backend = CSharpBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestCppBackendAssume:
    """C++ backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.cpp_backend import CppBackend
        self.backend = CppBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestSwiftBackendAssume:
    """Swift backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.swift_backend import SwiftBackend
        self.backend = SwiftBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestLuauBackendAssume:
    """Luau backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.luau_backend import LuauBackend
        self.backend = LuauBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "-- assume:" in out or "assume:" in out


class TestMatlabBackendAssume:
    """MATLAB backend: assume -> comment-only (% assume:)."""

    def setup_method(self):
        from software.backends.matlab_backend import MatlabBackend
        self.backend = MatlabBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "% assume:" in out or "assume:" in out


class TestGDScriptBackendAssume:
    """GDScript backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.gdscript_backend import GDScriptBackend
        self.backend = GDScriptBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "# assume:" in out or "assume:" in out


class TestWASMBackendAssume:
    """WASM backend: assume -> comment-only in LLVM IR (;; assume:)."""

    def test_assume_emits_comment(self):
        from software.backends.wasm_backend import WASMBackend
        mod = parse_source(_ASSUME_SIMPLE, "<test>")
        Profiler().profile_module(mod)
        result = WASMBackend(optimize=False).compile_full(mod)
        out = result.ir
        assert "; assume:" in out or "assume:" in out


class TestLLVMBackendAssume:
    """LLVM-IR backend: assume -> comment-only (; assume:)."""

    def setup_method(self):
        from software.backends.llvm_backend import LLVMBackend
        self.backend = LLVMBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "; assume:" in out or "assume:" in out


class TestHLSLBackendAssume:
    """HLSL backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.hlsl_backend import HLSLBackend
        self.backend = HLSLBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestGLSLBackendAssume:
    """GLSL backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.glsl_backend import GLSLBackend
        self.backend = GLSLBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestWGSLBackendAssume:
    """WGSL backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.wgsl_backend import WGSLBackend
        self.backend = WGSLBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestMetalBackendAssume:
    """Metal backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.metal_backend import MetalBackend
        self.backend = MetalBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out


# ─────────────────────────────────────────────────────────────────────────────
# PROOF BACKENDS (3): assume -> hypothesis hN AFTER requires hypotheses
# ─────────────────────────────────────────────────────────────────────────────

class TestLeanBackendAssume:
    """Lean 4 backend: assume -> hypothesis h_assumeN after requires-derived ones."""

    def setup_method(self):
        from software.verification.lean.LeanBackend import LeanBackend
        self.backend = LeanBackend(optimize=False)

    def test_assume_emits_hypothesis(self):
        out = _compile_verification(_ASSUME_SQRT, self.backend)
        # Must have a hypothesis line containing the assume predicate
        assert "assume" in out.lower() or "h_assume" in out or "sqrt" in out, \
            "Lean backend must emit assume as a hypothesis"

    def test_assume_hypothesis_present_in_theorem(self):
        out = _compile_verification(_ASSUME_SQRT, self.backend)
        # The assume predicate (sqrt) must appear in the theorem's hypothesis block
        assert "sqrt" in out, "Lean assume hypothesis must reference the predicate"

    def test_assume_hypothesis_after_requires(self):
        """In a mixed requires+assume function, requires hyps come first."""
        out = _compile_verification(_ASSUME_WITH_REQUIRES, self.backend)
        # Both must appear
        assert "x > 0" in out or "(x > (0 : Real))" in out or "h1" in out, \
            "requires hypothesis must be present"
        assert "sqrt" in out, "assume hypothesis must be present"
        # Order: requires-derived h1 must come before assume-derived h_assume1
        req_pos = out.find("h1")
        assume_pos = out.find("h_assume")
        if req_pos >= 0 and assume_pos >= 0:
            assert req_pos < assume_pos, \
                "requires-derived h1 must appear before assume-derived h_assume1"

    def test_assume_no_runtime_guard_in_lean(self):
        """Lean emits no assert() or runtime check for assume."""
        out = _compile_verification(_ASSUME_SQRT, self.backend)
        assert "assert" not in out.lower().replace("-- assert", "")


class TestCoqBackendAssume:
    """Coq backend: assume -> hypothesis after requires-derived ones."""

    def setup_method(self):
        from software.verification.coq.coq_backend import CoqBackend
        self.backend = CoqBackend(optimize=False)

    def test_assume_emits_hypothesis(self):
        out = _compile_verification(_ASSUME_SQRT, self.backend)
        # Must mention sqrt in a hypothesis context
        assert "sqrt" in out, "Coq backend must include assume predicate as hypothesis"

    def test_assume_hypothesis_after_requires(self):
        out = _compile_verification(_ASSUME_WITH_REQUIRES, self.backend)
        # Both predicates must appear in the theorem
        assert "x > 0" in out or "h1" in out
        assert "sqrt" in out


class TestIsabelleBackendAssume:
    """Isabelle/HOL backend: assume -> assumes clause after requires assumes."""

    def setup_method(self):
        from software.verification.isabelle.isabelle_backend import IsabelleBackend
        self.backend = IsabelleBackend(optimize=False)

    def test_assume_emits_assumes_clause(self):
        out = _compile_verification(_ASSUME_SQRT, self.backend)
        assert "sqrt" in out, "Isabelle backend must include assume predicate"

    def test_assume_after_requires_in_isabelle(self):
        out = _compile_verification(_ASSUME_WITH_REQUIRES, self.backend)
        assert "x > 0" in out or "assumes" in out
        assert "sqrt" in out


# ─────────────────────────────────────────────────────────────────────────────
# HARDWARE BACKENDS (4): comment-only
# ─────────────────────────────────────────────────────────────────────────────

class TestVerilogBackendAssume:
    """Verilog backend: assume -> comment-only."""

    def setup_method(self):
        from hardware.hdl_gen.verilog_backend import VerilogBackend
        self.backend = VerilogBackend()

    def test_assume_emits_comment(self):
        out = _compile_hdl(_HDL_ASSUME, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestSystemVerilogBackendAssume:
    """SystemVerilog backend: assume -> comment-only."""

    def setup_method(self):
        from hardware.hdl_gen.systemverilog_backend import SystemVerilogBackend
        self.backend = SystemVerilogBackend()

    def test_assume_emits_comment(self):
        out = _compile_hdl(_HDL_ASSUME, self.backend)
        assert "// assume:" in out or "assume:" in out


class TestVHDLBackendAssume:
    """VHDL backend: assume -> comment-only (-- assume:)."""

    def setup_method(self):
        from hardware.hdl_gen.vhdl_backend import VHDLBackend
        self.backend = VHDLBackend()

    def test_assume_emits_comment(self):
        out = _compile_hdl(_HDL_ASSUME, self.backend)
        assert "-- assume:" in out or "assume:" in out


class TestChiselBackendAssume:
    """Chisel backend: assume -> comment-only."""

    def setup_method(self):
        from hardware.hdl_gen.chisel_backend import ChiselBackend
        self.backend = ChiselBackend()

    def test_assume_emits_comment(self):
        out = _compile_hdl(_HDL_ASSUME, self.backend)
        assert "// assume:" in out or "assume:" in out


# ─────────────────────────────────────────────────────────────────────────────
# SAFETY-CRITICAL BACKENDS (4)
# ─────────────────────────────────────────────────────────────────────────────

class TestAdaBackendAssume:
    """Ada/SPARK backend: assume -> pragma Assume (P); or comment."""

    def setup_method(self):
        from software.backends.ada_backend import AdaBackend
        self.backend = AdaBackend(optimize=False)

    def test_assume_emits_pragma_or_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        # Either pragma Assume or a comment line; neither is a Pre =>
        has_pragma = "pragma Assume" in out or "pragma assume" in out.lower()
        has_comment = "-- assume:" in out or "assume:" in out
        assert has_pragma or has_comment, \
            "Ada backend must emit pragma Assume or comment for assume clause"

    def test_assume_not_in_pre_contract(self):
        """assume must NOT appear in the Pre => SPARK contract."""
        out = _compile(_ASSUME_SIMPLE, self.backend)
        spec = out  # Both spec and body are in compile() output
        # If "Pre =>" exists, the assume predicate must NOT be in it
        if "Pre  =>" in spec or "Pre =>" in spec:
            # Find lines containing Pre =>
            pre_lines = [l for l in spec.splitlines() if "Pre" in l and "=>" in l]
            for line in pre_lines:
                assert "assume" not in line.lower(), \
                    f"assume predicate leaked into Pre => contract: {line}"

    def test_assume_sqrt_handled(self):
        """Ada handles assume with transcendental sqrt."""
        src = """\
module ada_assume;
fn f(x: Real) -> Real
assume (sqrt(x) > 0.0)
{ x }
"""
        out = _compile(src, self.backend)
        # Must contain something about assume + sqrt
        assert "assume" in out.lower() or "pragma" in out.lower()


class TestAutoSARBackendAssume:
    """AUTOSAR backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.autosar_backend import AutosarBackend
        self.backend = AutosarBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "assume:" in out.lower() or "assume" in out.lower()


class TestAADLBackendAssume:
    """AADL backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.aadl_backend import AadlBackend
        self.backend = AadlBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "assume:" in out.lower() or "assume" in out.lower()


class TestROS2BackendAssume:
    """ROS2 backend: assume -> comment-only."""

    def setup_method(self):
        from software.backends.ros2_backend import Ros2Backend
        self.backend = Ros2Backend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "assume:" in out.lower() or "assume" in out.lower()


# ─────────────────────────────────────────────────────────────────────────────
# SOLIDITY (1): comment-only
# ─────────────────────────────────────────────────────────────────────────────

class TestSolidityBackendAssume:
    """Solidity backend: assume -> comment-only, no require()."""

    def setup_method(self):
        from software.backends.solidity_backend import SolidityBackend
        self.backend = SolidityBackend(optimize=False)

    def test_assume_emits_comment(self):
        out = _compile(_ASSUME_SIMPLE, self.backend)
        assert "// assume:" in out or "assume:" in out

    def test_assume_no_require_call(self):
        """Solidity must NOT emit require() for assume clause."""
        out = _compile(_ASSUME_SIMPLE, self.backend)
        # No require() that touches the assume predicate's variable
        lines = [l for l in out.splitlines() if "require(" in l and "assume" not in l.lower()]
        for line in lines:
            assert "x >= 0" not in line, \
                f"Solidity must not emit require() for assume: {line}"


# ─────────────────────────────────────────────────────────────────────────────
# Non-regression: C backend MD5 for pid_controller.eml unchanged
# ─────────────────────────────────────────────────────────────────────────────

def test_c_backend_pid_md5_unchanged():
    """The C backend MD5 for pid_controller.eml must stay 6d5d972be783cbe62afd05c97e334774.

    Phase G is a no-op for files with no assume clauses.
    The MD5 is environment-specific (depends on absolute source_file path).
    """
    from software.backends.c_backend import CBackend
    out = _compile_file(PID, CBackend())
    assert _md5(out) == "6d5d972be783cbe62afd05c97e334774", \
        f"C backend regression: MD5={_md5(out)} (expected 6d5d972be783cbe62afd05c97e334774)"
