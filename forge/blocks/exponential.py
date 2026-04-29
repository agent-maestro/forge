"""Exponential blocks -- exp, decay, growth, sigmoid.

Chain order 1 for raw exp / log; chain order 2 for sigmoid family
(reciprocal of `1 + exp(-x)`). These are the canonical activation
functions for ML inference, the envelope shapers for audio, and
the rate kernels for chemistry / physics.

The `sigmoid` block ships the SuperBEST canonical form -- the
optimizer's superbest pass is a no-op on it, which is the
intended invariant.
"""

from __future__ import annotations

from forge.blocks._core import Block, make_block


# ── exp_block -- raw exp(x) ─────────────────────────────────────

exp_block: Block = make_block(
    name="exp_block",
    source="""\
fn exp_block(x: f64) -> f64
  where chain_order <= 1
{
    exp(x)
}
""",
    parameters=("x",),
    lean_theorem=(
        "theorem exp_block_pos (x : ℝ) : 0 < exp_block x :=\n"
        "  Real.exp_pos _"
    ),
    skip_allocation=True,
)


# ── decay -- exp(-rate * t) ─────────────────────────────────────
#
# Exponential decay envelope. Bounded above by 1 when `rate >= 0`
# and `t >= 0` -- the Lean theorem encodes that invariant.
#

decay: Block = make_block(
    name="decay",
    source="""\
fn decay(t: f64, rate: f64) -> f64
  where chain_order <= 1,
        domain: t >= 0.0,
        domain: rate >= 0.0
{
    exp(-rate * t)
}
""",
    parameters=("t", "rate"),
    lean_theorem=(
        "theorem decay_le_one (t rate : ℝ) (h_t : t ≥ 0) (h_r : rate ≥ 0) :\n"
        "  decay t rate ≤ 1 := by\n"
        "  unfold decay\n"
        "  exact Real.exp_le_one_iff.mpr (mul_nonpos_of_nonpos_of_nonneg\n"
        "    (neg_nonpos_of_nonneg h_r) h_t)"
    ),
    skip_allocation=True,
)


# ── growth -- exp(rate * t) ─────────────────────────────────────
#
# Compound-interest / unbounded population growth. Type checker
# does NOT bound the output -- callers must externally clamp.
#

growth: Block = make_block(
    name="growth",
    source="""\
fn growth(t: f64, rate: f64) -> f64
  where chain_order <= 1
{
    exp(rate * t)
}
""",
    parameters=("t", "rate"),
    lean_theorem=(
        "theorem growth_pos (t rate : ℝ) : 0 < growth t rate :=\n"
        "  Real.exp_pos _"
    ),
    skip_allocation=True,
)


# ── sigmoid -- canonical 1 / (1 + exp(-x)) form ─────────────────
#
# Patent #01 demo. Already in canonical SuperBEST form, so the
# optimizer's superbest pass is a no-op. This is the intended
# invariant.
#

sigmoid_block: Block = make_block(
    name="sigmoid_block",
    source="""\
fn sigmoid_block(x: f64) -> f64
  where chain_order <= 2
{
    1.0 / (1.0 + exp(-x))
}
""",
    parameters=("x",),
    lean_theorem=(
        "theorem sigmoid_in_unit_interval (x : ℝ) :\n"
        "  0 < sigmoid_block x ∧ sigmoid_block x < 1 := by\n"
        "  unfold sigmoid_block\n"
        "  constructor\n"
        "  · exact one_div_pos.mpr (by positivity)\n"
        "  · exact one_div_lt_one_of_lt_div (by simp [Real.exp_pos])\n"
        "      (lt_of_lt_of_le zero_lt_one (le_add_of_nonneg_right (Real.exp_nonneg _)))"
    ),
    skip_allocation=True,
)


# ── softplus -- ln(1 + exp(x)) ─────────────────────────────────
#
# Smooth approximation to ReLU. Chain order 2 for the same reason
# as sigmoid -- the ln nests over the exp.
#

softplus: Block = make_block(
    name="softplus_block",
    source="""\
fn softplus_block(x: f64) -> f64
  where chain_order <= 2
{
    ln(1.0 + exp(x))
}
""",
    parameters=("x",),
    lean_theorem=(
        "theorem softplus_pos (x : ℝ) : 0 < softplus_block x := by\n"
        "  unfold softplus_block\n"
        "  exact Real.log_pos (by linarith [Real.exp_pos x])"
    ),
    skip_allocation=True,
)


# ── tanh_block -- canonical tanh(x) ─────────────────────────────

tanh_block: Block = make_block(
    name="tanh_block",
    source="""\
fn tanh_block(x: f64) -> f64
  where chain_order <= 1
{
    tanh(x)
}
""",
    parameters=("x",),
    lean_theorem=(
        "theorem tanh_in_open_neg_one_one (x : ℝ) :\n"
        "  -1 < tanh_block x ∧ tanh_block x < 1 :=\n"
        "  ⟨Real.neg_one_lt_tanh _, Real.tanh_lt_one _⟩"
    ),
    skip_allocation=True,
)


__all__ = [
    "exp_block",
    "decay",
    "growth",
    "sigmoid_block",
    "softplus",
    "tanh_block",
]
