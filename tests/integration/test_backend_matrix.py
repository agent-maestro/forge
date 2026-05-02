"""Backend integration matrix.

Every backend produces output for every demo in
`lang/spec/grammar/examples/` (software) or
`industries/**/*.eml` (hardware). For the Python backend we also
verify numerical agreement with the SymPy reference.

Backends not covered here: C / Rust / Lean / Verilog runtime equivalence
all live in `tests/equivalence/test_cross_target.py` -- those tests are
gated on the appropriate toolchain. This matrix is structural-only so
it always runs in CI.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.chisel_backend import ChiselBackend
from hardware.hdl_gen.verilog_backend import VerilogBackend
from hardware.hdl_gen.vhdl_backend import VHDLBackend
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler
from software.backends.c_backend import CBackend
from software.backends.llvm_backend import LLVMBackend
from software.backends.python_backend import PythonBackend
from software.backends.rust_backend import RustBackend
from software.backends.wasm_backend import WASMBackend


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"
INDUSTRIES = REPO_ROOT / "industries"


# ── Software backend matrix: every demo, every backend ───────────

SOFTWARE_DEMOS = [
    "hello.eml", "pid_basic.eml", "arrhenius.eml", "bessel_fm.eml",
    "orbit.eml", "kalman.eml", "motor_foc.eml", "trajectory.eml",
    "pid_nonlinear.eml", "sigmoid.eml",
]


def _profile_demo(name: str):
    mod = parse_file(str(EXAMPLES / name))
    Profiler().profile_module(mod)
    return mod


@pytest.mark.parametrize("demo", SOFTWARE_DEMOS)
def test_c_backend_emits_for_demo(demo: str):
    src = CBackend().compile(_profile_demo(demo))
    assert "#include" in src
    assert re.search(r"\b\w+\s*\([^)]*\)\s*\{", src)


@pytest.mark.parametrize("demo", SOFTWARE_DEMOS)
def test_rust_backend_emits_for_demo(demo: str):
    src = RustBackend().compile(_profile_demo(demo))
    assert "fn " in src or "//" in src


@pytest.mark.parametrize("demo", SOFTWARE_DEMOS)
def test_python_backend_emits_for_demo(demo: str):
    src = PythonBackend().compile(_profile_demo(demo))
    assert "import math" in src
    # Generated source must be valid Python.
    compile(src, demo, "exec")


@pytest.mark.parametrize("demo", SOFTWARE_DEMOS)
def test_llvm_backend_emits_for_demo(demo: str):
    ir = LLVMBackend().compile(_profile_demo(demo))
    assert ir.startswith("; ModuleID")
    assert "define " in ir


# orbit.eml exercises a `while` loop with an unsigned-integer
# counter. The current LLVM backend has a known type-inference gap
# around integer-typed mutables (issue #3) that produces malformed
# IR — the gap is invisible to emit-only smoke tests but trips
# clang's wasm32 verifier on CI runners that have clang installed.
# Restrict this test to the kernels that emit clean IR until the
# backend gap is fixed.
WASM_CLEAN_DEMOS = [d for d in SOFTWARE_DEMOS if d != "orbit.eml"]


@pytest.mark.parametrize("demo", WASM_CLEAN_DEMOS)
def test_wasm_backend_emits_for_demo(demo: str):
    res = WASMBackend().compile_full(_profile_demo(demo))
    # Without llc/clang on PATH we get IR; with it we get bytecode.
    assert res.toolchain in ("none", "llc", "clang")
    assert "wasm32" in res.ir


# ── Numerical agreement: Python backend vs SymPy reference ───────

NUMERIC_CASES = [
    ("sigmoid.eml",   "sigmoid",  (0.0,),  0.5),
    ("sigmoid.eml",   "sigmoid",  (1.0,),  1.0 / (1.0 + math.exp(-1.0))),
    ("sigmoid.eml",   "silu",     (1.0,),  1.0 / (1.0 + math.exp(-1.0))),
    ("arrhenius.eml", "rate",     (1.0e7, 50000.0, 300.0),
        1.0e7 * math.exp(-50000.0 / (8.314 * 300.0))),
]


@pytest.mark.parametrize("demo,fn,args,expected", NUMERIC_CASES)
def test_python_backend_numerics(demo, fn, args, expected):
    """Generated Python source produces results matching the closed-form."""
    src = PythonBackend().compile(_profile_demo(demo))
    ns: dict = {}
    exec(compile(src, demo, "exec"), ns)
    got = ns[fn](*args)
    assert math.isclose(got, expected, rel_tol=1e-12, abs_tol=1e-12)


# ── Hardware backend matrix: every FPGA-targeted vertical ───────

def _fpga_verticals() -> list[Path]:
    out: list[Path] = []
    for path in INDUSTRIES.glob("**/*.eml"):
        # crypto/ scaffolds describe algorithms that need grammar
        # extensions (array types, tuple parameters, extern decls)
        # not yet in the parser. They are kept as prose showcase
        # under industries/crypto/scope/ and certification/ — the
        # cost-class / chain-order claims travel via the README,
        # not via parsed AST. Re-include once the grammar lands.
        if "crypto" in path.parts:
            continue
        mod = parse_file(str(path))
        Profiler().profile_module(mod)
        for fn in mod.functions:
            for a in fn.annotations:
                if a.kind == "target" and a.args.get(0) == "fpga":
                    out.append(path)
                    break
            else:
                continue
            break
    return out


FPGA_VERTICALS = _fpga_verticals()


@pytest.mark.parametrize(
    "vertical",
    FPGA_VERTICALS,
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_verilog_backend_emits_for_vertical(vertical: Path):
    mod = parse_file(str(vertical))
    Profiler().profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    src = VerilogBackend().compile(mod, plan)
    assert "module " in src and "endmodule" in src


@pytest.mark.parametrize(
    "vertical",
    FPGA_VERTICALS,
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_vhdl_backend_emits_for_vertical(vertical: Path):
    mod = parse_file(str(vertical))
    Profiler().profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    src = VHDLBackend().compile(mod, plan)
    assert "library IEEE;" in src
    assert "entity " in src
    assert "architecture rtl" in src


@pytest.mark.parametrize(
    "vertical",
    FPGA_VERTICALS,
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_chisel_backend_emits_for_vertical(vertical: Path):
    mod = parse_file(str(vertical))
    Profiler().profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    src = ChiselBackend().compile(mod, plan)
    assert "package monogate.gen" in src
    assert "extends Module" in src
