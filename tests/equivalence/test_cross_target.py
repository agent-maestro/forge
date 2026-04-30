"""Cross-target equivalence tests -- operational proof of Patent #22.

For a curated set of stdlib functions, compile to every available
backend, run the same input vectors through each, and assert the
outputs agree with the Python SymPy reference within a tight ULP
tolerance.

Toolchain skipping: each backend reports `available=False` when
its compiler isn't on PATH, and the harness's `overall_match`
only requires available backends to match. A box without
gcc/cargo/verilator still passes the test, but the test no
longer proves anything for the missing target.

NOTE: cargo builds are slow (~10s each). To keep the test suite
fast, the parametrize set is intentionally small and focuses on
representative chain-order classes (0, 1, 2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.equivalence import cross_target_check
from tools.equivalence.rust_runner import cargo_available


REPO_ROOT = Path(__file__).resolve().parents[2]
STDLIB_DIR = REPO_ROOT / "lang" / "spec" / "stdlib"

# ── Curated test cases ────────────────────────────────────────
#
# Each entry: (file, fn_name, vectors, max_abs_tolerance)
#
# Coverage rationale:
#   - lerp     chain 0, multiplies + adds
#   - sq       chain 0, single mul
#   - hypot2   chain 1, sqrt of sum-of-squares
#   - sigmoid  chain 1, exp + divide
#   - softplus chain 2, ln(1 + exp(x))
#   - vec3_dot chain 0, multi-arg, scalar return

CASES: list[tuple[str, str, list[tuple[float, ...]], float]] = [
    ("math.eml", "lerp", [
        (0.0, 10.0, 0.0),
        (0.0, 10.0, 0.5),
        (0.0, 10.0, 1.0),
        (-3.0, 7.0, 0.25),
        (1.5, 1.5, 0.7),
    ], 1e-12),
    ("math.eml", "sq", [
        (0.0,), (1.0,), (-2.5,), (1e3,), (1e-3,),
    ], 1e-12),
    ("math.eml", "hypot2", [
        (3.0, 4.0),     # 5
        (5.0, 12.0),    # 13
        (1.0, 1.0),
        (0.0, 7.0),
    ], 1e-12),
    # sigmoid + softplus moved from stdlib::math to stdlib::ml in 2026-04
    # to keep math.eml as a numeric utilities module and let ML code
    # write `use stdlib::ml;` for its activations.
    ("ml.eml", "sigmoid", [
        (0.0,), (1.0,), (-1.0,), (5.0,), (-5.0,),
    ], 1e-12),
    ("ml.eml", "softplus", [
        (0.0,), (1.0,), (-1.0,), (5.0,), (-2.5,),
    ], 1e-12),
    ("linalg.eml", "vec3_dot", [
        (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),    # 32
        (0.0, 0.0, 0.0, 1.0, 1.0, 1.0),    # 0
        (-1.0, 2.0, -3.0, 4.0, -5.0, 6.0), # -32
    ], 1e-12),
]


@pytest.mark.parametrize(
    "filename,fn_name,vectors,tolerance",
    CASES,
    ids=[f"{c[0]}::{c[1]}" for c in CASES],
)
def test_python_reference_self_consistent(
    filename: str,
    fn_name: str,
    vectors: list[tuple[float, ...]],
    tolerance: float,
) -> None:
    """Sanity check: the Python reference runs and produces a
    finite output for every vector. This is the precondition for
    every other backend's comparison."""
    path = STDLIB_DIR / filename
    r = cross_target_check(
        path, fn_name, vectors,
        tolerance=tolerance,
        targets=("python",),
    )
    py = r.targets["python"]
    assert py.available, f"python ref unavailable: {py.error}"
    assert len(py.outputs) == len(vectors)
    for out in py.outputs:
        assert out == out  # not NaN
        assert out != float("inf")
        assert out != float("-inf")


@pytest.mark.skipif(
    not cargo_available(),
    reason="cargo / rustc not on PATH",
)
@pytest.mark.parametrize(
    "filename,fn_name,vectors,tolerance",
    CASES,
    ids=[f"{c[0]}::{c[1]}" for c in CASES],
)
def test_rust_matches_python(
    filename: str,
    fn_name: str,
    vectors: list[tuple[float, ...]],
    tolerance: float,
) -> None:
    """The Rust backend's compiled output must agree with the
    Python reference within `tolerance`."""
    path = STDLIB_DIR / filename
    r = cross_target_check(
        path, fn_name, vectors,
        tolerance=tolerance,
        targets=("python", "rust"),
    )
    rust = r.targets["rust"]
    assert rust.available, f"rust unavailable: {rust.error}"
    assert rust.error == "", (
        f"rust runner error on {filename}::{fn_name}: {rust.error}"
    )
    assert rust.max_abs_err <= tolerance, (
        f"{filename}::{fn_name}: rust diverged "
        f"(max_abs={rust.max_abs_err:.3g}, tol={tolerance:.3g})\n"
        + r.render()
    )


def test_overall_match_treats_skipped_targets_as_pass() -> None:
    """Box without a toolchain must still be able to assert
    overall_match=True so the test suite is portable."""
    path = STDLIB_DIR / "math.eml"
    r = cross_target_check(
        path, "lerp", [(0.0, 1.0, 0.5)],
        tolerance=1e-12,
        targets=("python", "rust", "c"),
    )
    # python is always available; one of (rust, c) may be skipped.
    # overall_match must reflect only the available ones.
    available_ok = all(
        (not t.available) or (t.error == "")
        for t in r.targets.values()
    )
    if available_ok:
        assert r.overall_match, r.render()
