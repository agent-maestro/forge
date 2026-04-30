"""Cross-target equivalence for `complex_body` functions.

Phase 2.5 introduced a tree-walking interpreter
(`lang/profiler/eml_interpreter.py`) so the Python reference path
can evaluate functions whose body uses `let mut` / `while` / assign
-- the imperative subset that SymPy's lambdify cannot model.

This test exercises that path end-to-end against the Rust backend
on `orbit.eml::kepler_solve`, the canonical Newton-iteration
example. Bit-exact agreement is the bar; a regression here means
the interpreter has drifted from the runtime semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.equivalence import cross_target_check
from tools.equivalence.rust_runner import cargo_available


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    not cargo_available(),
    reason="cargo / rustc not on PATH",
)
def test_kepler_solve_python_vs_rust_bit_exact() -> None:
    """orbit::kepler_solve runs through the Phase 2.5 interpreter
    on the Python side and through `monogate_sys` on the Rust side.
    The Newton iteration is deterministic; outputs must match in
    every bit.

    Vectors span: zero-eccentricity (trivial), low-e short
    iteration, moderate-e longer iteration. n=u8 forces the
    runner's argument coercion path (Rust signature requires the
    cast to compile).
    """
    report = cross_target_check(
        REPO_ROOT / "lang/spec/grammar/examples/orbit.eml",
        "kepler_solve",
        [
            (0.5, 0.1, 5),
            (1.0, 0.3, 8),
            (0.0, 0.0, 3),
        ],
        targets=("rust",),
    )
    rust = report.targets["rust"]
    assert rust.available, f"rust target unavailable: {rust.error}"
    assert rust.error == "", f"rust target errored: {rust.error}"
    assert rust.max_abs_err == 0.0, (
        f"non-zero divergence Python vs Rust on kepler_solve: "
        f"{rust.max_abs_err}"
    )
    assert report.overall_match


def test_interpreter_handles_kepler_solve_directly() -> None:
    """Smoke test for the interpreter alone -- bypasses the
    cross-target harness so this still runs without a Rust
    toolchain. Verifies the Newton iteration produces a fixed
    point of Kepler's equation (M = E - e * sin(E)) within
    convergence tolerance for a healthy iteration count."""
    from math import sin
    from lang.parser.parser import parse_file
    from lang.profiler.profiler import Profiler
    from tools.equivalence.python_runner import (
        constants_from_module,
        build_module_callee_table,
        run_python_reference,
    )

    mod = parse_file(
        str(REPO_ROOT / "lang/spec/grammar/examples/orbit.eml")
    )
    Profiler().profile_module(mod)
    fn = next(f for f in mod.functions if f.name == "kepler_solve")

    consts = constants_from_module(mod)
    callees = build_module_callee_table(
        mod, "kepler_solve", constants=consts,
    )
    M, e, n = 1.2, 0.4, 12
    [E] = run_python_reference(
        fn, [(M, e, n)],
        constants=consts, callee_table=callees,
    )
    # 12 Newton steps on Kepler's equation with e=0.4 reaches
    # ~ machine epsilon. Residual is M - (E - e*sin(E)).
    residual = M - (E - e * sin(E))
    assert abs(residual) < 1e-12, (
        f"kepler_solve(M={M}, e={e}, n={n}) returned E={E}; "
        f"residual {residual} not within tolerance"
    )
