"""Smoke tests for the Python backend."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from lang.parser.parser import parse_file, parse_source
from lang.profiler.profiler import Profiler
from software.backends.python_backend import PythonBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


# Demos whose body the SymPy bridge can fully express -- numerical
# equivalence matters here.
SCALAR_DEMOS = [
    ("sigmoid.eml",   "sigmoid",    (1.0,),                 1.0 / (1.0 + math.exp(-1.0))),
    ("arrhenius.eml", "rate",       (1.0e7, 50000.0, 300.0),
        1.0e7 * math.exp(-50000.0 / (8.314 * 300.0))),
]


@pytest.mark.parametrize("demo", [
    "hello.eml", "pid_basic.eml", "arrhenius.eml", "bessel_fm.eml",
    "orbit.eml", "kalman.eml", "motor_foc.eml", "trajectory.eml",
    "pid_nonlinear.eml", "sigmoid.eml",
])
def test_demo_compiles_and_imports(demo):
    """Every demo .eml compiles to Python that exec's without error."""
    mod = parse_file(str(EXAMPLES / demo))
    Profiler().profile_module(mod)
    src = PythonBackend().compile(mod)
    ns: dict = {}
    exec(compile(src, demo, "exec"), ns)
    # Every fn the parser saw must be callable in the resulting ns.
    for fn in mod.functions:
        assert fn.name in ns, f"{fn.name} missing from generated module"
        assert callable(ns[fn.name])


@pytest.mark.parametrize("demo,fn,args,expected", SCALAR_DEMOS)
def test_scalar_demo_matches_reference(demo, fn, args, expected):
    """Generated Python source produces the same value as math.* would."""
    mod = parse_file(str(EXAMPLES / demo))
    Profiler().profile_module(mod)
    src = PythonBackend().compile(mod)
    ns: dict = {}
    exec(compile(src, demo, "exec"), ns)
    got = ns[fn](*args)
    assert math.isclose(got, expected, rel_tol=1e-12, abs_tol=1e-12), (
        f"{demo}::{fn}({args}) = {got!r}, expected {expected!r}"
    )


def test_no_optimize_flag():
    """optimize=False bypasses the optimizer and still produces clean source."""
    mod = parse_file(str(EXAMPLES / "sigmoid.eml"))
    Profiler().profile_module(mod)
    src = PythonBackend(optimize=False).compile(mod)
    ns: dict = {}
    exec(compile(src, "sigmoid_noopt", "exec"), ns)
    assert math.isclose(
        ns["sigmoid"](1.0),
        1.0 / (1.0 + math.exp(-1.0)),
        rel_tol=1e-12,
    )


def test_rebound_let_shadow_chain_compiles_with_optimizer_enabled():
    """Loop-unrolled EML may shadow an immutable let name repeatedly.
    The optimizer must preserve those sequencing boundaries."""
    mod = parse_source("""\
fn poly4(x: Real, c0: Real) -> Real
    where chain_order <= 0
{
    let acc = 0.0;
    let acc = acc * x + c0;
    let acc = acc * x + c0;
    let acc = acc * x + c0;
    let acc = acc * x + c0;
    let acc = acc * x + c0;
    acc
}
""")
    Profiler().profile_module(mod)
    src = PythonBackend().compile(mod)
    ns: dict = {}
    exec(compile(src, "poly4_shadow", "exec"), ns)
    assert math.isclose(ns["poly4"](2.0, 3.0), 93.0, rel_tol=1e-12)
