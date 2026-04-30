"""Verify that the optimizer pass sequence is correctness-preserving.

For a curated set of stdlib + vertical functions, build the Rust
target two ways:
  - With the optimizer enabled (default)
  - With the optimizer disabled (--no-optimize)

Run identical input vectors through each and assert the outputs
match BIT-EXACTLY. This is the formal correctness gate for every
pass in `lang/optimizer/` -- if a future pass introduces a
rounding-changing rewrite, this test catches it immediately.

Why bit-exact (not ULP-tolerant): every current pass (constant
folding + CSE + SuperBEST identity) is provably bit-preserving.
Constant folding evaluates literal arithmetic in IEEE-754 doubles
exactly the same way the runtime would; CSE is a hoist (zero
arithmetic change). If a future pass needs ULP tolerance, that's
a deliberate design decision and this test should be updated to
record it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.equivalence import cross_target_check
from tools.equivalence.rust_runner import cargo_available


REPO_ROOT = Path(__file__).resolve().parents[2]


# Each entry: (path, fn_name, vectors)
# Mix of stdlib (small expressions) and vertical (production-shape).
CASES: list[tuple[str, str, list[tuple[float, ...]]]] = [
    # Stdlib -- exercises folding-friendly literal arithmetic
    ("lang/spec/stdlib/math.eml", "lerp", [
        (0.0, 10.0, 0.5), (1.5, 1.5, 0.7), (-3.0, 7.0, 0.25),
    ]),
    ("lang/spec/stdlib/ml.eml", "sigmoid", [
        (0.0,), (1.0,), (-2.5,),
    ]),
    ("lang/spec/stdlib/math.eml", "hypot2", [
        (3.0, 4.0), (5.0, 12.0),
    ]),
    ("lang/spec/stdlib/linalg.eml", "vec3_dot", [
        (1.0, 2.0, 3.0, 4.0, 5.0, 6.0),
        (-1.0, 2.0, -3.0, 4.0, -5.0, 6.0),
    ]),
    # Vertical -- production-shape with module constants that
    # the folder has to substitute
    ("industries/aerospace/flight_control/autopilot.eml",
     "gravity_compensation", [
        (0.0,), (0.1,), (-0.2,),
    ]),
    ("industries/defense/navigation/ins.eml",
     "attitude_step", [
        (0.0, 0.0), (0.1, 0.05),
    ]),
    # NOTE: motor_foc::pi_step is NOT included here. Since the
    # 2026-04 stdlib refactor it calls `pid(...)` from
    # stdlib::control, which the SymPy bridge cannot evaluate
    # without the inliner (the no-optimize path leaves it as an
    # opaque sp.Function). The full Rust-vs-Python equivalence
    # for that function is still covered by
    # tests/equivalence/test_industry_verticals.py with
    # optimization enabled (the production path).
]


@pytest.mark.skipif(
    not cargo_available(),
    reason="cargo / rustc not on PATH",
)
@pytest.mark.parametrize(
    "path,fn_name,vectors",
    CASES,
    ids=[f"{c[0]}::{c[1]}" for c in CASES],
)
def test_optimizer_is_bit_preserving(
    path: str,
    fn_name: str,
    vectors: list[tuple[float, ...]],
) -> None:
    """Optimized and unoptimized Rust outputs must agree bit-exactly."""
    full_path = REPO_ROOT / path
    opt = cross_target_check(
        full_path, fn_name, vectors,
        targets=("rust",),
        optimize=True,
    )
    raw = cross_target_check(
        full_path, fn_name, vectors,
        targets=("rust",),
        optimize=False,
    )

    opt_rust = opt.targets["rust"]
    raw_rust = raw.targets["rust"]

    assert opt_rust.available and raw_rust.available, (
        f"both rust paths must build (opt: {opt_rust.error}; "
        f"raw: {raw_rust.error})"
    )
    assert opt_rust.outputs == raw_rust.outputs, (
        f"{path}::{fn_name}: optimizer changed numerical outputs!\n"
        f"  optimized: {opt_rust.outputs}\n"
        f"  raw:       {raw_rust.outputs}\n"
        f"  diffs:     {[
            o - r for o, r in zip(opt_rust.outputs, raw_rust.outputs)
            if o != r
        ]}"
    )
