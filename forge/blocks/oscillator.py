"""Oscillator blocks -- sin, cos, damped_osc, fm_carrier.

Chain order 1 for the elementary oscillators (`sin(omega * t)`),
chain order 2 for blocks that nest a sin inside an exp envelope
(`exp(-decay * t) * sin(omega * t)`), chain order 3 for FM where
the modulator's sin nests inside the carrier's sin.

These are the canonical building blocks for synthesis (audio,
RF, sensor simulation) and for any controller that consumes a
phase signal.
"""

from __future__ import annotations

from forge.blocks._core import Block, make_block


# ── sin(omega * t) -- the elementary oscillator ──────────────────

sin_block: Block = make_block(
    name="sin_block",
    source="""\
fn sin_block(t: f64, omega: f64) -> f64
  where chain_order <= 1
{
    sin(omega * t)
}
""",
    parameters=("t", "omega"),
    lean_theorem=(
        "theorem sin_block_bounded (t omega : ℝ) :\n"
        "  -1 ≤ sin_block t omega ∧ sin_block t omega ≤ 1 :=\n"
        "  ⟨Real.neg_one_le_sin _, Real.sin_le_one _⟩"
    ),
    skip_allocation=True,
)


# ── cos(omega * t) ──────────────────────────────────────────────

cos_block: Block = make_block(
    name="cos_block",
    source="""\
fn cos_block(t: f64, omega: f64) -> f64
  where chain_order <= 1
{
    cos(omega * t)
}
""",
    parameters=("t", "omega"),
    lean_theorem=(
        "theorem cos_block_bounded (t omega : ℝ) :\n"
        "  -1 ≤ cos_block t omega ∧ cos_block t omega ≤ 1 :=\n"
        "  ⟨Real.neg_one_le_cos _, Real.cos_le_one _⟩"
    ),
    skip_allocation=True,
)


# ── damped_osc -- exp(-decay * t) * sin(omega * t) ──────────────
#
# Patent #14 demo target. The 4-sin shared / 1-exp dedicated
# allocation decision is exercised here when this block is paired
# with three additional oscillators.
#

damped_osc: Block = make_block(
    name="damped_osc",
    source="""\
@target(fpga, clock_mhz = 100)
fn damped_osc(t: f64, omega: f64, decay: f64) -> f64
  where chain_order <= 2
{
    exp(-decay * t) * sin(omega * t)
}
""",
    parameters=("t", "omega", "decay"),
    lean_theorem=(
        "-- Decays to zero; bounded by the envelope.\n"
        "theorem damped_osc_envelope (t omega decay : ℝ) (h : decay ≥ 0) :\n"
        "  abs (damped_osc t omega decay) ≤ Real.exp (-decay * t) := by\n"
        "  unfold damped_osc\n"
        "  exact mul_le_of_le_one_right (Real.exp_pos _).le (abs_sin_le_one _)"
    ),
)


# ── fm_carrier -- sin(omega_c * t + beta * sin(omega_m * t)) ────
#
# Frequency-modulated carrier. The nested `sin` inside `sin` lifts
# the chain order to 3, which the type checker enforces.
#

fm_carrier: Block = make_block(
    name="fm_carrier",
    source="""\
fn fm_carrier(t: f64, omega_c: f64, omega_m: f64, beta: f64) -> f64
  where chain_order <= 3
{
    sin(omega_c * t + beta * sin(omega_m * t))
}
""",
    parameters=("t", "omega_c", "omega_m", "beta"),
    lean_theorem=(
        "theorem fm_carrier_bounded (t omega_c omega_m beta : ℝ) :\n"
        "  -1 ≤ fm_carrier t omega_c omega_m beta ∧\n"
        "  fm_carrier t omega_c omega_m beta ≤ 1 :=\n"
        "  ⟨Real.neg_one_le_sin _, Real.sin_le_one _⟩"
    ),
    skip_allocation=True,
)


# ── chirp -- sin(2*pi*f0*t + 0.5*k*t*t) ─────────────────────────
#
# Linear chirp -- frequency increases linearly with time. The
# t*t in the phase keeps chain order at 1 since t*t is polynomial.
#

chirp: Block = make_block(
    name="chirp",
    source="""\
fn chirp(t: f64, f0: f64, k: f64) -> f64
  where chain_order <= 1
{
    sin(6.28318530717958647692 * f0 * t + 0.5 * k * t * t)
}
""",
    parameters=("t", "f0", "k"),
    skip_allocation=True,
)


__all__ = [
    "sin_block",
    "cos_block",
    "damped_osc",
    "fm_carrier",
    "chirp",
]
