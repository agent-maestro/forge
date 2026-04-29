"""Signal-processing blocks -- FFT butterfly, convolution, biquad.

The FFT butterfly is the canonical radix-2 building block. The
convolution kernel is a 3-tap FIR; longer kernels compose by
unrolling. The biquad is the canonical IIR section.

Chain order 0 across the lot -- pure multiply-add, no
transcendentals (the FFT butterfly's twiddle factors are passed
in as parameters, not computed inline).
"""

from __future__ import annotations

from forge.blocks._core import Block, make_block


# ── fft_butterfly -- single radix-2 step ────────────────────────
#
# Inputs:  (a_re, a_im), (b_re, b_im), twiddle (w_re, w_im)
# Outputs: (a' = a + w*b, b' = a - w*b)
#
# Returns the 4 components of the two output complex pairs.
#

fft_butterfly: Block = make_block(
    name="fft_butterfly",
    source="""\
fn fft_butterfly(a_re: f64, a_im: f64,
                 b_re: f64, b_im: f64,
                 w_re: f64, w_im: f64)
                 -> (f64, f64, f64, f64)
  where chain_order <= 0
{
    let wb_re = w_re * b_re - w_im * b_im;
    let wb_im = w_re * b_im + w_im * b_re;
    (a_re + wb_re, a_im + wb_im,
     a_re - wb_re, a_im - wb_im)
}
""",
    parameters=("a_re", "a_im", "b_re", "b_im", "w_re", "w_im"),
    lean_theorem=(
        "-- The butterfly preserves total energy:\n"
        "--   |a'|^2 + |b'|^2 = 2 * (|a|^2 + |b|^2)\n"
        "-- Full proof lives in monogate-lean/MonogateEML/FFT.lean."
    ),
    skip_allocation=True,
)


# ── convolution_3tap -- 3-tap FIR convolution ───────────────────
#
# y[k] = c0*x[k] + c1*x[k-1] + c2*x[k-2]
#

convolution_3tap: Block = make_block(
    name="convolution_3tap",
    source="""\
fn convolution_3tap(x: f64, x_z1: f64, x_z2: f64,
                    c0: f64, c1: f64, c2: f64) -> f64
  where chain_order <= 0
{
    c0 * x + c1 * x_z1 + c2 * x_z2
}
""",
    parameters=("x", "x_z1", "x_z2", "c0", "c1", "c2"),
    skip_allocation=True,
)


# ── convolution_5tap -- 5-tap FIR ───────────────────────────────

convolution_5tap: Block = make_block(
    name="convolution_5tap",
    source="""\
fn convolution_5tap(x: f64, x_z1: f64, x_z2: f64, x_z3: f64, x_z4: f64,
                    c0: f64, c1: f64, c2: f64, c3: f64, c4: f64) -> f64
  where chain_order <= 0
{
    c0 * x + c1 * x_z1 + c2 * x_z2 + c3 * x_z3 + c4 * x_z4
}
""",
    parameters=(
        "x", "x_z1", "x_z2", "x_z3", "x_z4",
        "c0", "c1", "c2", "c3", "c4",
    ),
    skip_allocation=True,
)


# ── biquad_step -- canonical Direct-Form-I biquad ───────────────
#
# y[k] = b0*x[k] + b1*x[k-1] + b2*x[k-2]
#       - a1*y[k-1] - a2*y[k-2]
#
# DF-I is preferred over DF-II / DF-II-T for fp32 stability --
# the optimizer's superbest pass would rewrite a DF-II-T body to
# this form anyway.
#

biquad_step: Block = make_block(
    name="biquad_step",
    source="""\
fn biquad_step(x: f64, x_z1: f64, x_z2: f64,
               y_z1: f64, y_z2: f64,
               b0: f64, b1: f64, b2: f64,
               a1: f64, a2: f64) -> f64
  where chain_order <= 0
{
    b0 * x + b1 * x_z1 + b2 * x_z2 - a1 * y_z1 - a2 * y_z2
}
""",
    parameters=(
        "x", "x_z1", "x_z2", "y_z1", "y_z2",
        "b0", "b1", "b2", "a1", "a2",
    ),
    lean_theorem=(
        "theorem biquad_step_linear\n"
        "    (x x_z1 x_z2 y_z1 y_z2 b0 b1 b2 a1 a2 : ℝ) :\n"
        "  biquad_step x x_z1 x_z2 y_z1 y_z2 b0 b1 b2 a1 a2 =\n"
        "  b0*x + b1*x_z1 + b2*x_z2 - a1*y_z1 - a2*y_z2 := rfl"
    ),
    skip_allocation=True,
)


# ── moving_average_4 -- 4-sample boxcar filter ──────────────────

moving_average_4: Block = make_block(
    name="moving_average_4",
    source="""\
fn moving_average_4(x0: f64, x1: f64, x2: f64, x3: f64) -> f64
  where chain_order <= 0
{
    (x0 + x1 + x2 + x3) * 0.25
}
""",
    parameters=("x0", "x1", "x2", "x3"),
    skip_allocation=True,
)


# ── one_pole_hpf -- single-pole high-pass filter ────────────────
#
# y[k] = alpha * (y[k-1] + x[k] - x[k-1])
#

one_pole_hpf: Block = make_block(
    name="one_pole_hpf",
    source="""\
fn one_pole_hpf(x_now: f64, x_prev: f64, y_prev: f64, alpha: f64) -> f64
  where chain_order <= 0,
        domain: alpha >= 0.0,
        domain: alpha <= 1.0
{
    alpha * (y_prev + x_now - x_prev)
}
""",
    parameters=("x_now", "x_prev", "y_prev", "alpha"),
    skip_allocation=True,
)


__all__ = [
    "fft_butterfly",
    "convolution_3tap",
    "convolution_5tap",
    "biquad_step",
    "moving_average_4",
    "one_pole_hpf",
]
