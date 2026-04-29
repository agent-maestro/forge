"""Tests for the C99 backend (`software.backends.c_backend`)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.c_backend import CBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"
RUNTIME_C_DIR = REPO_ROOT / "software" / "runtime" / "c"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> CBackend:
    return CBackend()


def _profile_and_compile(filename: str, profiler: Profiler,
                         backend: CBackend) -> str:
    mod = parse_file(EXAMPLES_DIR / filename)
    profiler.profile_module(mod)
    return backend.compile(mod)


# ── All demo files compile to C without raising ─────────────────────


@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_demo_compiles_to_c(filename: str, profiler: Profiler,
                            backend: CBackend) -> None:
    out = _profile_and_compile(filename, profiler, backend)
    # Sanity: must include the runtime header and at least one function.
    assert '#include "libmonogate.h"' in out
    # Every demo file produces at least one C function definition
    assert ") {" in out and "}" in out


# ── Specific structural expectations ────────────────────────────────


def test_hello_emits_constant_return(profiler: Profiler, backend: CBackend):
    out = _profile_and_compile("hello.eml", profiler, backend)
    assert "double answer(void)" in out
    assert "return 42.0;" in out


def test_pid_basic_emits_module_constants(profiler: Profiler,
                                          backend: CBackend):
    out = _profile_and_compile("pid_basic.eml", profiler, backend)
    assert "static const double Kp = 0.5;" in out
    assert "static const double Ki = 0.1;" in out
    assert "static const double Kd = 0.05;" in out


def test_arrhenius_dispatches_exp_to_mg_exp(profiler: Profiler,
                                            backend: CBackend):
    out = _profile_and_compile("arrhenius.eml", profiler, backend)
    assert "mg_exp(" in out
    # Arrhenius rate has a unary minus on -Ea
    assert "(-Ea)" in out


def test_motor_foc_emits_tuple_struct(profiler: Profiler,
                                      backend: CBackend):
    out = _profile_and_compile("motor_foc.eml", profiler, backend)
    assert "typedef struct { double e0; double e1; } park_result_t;" in out
    assert "park_result_t park(" in out
    # Compound literal cast on the return
    assert "return (park_result_t){" in out


def test_orbit_emits_while_and_mut(profiler: Profiler, backend: CBackend):
    out = _profile_and_compile("orbit.eml", profiler, backend)
    assert "while (" in out
    # `let mut E = M;` becomes a plain double declaration in C
    assert "double E = M;" in out
    # The bare assignment `E = E - f / fp;` should appear
    assert "E = " in out


def test_motor_control_emits_six_functions(profiler: Profiler,
                                           backend: CBackend):
    out = _profile_and_compile("motor_control.eml", profiler, backend)
    for fn_name in ("pid_output", "damped_response", "motor_torque",
                    "unstable_gain", "realtime_control", "safe_pid"):
        assert f" {fn_name}(" in out, f"missing function {fn_name}"


def test_complex_body_function_still_emits_valid_c(profiler: Profiler,
                                                   backend: CBackend):
    """orbit.eml's kepler_solve has complex_body status. The C
    backend should still emit the body (since the AST parses); the
    profile comment just notes it as COMPLEX BODY."""
    out = _profile_and_compile("orbit.eml", profiler, backend)
    assert "COMPLEX BODY" in out
    # And the body still exists
    assert "kepler_solve(" in out


def test_profile_comment_includes_chain_order(profiler: Profiler,
                                              backend: CBackend):
    out = _profile_and_compile("motor_control.eml", profiler, backend)
    # damped_response should be tagged with chain_order 3
    assert "Chain order: 3" in out


def test_call_to_user_function_passes_through(profiler: Profiler):
    """motor_control's safe_pid calls pid_output. Verify the CALL
    survives in the emitted C when optimization is disabled --
    the inliner pass would otherwise substitute pid_output's body
    in place. We disable optimize here because this test is
    specifically about the CALL-emission code path."""
    raw = CBackend(optimize=False)
    out = _profile_and_compile("motor_control.eml", profiler, raw)
    assert "pid_output(error" in out


def test_unsupported_node_kind_raises():
    """Synthesizing a NodeKind the backend doesn't know about should
    raise CompileError, not silently emit garbage."""
    from lang.parser.ast_nodes import ASTNode, NodeKind
    from software.backends.c_backend import CBackend, CompileError
    bad = ASTNode(kind=NodeKind.BLOCK)  # blocks aren't expressions
    with pytest.raises(CompileError):
        CBackend()._emit_expr(bad)


# ── Optional integration test: invoke gcc if available ──────────────


def _gcc_available() -> bool:
    return shutil.which("gcc") is not None


@pytest.mark.skipif(not _gcc_available(), reason="gcc not on PATH")
@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_generated_c_compiles_with_gcc(
    filename: str, profiler: Profiler, backend: CBackend,
) -> None:
    """When gcc is available, the generated C must compile cleanly
    against software/runtime/c/libmonogate.h with -Wall -Werror."""
    out = _profile_and_compile(filename, profiler, backend)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        c_file = tmp_path / "out.c"
        c_file.write_text(out, encoding="utf-8")
        # libmonogate.c is needed because some functions are extern.
        result = subprocess.run(
            ["gcc", "-c", "-Wall", "-Werror",
             f"-I{RUNTIME_C_DIR}",
             "-o", str(tmp_path / "out.o"),
             str(c_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"gcc rejected generated C from {filename}:\n"
            f"--- STDERR ---\n{result.stderr}\n"
            f"--- SOURCE ---\n{out[:2000]}"
        )
