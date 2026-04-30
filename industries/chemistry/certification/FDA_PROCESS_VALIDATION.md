# FDA Process Validation — Stage 1 / Stage 2 / Stage 3 evidence

> Maps the FDA 2011 Process Validation Guidance ("General
> Principles and Practices") three-stage lifecycle onto the Forge
> artefacts produced by the EML-lang chemistry primitives in this
> vertical.

## The three FDA stages

The FDA 2011 PV Guidance defines three lifecycle stages:

  - **Stage 1 — Process Design.** Design the process based on
    knowledge of the product, the manufacturing process, and the
    operating environment.
  - **Stage 2 — Process Qualification.** Confirm the process design
    is reproducible and yields material that meets specifications.
  - **Stage 3 — Continued Process Verification.** Maintain the
    process in a state of control during routine production.

EML-lang provides traceable, machine-checkable evidence at each
stage when a chemistry primitive is in the loop.

## Mapping table

| FDA stage / activity | Forge artefact |
|---|---|
| **Stage 1: Process design** | |
| Process knowledge documentation | The header docstring of each `.eml` (the equation, its derivation, its operating window) |
| Critical process parameters (CPP) identification | The `requires (...)` clauses encode the operational range; values outside the range are out-of-spec by construction |
| Critical quality attributes (CQA) bounds | The `ensures (result ...)` clauses encode the expected output range; violations are detected by the formal proof |
| Design-of-experiments support | `eml-cost analyze` reports cost class + chain order; `find_siblings` lets the chemist enumerate equivalent expressions for trade-space exploration |
| **Stage 2: Process qualification** | |
| Installation Qualification (IQ) | Compiler version + git commit hash captured in build artefact metadata |
| Operational Qualification (OQ) | `tools/equivalence/cross_target_check` proves the C/Rust/Lean/Python implementations all agree to bit-exactness on the OQ vector pack |
| Performance Qualification (PQ) | `tests/industry/test_chemistry.py` runs the OQ vectors and measures output deviation against the verified Python reference |
| Mathematical model validation | The Lean theorem itself — a different language, different toolchain, independent proof obligation |
| **Stage 3: Continued process verification** | |
| Process trending | Compile-time `drift_risk` field from `eml-cost analyze` flags any function whose chain order makes the deployed precision unsafe |
| Change control | Any change to the `.eml` requires a new commit; the cross-target equivalence harness fails-closed if outputs diverge |
| Re-validation triggers | Compiler-version pinning in CI; any toolchain change re-runs the equivalence harness |

## What this is NOT

- It is not a substitute for the manufacturer's PPQ (process
  performance qualification) batches. Forge produces evidence
  for the algorithm; PPQ produces evidence for the physical
  process.
- It is not a regulator-blessed software validation. The FDA
  does not bless toolchains; it accepts the user's documented
  validation activities.

## Suggested deliverable bundle for a Pre-Approval Inspection

For each chemistry primitive in the firm's NDA / ANDA / 505(b)(2):

1. The `.eml` file with header docstring, requires/ensures
   clauses, and `@verify` annotation.
2. The cross-target equivalence report (Stage 2 OQ evidence).
3. The Lean theorem statement and machine-verification status.
4. The PQ test report from `tests/industry/test_chemistry.py`.
5. The compile-time `eml-cost analyze --json` output for each
   target backend in production (Stage 1 design + Stage 3
   monitoring evidence).
6. A short narrative cross-walking the FDA PV Guidance
   activities onto the artefacts above.

## Selected pharmaceutical primitives — PV stage emphasis

| Function | Primary PV stage | Why |
|---|---|---|
| `one_compartment.plasma_concentration` | Stage 2 (PQ) | Dose-adjustment software; need bit-exact reproducibility across the C, Rust, Python deployments used in clinical-pharmacology workflows. |
| `two_compartment.plasma_concentration` | Stage 2 (PQ) | Same — TDM dose-adjustment software class. |
| `pk_absorption.plasma_concentration` | Stage 2 (PQ) | Bateman kernel; PO dose-prediction. |
| `dose_response.effect` | Stage 1 (design) | Used in the trial-design exposure-response stage; verified Hill-equation arithmetic prevents the IC50 ↔ EC50 sign flips that plague spreadsheet models. |
| `drug_clearance.crcl_male / female` | Stage 2 (PQ) | Cockcroft-Gault calculator; lives in dose-adjustment EMRs. |
| `arrhenius.rate_constant` | Stage 1 + Stage 3 | Stability-prediction (ICH Q1A). Drift-risk monitoring matters because exp accumulates relative error. |
| `clausius_clapeyron.predict_pressure` | Stage 1 + Stage 3 | Lyophilisation primary-drying-temperature design space; same stability-prediction concern. |
| `crystallization.power_law_growth_rate` | Stage 1 (design) | Particle-size-distribution control; CPP/CQA on G(σ). |
| `reactor_temperature.reaction_heat_load` | Stage 3 (monitoring) | Heat-balance verification for exothermic reactions; misprediction is a runaway-risk driver. |

## Linkage to ICH Q8/Q9/Q10

This PV evidence is also directly usable as ICH Q8 (Quality by
Design) "design space" evidence, ICH Q9 (Quality Risk Management)
"risk evaluation" evidence, and ICH Q10 (Pharmaceutical Quality
System) "control strategy" evidence. See `ICH_Q8_Q9_Q10.md` in
this directory for the cross-walk.
