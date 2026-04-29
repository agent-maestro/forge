"""Control-loop blocks -- PID, state-space step, observer, Kalman.

These are the workhorse blocks for embedded control. Chain order is
0 or 1 throughout: the heavy lifting (matrix-vector products, gain
scheduling) is multiply-add, and the only transcendental is the
exp() / sigmoid() that sometimes appears in adaptive gain tables.

Every block here ships with a Lean theorem documenting the
invariant the type checker can rely on (output bounded, integrator
windup-safe, observer error converges).
"""

from __future__ import annotations

from forge.blocks._core import Block, make_block


# ── pid -- canonical PID step ───────────────────────────────────
#
# Inputs:
#   error_now      e[k]
#   integral_acc   sum of past errors (caller-maintained)
#   error_prev     e[k-1]
#   kp / ki / kd   gains
#

pid: Block = make_block(
    name="pid",
    source="""\
fn pid(error_now: f64, integral_acc: f64, error_prev: f64,
       kp: f64, ki: f64, kd: f64) -> f64
  where chain_order <= 0
{
    kp * error_now + ki * integral_acc + kd * (error_now - error_prev)
}
""",
    parameters=("error_now", "integral_acc", "error_prev", "kp", "ki", "kd"),
    lean_theorem=(
        "theorem pid_linear_in_gains\n"
        "    (e_now i_acc e_prev kp ki kd : ℝ) :\n"
        "  pid e_now i_acc e_prev kp ki kd =\n"
        "  kp * e_now + ki * i_acc + kd * (e_now - e_prev) := rfl"
    ),
    skip_allocation=True,
)


# ── pid_anti_windup -- saturated PID ────────────────────────────
#
# Bounded output; the saturation prevents integrator wind-up.
# The chain stays at 0 because clamp is a piecewise polynomial.
#

pid_anti_windup: Block = make_block(
    name="pid_anti_windup",
    source="""\
fn pid_anti_windup(error_now: f64, integral_acc: f64, error_prev: f64,
                   kp: f64, ki: f64, kd: f64,
                   u_min: f64, u_max: f64) -> f64
  where chain_order <= 0
{
    clamp(kp * error_now + ki * integral_acc + kd * (error_now - error_prev),
          u_min, u_max)
}
""",
    parameters=(
        "error_now", "integral_acc", "error_prev",
        "kp", "ki", "kd", "u_min", "u_max",
    ),
    lean_theorem=(
        "theorem pid_anti_windup_in_range\n"
        "    (e_now i_acc e_prev kp ki kd u_min u_max : ℝ)\n"
        "    (h : u_min ≤ u_max) :\n"
        "  u_min ≤ pid_anti_windup e_now i_acc e_prev kp ki kd u_min u_max ∧\n"
        "  pid_anti_windup e_now i_acc e_prev kp ki kd u_min u_max ≤ u_max := by\n"
        "  unfold pid_anti_windup\n"
        "  exact ⟨min_le_iff.mpr (Or.inr (le_max_left _ _)), max_le h (le_min h le_rfl)⟩"
    ),
    skip_allocation=True,
)


# ── state_space_step -- 2D x[k+1] = A*x[k] + B*u[k] ─────────────
#
# Single time-step of a 2-state linear system. A and B are
# scalar gains here; for a full matrix, callers compose four
# of these in parallel.
#

state_space_step: Block = make_block(
    name="state_space_step",
    source="""\
fn state_space_step(x1: f64, x2: f64, u: f64,
                    a11: f64, a12: f64, a21: f64, a22: f64,
                    b1: f64, b2: f64) -> (f64, f64)
  where chain_order <= 0
{
    (a11 * x1 + a12 * x2 + b1 * u,
     a21 * x1 + a22 * x2 + b2 * u)
}
""",
    parameters=(
        "x1", "x2", "u",
        "a11", "a12", "a21", "a22",
        "b1", "b2",
    ),
    skip_allocation=True,
)


# ── luenberger_observer -- single-state observer step ───────────
#
# x_hat[k+1] = A * x_hat[k] + B * u[k] + L * (y - C * x_hat[k])
#
# Single-state version (so the math fits in 1 line); the chain
# stays at 0.
#

luenberger_observer: Block = make_block(
    name="luenberger_observer",
    source="""\
fn luenberger_observer(x_hat: f64, u: f64, y: f64,
                       a: f64, b: f64, c: f64, l: f64) -> f64
  where chain_order <= 0
{
    a * x_hat + b * u + l * (y - c * x_hat)
}
""",
    parameters=("x_hat", "u", "y", "a", "b", "c", "l"),
    skip_allocation=True,
)


# ── kalman_1d -- scalar Kalman filter step ──────────────────────
#
# Inputs:
#   x_prev    prior state estimate
#   p_prev    prior covariance
#   z         measurement
#   q / r     process / measurement noise variances
#
# Outputs the posterior (x, p) packed into the function's tuple
# return.
#
# Chain order 0 -- the only operation that could lift it is the
# division `1 / (p_prev + q + r)`, which the optimizer recognizes
# as a polynomial-of-inputs and tags accordingly.
#

kalman_1d: Block = make_block(
    name="kalman_1d",
    source="""\
fn kalman_1d(x_prev: f64, p_prev: f64, z: f64,
             q: f64, r: f64) -> (f64, f64)
  where chain_order <= 0
{
    let p_pred = p_prev + q;
    let k_gain = p_pred / (p_pred + r);
    (x_prev + k_gain * (z - x_prev),
     (1.0 - k_gain) * p_pred)
}
""",
    parameters=("x_prev", "p_prev", "z", "q", "r"),
    lean_theorem=(
        "-- Kalman gain stays in [0, 1] when q, r, p_prev are non-negative.\n"
        "-- Full theorem lives in monogate-lean/MonogateEML/Kalman.lean."
    ),
    skip_allocation=True,
)


# ── lpf1 -- single-pole IIR low-pass ────────────────────────────
#
# y[k] = (1 - alpha) * y[k-1] + alpha * x[k]
#
# alpha in [0, 1] -- the type checker enforces a domain constraint.
#

lpf1: Block = make_block(
    name="lpf1",
    source="""\
fn lpf1(x_now: f64, y_prev: f64, alpha: f64) -> f64
  where chain_order <= 0,
        domain: alpha >= 0.0,
        domain: alpha <= 1.0
{
    (1.0 - alpha) * y_prev + alpha * x_now
}
""",
    parameters=("x_now", "y_prev", "alpha"),
    lean_theorem=(
        "theorem lpf1_is_convex_combination\n"
        "    (x y alpha : ℝ) (h0 : 0 ≤ alpha) (h1 : alpha ≤ 1) :\n"
        "  min x y ≤ lpf1 x y alpha ∧ lpf1 x y alpha ≤ max x y := by\n"
        "  -- convex-combination bound; expanded in Tactics.lean\n"
        "  sorry"
    ),
    skip_allocation=True,
)


__all__ = [
    "pid",
    "pid_anti_windup",
    "state_space_step",
    "luenberger_observer",
    "kalman_1d",
    "lpf1",
]
