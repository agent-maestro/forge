# Model Validation (SR 11-7 / OCC 2011-12)

> Regulator-facing posture for the EML-lang pricing functions in
> this vertical. Maps Federal Reserve SR 11-7 / OCC 2011-12
> "Sound Practices for Model Risk Management" requirements onto
> the Forge artefacts that satisfy each one.

## Scope

Every `.eml` file under `industries/finance/pricing/` and
`industries/finance/greeks/` is treated as a "model" in the
SR 11-7 sense: an algorithmic input → output mapping used to
produce a quantitative output (price, sensitivity, risk number)
that informs a business decision.

This document enumerates the SR 11-7 model-risk-management
elements and points at the specific Forge artefact that
discharges each one.

## Mapping table

| SR 11-7 requirement | Forge artefact |
|---|---|
| Model definition + intended use | The header docstring of each `.eml` file |
| Input data assumptions | `requires (...)` clauses on each function |
| Output bounds / invariants | `ensures (result ...)` clauses on each function |
| Conceptual soundness | The Lean theorem named by `@verify(lean, theorem = "...")` |
| Implementation testing | `tools/equivalence/` cross-target harness — Python ↔ Rust ↔ C ↔ Lean ↔ Verilog all agree to bit-exactness on the same vectors |
| Outcome analysis | `tests/industry/test_finance.py` — output-vs-reference deltas at the canonical vector pack |
| Independent code review | The Lean proof itself: a different language, different toolchain, different proof obligation, signed off independently of the C / Rust / FPGA path |
| Ongoing performance monitoring | `eml-cost analyze` reports drift_risk; the `fp16_drift_risk` field flags any function whose chain order makes single-precision deployment unsafe |
| Documentation | The Markdown header of each `.eml` file is the model documentation; the Lean theorem statement is the formal documentation |
| Model inventory | The repository directory tree itself; every model is a single file with a single function name |

## What this is NOT

- It is not a substitute for the institution's internal model
  risk committee. Forge produces the artefacts model risk wants
  to see; the committee still has to review and approve.
- It is not a regulator-blessed model. SR 11-7 / OCC 2011-12
  govern the user's process, not the toolchain. The toolchain
  is what makes the user's process auditable.
- It is not a substitute for the institution's data quality
  controls. `requires (spot > 0.0)` enforces a domain bound at
  computation time; it does not validate the input feed.

## Suggested deliverable bundle for a model risk submission

For each pricing model going to MRM:

1. The `.eml` file (canonical source).
2. The C and Rust outputs from `eml-compile <file> --target c`
   and `--target rust` (showing implementation parity).
3. The Lean theorem statement (one of the existing `@verify`
   targets — listed in `industries/finance/certification/`
   theorem index below).
4. The numerical equivalence report from
   `tools/equivalence/cross_target_check` on the desk's
   canonical pricing-vector pack.
5. The `eml-cost analyze --json` output, evidencing chain
   order, cost class, and drift risk.
6. A short narrative document mapping the user's MRM
   questionnaire fields onto the artefacts above.

## Theorem index

| Function | Theorem | Statement (informal) |
|---|---|---|
| `black_scholes_call` | `black_scholes_call_no_arb` | Call price ≥ max(0, S − K · exp(−rT)). |
| `black_scholes_put` | `black_scholes_put_via_parity` | Put price equals call − S + K · exp(−rT). |
| `call_delta` | `bs_call_delta_in_zero_one` | Delta of a call lies in [0, 1]. |
| `put_delta` | `bs_put_delta_in_minus_one_zero` | Delta of a put lies in [−1, 0]. |
| `bs_gamma` | `bs_gamma_non_negative` | Gamma is non-negative. |
| `bs_vega` | `bs_vega_non_negative` | Vega is non-negative. |
| `call_theta` | `bs_call_theta_negative_in_money` | At-the-money call theta is non-positive. |
| `put_theta` | `bs_put_theta_via_parity` | Put-call parity for theta. |
| `sabr_atm_vol` | `sabr_atm_vol_positive` | At-the-money SABR vol is strictly positive. |
| `heston_log_spot_step` | `heston_log_spot_step_stable` | Log-spot step preserves finiteness on bounded inputs. |
| `parametric_var` | `parametric_var_monotone_in_sigma` | VaR is monotone in σ at fixed horizon and confidence. |
| `cva_cell` | `cva_cell_non_negative` | Per-bucket CVA contribution is non-negative. |
| `linear_pnl` | `stress_pnl_linear` | First-order stress P&L is bilinear in (Δ, V) and (shocks). |

The Lean source for these theorems is intentionally not inside
the Forge tree — it lives next to the rest of the EML
formalisation in `monogate-lean/MonogateEML/`. The build
guarantees: every `@verify(lean, theorem = ...)` annotation in
this vertical resolves to a sorry-free theorem in the lake build.
