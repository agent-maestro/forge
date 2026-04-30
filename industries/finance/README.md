# finance — Quantitative Finance vertical

> Forge for Quant Finance. Pricing models, Greeks, and risk
> calculations as `.eml` source — same file compiles to C, Rust,
> Verilog, VHDL, Chisel, LLVM, and an associated Lean theorem.

**Certification target:** SR 11-7 (Federal Reserve Model Risk
Management) + FRTB internal-model approval.
**Typical chain orders:** 1–3 (transcendental-heavy: exp / log /
sqrt / tanh dominate; the normal CDF approximation is the routing
choice that drives most of the chain order).

## Why finance belongs in EML-lang

The headline forge property here is **regulator-acceptable formal
verification of pricing models**. Banks already pay regulators
(US OCC, EU EBA, UK PRA) for permission to use internal pricing
models for capital calculation; the bottleneck is the model
validation and ongoing monitoring under SR 11-7 and FRTB. Today
this is "shadow code in C++ vs Excel vs MATLAB, model risk
committee review, manual sign-off." Forge's pitch:

  - One source of truth (`.eml`) for the pricing math.
  - A Lean theorem attached to every callable: monotonicity in
    spot, put-call parity, no-arbitrage bounds, etc.
  - The same source emits the C reference, the FPGA bitstream,
    and the regulator-facing PDF.
  - Bit-exact equivalence across backends (the existing harness
    in `tools/equivalence/`) — model risk committees can stop
    arguing about which language is canonical.

The market is the pricing-engineering teams at HFT firms, options
market makers, dealing banks, and quant hedge funds. The pricing
goes onto FPGAs in market-making (microseconds matter) and onto
GPUs in risk (millions of paths × thousands of instruments).

## Subdirectories

| Path | Family | Headline files | Chain order |
|------|--------|----------------|-------------|
| `pricing/` | Closed-form / approximation pricers | `black_scholes.eml`, `heston.eml`, `sabr.eml` | 1–3 |
| `greeks/` | First-order option sensitivities | `delta.eml`, `gamma.eml`, `vega.eml`, `theta.eml` | 1–2 |
| `risk/` | Tail-risk + stress + counterparty | `var_monte_carlo.eml`, `cva.eml`, `stress_test.eml` | 0–1 |
| `certification/` | Regulator-facing docs | `MODEL_VALIDATION.md`, `FRTB_COMPLIANCE.md` | n/a |

## Numerical notes

The standard-normal CDF `N(x)` has no closed form in EML's
builtin set, so each pricer here uses a tanh-based polynomial
approximation:

    N(x) ≈ 0.5 * (1 + tanh(sqrt(2/π) * (x + 0.044715 * x³)))

This is the GELU-paper approximation, accurate to ~1.5e-7 over
|x| < 6 — well within the precision banks accept for daily
pricing. The chain order ends up at 1 (single tanh applied to a
chain-0 polynomial), which keeps drift_risk LOW per the existing
`fp16_drift_risk` model.

For Heston / SABR / risk pricers that need ln + sqrt + exp
chains, the chain order rises to 2–3; those functions are tagged
explicitly in their `where chain_order <= N` declarations and
should always be deployed at f64 precision.

## Adding an application

1. Pick the right subdirectory (or create one if the model
   doesn't fit `pricing` / `greeks` / `risk`).
2. Write a `<name>.eml` file with chain-order + domain +
   precision declarations.
3. Add the regulator-facing theorem statement in `certification/`
   if the function is in production use.
4. Add a test in `tests/industry/test_finance.py`.

## Cross-references

- Stdlib transcendentals used here come from `lang/spec/stdlib/math.eml`.
- The cross-target equivalence harness at `tools/equivalence/`
  is what produces the bit-exact agreement claim.
- The certification posture mirrors `industries/aerospace/` (DO-178C)
  and `industries/medical/` (IEC 62304) — the procedural shape is
  the same; the domain content differs.
