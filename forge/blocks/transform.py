"""Coordinate-frame transforms for motor control -- Park, Clarke, dq0.

These are the canonical transforms that turn three-phase quantities
(`a, b, c`) into the rotor-frame d-q quantities the control loop
runs on. Chain order 1 because of the embedded sin/cos -- but
because the angle `theta` is an input rather than a derived
quantity, the chain stays bounded.

Vector
======

Field-oriented control of permanent-magnet synchronous motors
goes through this pipeline every loop iteration:

  abc → (clarke) → α-β → (park) → d-q  → controllers
                                      ↓
                                  inverse_park
                                      ↓
                                  inverse_clarke → SVPWM
"""

from __future__ import annotations

from forge.blocks._core import Block, make_block


# ── clarke -- a/b/c to alpha/beta (3-phase to 2-phase) ──────────
#
# Power-invariant Clarke transform.
# alpha = (2*a - b - c) / 3
# beta  = (b - c) / sqrt(3)
#

clarke: Block = make_block(
    name="clarke",
    source="""\
fn clarke(a: f64, b: f64, c: f64) -> (f64, f64)
  where chain_order <= 0
{
    let alpha = (2.0 * a - b - c) * 0.33333333333333333;
    let beta  = (b - c) * 0.57735026918962576;
    (alpha, beta)
}
""",
    parameters=("a", "b", "c"),
    lean_theorem=(
        "theorem clarke_balanced_zero\n"
        "    (a b c : ℝ) (h : a + b + c = 0) :\n"
        "  (clarke a b c).1 = a := by\n"
        "  unfold clarke\n"
        "  field_simp\n"
        "  linarith"
    ),
    skip_allocation=True,
)


# ── inverse_clarke -- alpha/beta back to a/b/c ──────────────────

inverse_clarke: Block = make_block(
    name="inverse_clarke",
    source="""\
fn inverse_clarke(alpha: f64, beta: f64) -> (f64, f64, f64)
  where chain_order <= 0
{
    let a = alpha;
    let b = -0.5 * alpha + 0.86602540378443864 * beta;
    let c = -0.5 * alpha - 0.86602540378443864 * beta;
    (a, b, c)
}
""",
    parameters=("alpha", "beta"),
    skip_allocation=True,
)


# ── park -- alpha/beta to d/q (rotating to rotor frame) ─────────
#
# d =  alpha * cos(theta) + beta * sin(theta)
# q = -alpha * sin(theta) + beta * cos(theta)
#

park: Block = make_block(
    name="park",
    source="""\
fn park(alpha: f64, beta: f64, theta: f64) -> (f64, f64)
  where chain_order <= 1
{
    let c = cos(theta);
    let s = sin(theta);
    (alpha * c + beta * s,
     -alpha * s + beta * c)
}
""",
    parameters=("alpha", "beta", "theta"),
    lean_theorem=(
        "-- d^2 + q^2 = alpha^2 + beta^2 (Park is an isometry).\n"
        "theorem park_preserves_norm (alpha beta theta : ℝ) :\n"
        "  let (d, q) := park alpha beta theta\n"
        "  d^2 + q^2 = alpha^2 + beta^2 := by\n"
        "  unfold park\n"
        "  ring_nf\n"
        "  rw [Real.sin_sq_add_cos_sq]\n"
        "  ring"
    ),
    skip_allocation=True,
)


# ── inverse_park -- d/q to alpha/beta ───────────────────────────

inverse_park: Block = make_block(
    name="inverse_park",
    source="""\
fn inverse_park(d: f64, q: f64, theta: f64) -> (f64, f64)
  where chain_order <= 1
{
    let c = cos(theta);
    let s = sin(theta);
    (d * c - q * s,
     d * s + q * c)
}
""",
    parameters=("d", "q", "theta"),
    skip_allocation=True,
)


# ── dq0 -- 3-phase abc to dq0 (Park + Clarke fused) ─────────────
#
# The composed pipeline the FOC inner loop actually runs. Chain
# order 1 (cos/sin nesting) -- the Clarke layer is pure
# multiply-add and doesn't lift the chain.
#

dq0: Block = make_block(
    name="dq0",
    source="""\
fn dq0(a: f64, b: f64, c: f64, theta: f64) -> (f64, f64, f64)
  where chain_order <= 1
{
    let alpha = (2.0 * a - b - c) * 0.33333333333333333;
    let beta  = (b - c) * 0.57735026918962576;
    let zero  = (a + b + c) * 0.33333333333333333;
    let cs = cos(theta);
    let sn = sin(theta);
    (alpha * cs + beta * sn,
     -alpha * sn + beta * cs,
     zero)
}
""",
    parameters=("a", "b", "c", "theta"),
    skip_allocation=True,
)


__all__ = [
    "clarke",
    "inverse_clarke",
    "park",
    "inverse_park",
    "dq0",
]
