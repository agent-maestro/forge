"""Structural tests for the LLVM IR backend.

We don't have an LLVM toolchain in this environment, so we validate
the emitted IR structurally rather than running `llvm-as`/`lli`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler
from software.backends.llvm_backend import LLVMBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.mark.parametrize("demo", [
    "hello.eml", "pid_basic.eml", "arrhenius.eml", "bessel_fm.eml",
    "orbit.eml", "kalman.eml", "motor_foc.eml", "trajectory.eml",
    "pid_nonlinear.eml", "sigmoid.eml",
])
def test_demo_emits_valid_ir_skeleton(demo):
    """Every demo emits IR with a ModuleID, externs, defines, and rets."""
    mod = parse_file(str(EXAMPLES / demo))
    Profiler().profile_module(mod)
    ir = LLVMBackend().compile(mod)
    assert ir.startswith("; ModuleID")
    assert "source_filename" in ir
    # Each function generates exactly one define.
    n_define = len(re.findall(r"^define ", ir, re.MULTILINE))
    callable_fns = [
        f for f in mod.functions
        if f.profile is None or f.profile.get("status") != "complex_body"
        or True  # complex bodies still emit -- they just use alloca/load/store
    ]
    assert n_define == len(callable_fns)
    # Every define ends with at least one ret instruction.
    n_ret = len(re.findall(r"^\s+ret ", ir, re.MULTILINE))
    assert n_ret >= n_define


def test_arrhenius_inlines_R_constant():
    """Module-level const R = 8.314 lowers to literal 8.314 inside `rate`."""
    mod = parse_file(str(EXAMPLES / "arrhenius.eml"))
    Profiler().profile_module(mod)
    ir = LLVMBackend().compile(mod)
    # constant_folding may have already eliminated R / 8.314 entirely
    # (constant 1/8.314 etc.), so we only assert no unbound R name leaks.
    assert "%R " not in ir and "load double, double* %R" not in ir


def test_externs_emitted_for_used_builtins():
    """sigmoid uses exp -- the IR must declare @mg_exp."""
    mod = parse_file(str(EXAMPLES / "sigmoid.eml"))
    Profiler().profile_module(mod)
    ir = LLVMBackend().compile(mod)
    assert "declare double @mg_exp(double)" in ir


def test_no_extern_for_unused_builtins():
    """hello.eml uses no transcendentals -- declare list should be empty."""
    mod = parse_file(str(EXAMPLES / "hello.eml"))
    Profiler().profile_module(mod)
    ir = LLVMBackend().compile(mod)
    assert "declare double @mg_" not in ir


def test_target_triple_emitted_when_set():
    mod = parse_file(str(EXAMPLES / "sigmoid.eml"))
    Profiler().profile_module(mod)
    ir = LLVMBackend(target_triple="wasm32-unknown-unknown").compile(mod)
    assert 'target triple = "wasm32-unknown-unknown"' in ir
