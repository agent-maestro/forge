# FRTB compliance posture

> Mapping of the EML-lang finance vertical onto the Basel
> Committee's "Fundamental Review of the Trading Book"
> (BCBS 457, January 2019; CRR3 / Basel 3.1 implementation).
> The audience for this document is a market-risk team
> seeking IMA approval or running SBA capital today.

## Why FRTB is different

FRTB replaces VaR-based market-risk capital with two parallel
regimes:

  - **SBA (Standardised Approach)** — sensitivity-based capital
    using regulator-prescribed risk weights and shocks. Every
    bank computes SBA. Forge's value-add: emit the
    delta/vega/gamma sensitivities and the curvature scenarios
    from the same source as the pricing model, with formal
    equivalence between them.

  - **IMA (Internal Models Approach)** — Expected Shortfall
    (ES) at the 97.5 % level over a stressed window, with a
    P&L attribution test (PLAT) and a backtest. To keep IMA
    desk-by-desk, the bank must show the front-office pricing
    model and the risk-engine pricing model agree numerically.
    This is exactly the cross-target equivalence Forge gives
    by construction: one .eml, multiple compiled targets, all
    bit-exact on a shared vector pack.

This document maps each FRTB clause onto the artefact that
satisfies it.

## SBA mapping

| FRTB SBA clause | Forge artefact |
|---|---|
| MAR21 — Sensitivities-based method (Δ, V, γ) | `industries/finance/greeks/{delta,vega,gamma}.eml` |
| MAR21.6 — Curvature risk (shock-based) | `industries/finance/risk/stress_test.eml` (`linear_pnl`, `quadratic_pnl`) |
| MAR21.13 — Default risk charge (DRC) | `industries/finance/risk/cva.eml` plus desk-level survival curves (institution data) |
| MAR21.91 — Aggregation across buckets | Host-side; the .eml ships the per-cell building blocks (`cva_cell`, `worst_scenario_pnl`) |

## IMA mapping

| FRTB IMA clause | Forge artefact |
|---|---|
| MAR32.5 — ES model construction | Custom; not shipped here. The ES engine consumes pricing outputs, which are the .eml files in `pricing/` |
| MAR32.21 — P&L attribution test | The cross-target equivalence harness (`tools/equivalence/cross_target_check`) is the natural source of truth for "front-office vs risk-engine prices match" — by construction they compile from the same source |
| MAR32.31 — Backtesting | Institution-specific. Forge ensures the model behaviour is reproducible across the days being backtested (no hidden version drift) |
| MAR33.5 — Non-modellable risk factors (NMRF) | Forge does not classify NMRFs; it does, however, document chain-order and drift-risk per function so the risk committee can articulate which models are conservatively shocked vs deeply modelled |

## Documentation requirements (MAR30.5)

FRTB MAR30.5 requires the bank to maintain documentation of:

  - the model's structure (formula, code, version);
  - the model's calibration;
  - the validation that the model is appropriate.

The Forge answer to each:

| MAR30.5 item | Forge artefact |
|---|---|
| Model structure | The `.eml` file is the canonical source; the Lean theorem statement formalises the headline invariant |
| Model calibration | Calibration data lives outside the .eml (model takes calibration parameters as inputs); the institution maintains its calibration ledger separately |
| Validation that the model is appropriate | The `MODEL_VALIDATION.md` mapping document plus the cross-target equivalence report; the Lean theorem proof itself is independent third-party validation by a separate toolchain |

## Notes for IMA-approval-seeking desks

Three things the supervisor will ask about that the Forge
pipeline answers cleanly:

  1. **"Are the front-office and risk pricing models identical?"**
     They compile from the same `.eml`. The cross-target
     equivalence harness in `tools/equivalence/` produces a
     bit-exact agreement report; that report is the supervisor's
     evidence.

  2. **"How do you control model version drift?"**
     The `.eml` is in version control. The Lean theorem is in
     version control. The CI pipeline rejects a commit that
     changes `.eml` semantics without a re-proof of the Lean
     theorem (the lake build fails).

  3. **"How do you handle precision changes (FP32 ↔ FP64)?"**
     `eml-cost analyze` reports `fp16_drift_risk` per function;
     functions tagged HIGH must run at FP64. Functions tagged
     LOW are explicitly authorised for FP32 deployment. The
     institution can keep this as a controlling table the
     supervisor reviews each year.

## Out of scope

- The institution's internal-loss data; Forge does not see it.
- Operational-risk capital under the SMA; that's a different
  Basel pillar.
- The institution's specific risk-factor taxonomy; the .eml
  files take risk-factor inputs, but the taxonomy lives in the
  desk's calibration tooling.
