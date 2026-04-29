"""Polynomial blocks -- linear, quadratic, power.

Chain order 0 across the board: pure multiply-add, no transcendentals.
These are the safest building blocks numerically; the type checker
will accept them under any `where chain_order <= N` clause for N >= 0.
"""

from __future__ import annotations

from forge.blocks._core import Block, make_block


# ── linear ──────────────────────────────────────────────────────────
#
# y = m * x + b -- the canonical affine map.
#

linear: Block = make_block(
    name="linear",
    source="""\
fn linear(x: f64, m: f64, b: f64) -> f64
  where chain_order <= 0
{
    m * x + b
}
""",
    parameters=("x", "m", "b"),
    lean_theorem=(
        "theorem linear_is_affine (x m b : ℝ) :\n"
        "  linear x m b = m * x + b := rfl"
    ),
    skip_allocation=True,
)


# ── quadratic ────────────────────────────────────────────────────────
#
# y = a*x^2 + b*x + c -- canonical quadratic.
# The optimizer's CSE pass folds the duplicate `x` reference.
#

quadratic: Block = make_block(
    name="quadratic",
    source="""\
fn quadratic(x: f64, a: f64, b: f64, c: f64) -> f64
  where chain_order <= 0
{
    a * x * x + b * x + c
}
""",
    parameters=("x", "a", "b", "c"),
    lean_theorem=(
        "theorem quadratic_is_polynomial (x a b c : ℝ) :\n"
        "  quadratic x a b c = a*x*x + b*x + c := rfl"
    ),
    skip_allocation=True,
)


# ── power (integer-exponent) ─────────────────────────────────────────
#
# y = base^k for k in {2, 3, 4} -- expanded to multiplications so the
# chain order stays at 0. Higher k uses `pow(...)` and lifts to
# chain order 1.
#

power_squared: Block = make_block(
    name="power_squared",
    source="""\
fn power_squared(x: f64) -> f64
  where chain_order <= 0
{
    x * x
}
""",
    parameters=("x",),
    skip_allocation=True,
)

power_cubed: Block = make_block(
    name="power_cubed",
    source="""\
fn power_cubed(x: f64) -> f64
  where chain_order <= 0
{
    x * x * x
}
""",
    parameters=("x",),
    skip_allocation=True,
)

power_quartic: Block = make_block(
    name="power_quartic",
    source="""\
fn power_quartic(x: f64) -> f64
  where chain_order <= 0
{
    let xx = x * x;
    xx * xx
}
""",
    parameters=("x",),
    skip_allocation=True,
)


# ── horner-form polynomial ───────────────────────────────────────────
#
# Higher-degree polynomial evaluation in Horner form. The choice of
# Horner over the direct power-of-x formulation halves the multiply
# count and keeps fp32 numerical drift bounded.
#

horner_quintic: Block = make_block(
    name="horner_quintic",
    source="""\
fn horner_quintic(x: f64, a0: f64, a1: f64, a2: f64,
                  a3: f64, a4: f64, a5: f64) -> f64
  where chain_order <= 0
{
    a0 + x * (a1 + x * (a2 + x * (a3 + x * (a4 + x * a5))))
}
""",
    parameters=("x", "a0", "a1", "a2", "a3", "a4", "a5"),
    skip_allocation=True,
)


__all__ = [
    "linear",
    "quadratic",
    "power_squared",
    "power_cubed",
    "power_quartic",
    "horner_quintic",
]
