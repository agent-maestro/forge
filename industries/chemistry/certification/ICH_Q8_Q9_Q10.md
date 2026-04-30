# ICH Q8 / Q9 / Q10 — Quality by Design, Risk Management, Pharmaceutical QS

> Cross-walk of the ICH "modernised pharmaceutical regulation"
> trio — Q8 Pharmaceutical Development, Q9 Quality Risk Management,
> Q10 Pharmaceutical Quality System — onto the EML-lang chemistry
> primitives in this vertical.

## ICH Q8 (Pharmaceutical Development) — design space + control strategy

ICH Q8 introduces the "design space" concept: a multi-dimensional
combination and interaction of input variables and process
parameters that have been demonstrated to provide assurance of
quality. EML-lang primitives support design-space identification
and operation in three concrete ways:

| Q8 element | Forge artefact |
|---|---|
| Critical Quality Attributes (CQA) | `ensures (result ...)` clauses on each function |
| Critical Process Parameters (CPP) | `requires (...)` clauses on each function — anything outside is operating outside the design space by construction |
| Risk-based design space | `eml-cost analyze` cost-class + drift-risk fields enumerate the (precision, chain order, depth) trade space |
| Real-time release testing (RTRT) | `tools/equivalence/` proves the FPGA spectrometer firmware computes the same Beer-Lambert / Voigt absorbance as the QC HPLC's Python reference; same algorithm, different platform |
| Quality target product profile | The `@verify(lean, theorem = "...")` clause is the formal expression of the CQA |

## ICH Q9 (Quality Risk Management) — risk evaluation evidence

| Q9 element | Forge artefact |
|---|---|
| Hazard identification | `eml-cost analyze` flags any chain-order ≥ 2 expression as a higher-precision risk |
| Risk analysis | The `requires` / `ensures` clauses encode the boundary conditions of the operating envelope |
| Risk evaluation | Lean theorem proves the operating-envelope-implies-CQA-met; the proof itself is the formal risk-evaluation evidence |
| Risk control | Out-of-envelope inputs are caught by the `requires` clause at runtime (in the C / Rust / Python deployments) or at compile time (in the Lean / Verilog / VHDL deployments) |
| Risk communication | The `.eml` source is the canonical artefact; everyone (regulator, manufacturer, supplier) reads the same source |
| Risk review | Git commit history on the `.eml` file is the formal risk-review log |

## ICH Q10 (Pharmaceutical Quality System) — control strategy + lifecycle

| Q10 element | Forge artefact |
|---|---|
| Process performance and product quality monitoring | `tests/industry/test_chemistry.py` runs the canonical vector pack on every commit; CI fails if any function output deviates by more than the documented tolerance |
| CAPA (corrective and preventive action) | A failed equivalence test produces a Git issue automatically; the issue's resolution must include a new commit that restores equivalence |
| Change management | The `.eml` source is the change-management object; pull request review enforces the four-eyes principle |
| Management review | The `tools/audit/audit.py` save-points produce a periodic snapshot of every claim made about each chemistry primitive |
| Knowledge management | The header docstring + `@verify` annotation + Lean theorem together capture the institutional knowledge for every primitive |
| Lifecycle: development | Stage 1 PV — see `FDA_PROCESS_VALIDATION.md` |
| Lifecycle: technology transfer | The `.eml` source is the transfer object; sites receiving it can re-emit the C / Rust / FPGA artefacts and verify equivalence to the donor site |
| Lifecycle: commercial manufacturing | Stage 3 PV — drift_risk field flags primitives that may need precision uplift if process variability widens |
| Lifecycle: discontinuation | Source-escrow — the `.eml` file is committed to Git; future regulators can recompile the toolchain and reproduce the evidence |

## Suggested cross-references in your QbD filing

For each chemistry primitive used in a CQA-relevant calculation
in your NDA / ANDA / 505(b)(2) / Type II Drug Master File:

1. **Q8 (Pharmaceutical Development) section**: cite the `.eml`
   source, the design-space encoded by `requires`, and the CQA
   encoded by `ensures`. The `eml-cost analyze` cost-class /
   drift-risk fields are direct design-space-trade-off evidence.
2. **Q9 (Quality Risk Management) section**: cite the Lean
   theorem statement (formal risk-evaluation evidence) and the
   cross-target equivalence report (formal verification of the
   risk-control implementation across deployment platforms).
3. **Q10 (Pharmaceutical Quality System) section**: cite the CI
   pipeline that runs `tests/industry/test_chemistry.py` and the
   periodic audit save-points.

## Worked example — vancomycin TDM dose-adjustment

The two-compartment plasma concentration model
(`pharma/two_compartment.plasma_concentration`) is in the dose-
adjustment loop for vancomycin therapeutic drug monitoring.

  - **Q8 (CQA)**: AUC_24 of vancomycin in the patient's plasma
    must lie in [400, 600] mg·h/L for safety + efficacy.
  - **Q8 (design space)**: dose, k_e, V_central are inputs; the
    `requires` clause enforces physiologically plausible ranges.
  - **Q9 (risk)**: a dose miscalculation produces nephrotoxicity
    (high) or sub-therapeutic exposure (low). The Lean theorem
    `two_compartment_alpha_dominates_early` establishes the
    correct shape of the curve at the time of peak risk.
  - **Q10 (control)**: the C-backend output is byte-equal to the
    Rust-backend output is byte-equal to the Python-backend
    output (cross-target equivalence harness). The pharmacist's
    EMR uses one; the bedside infusion pump uses another; both
    are guaranteed to compute the same dose adjustment.

This is the reproducibility property that ICH Q10 demands and
that traditional spreadsheet-PK + manual review doesn't provide.
