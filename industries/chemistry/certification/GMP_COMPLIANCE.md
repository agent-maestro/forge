# GMP Compliance — Good Manufacturing Practice for Pharmaceuticals

> Regulator-facing posture for the EML-lang chemistry primitives
> in this vertical. Maps the FDA 21 CFR Part 210/211, EU GMP
> Annex 15, and ICH Q7 software / process-control requirements
> onto the Forge artefacts that satisfy each one.

## Scope

GMP applies to any software that:

- generates a number used in a release decision (assay,
  potency, content uniformity), or
- controls a critical process parameter (CPP) — temperature,
  pH, pressure, dissolved oxygen, agitation rate, dose, or
- automates an in-process control that gates a stage transition
  (sterilisation Fo, drying loss-on-drying, blending uniformity).

Every `.eml` file under `industries/chemistry/{kinetics,
thermodynamics, electrochemistry, spectroscopy, pharma,
diffusion, surface, polymer, process_control}/` is treated as
GMP-relevant when used in any of the above roles.

## Mapping table

| GMP requirement | Forge artefact |
|---|---|
| Software validation under 21 CFR 211.68 | The Lean theorem named by `@verify(lean, theorem = "...")` discharges the "intended-use" prong; the `tools/equivalence/` harness discharges the "operates as intended" prong |
| Computer Software Assurance (FDA 2022 draft) | The cross-target equivalence report from `tools/equivalence/cross_target_check` is direct CSA evidence — Python ↔ C ↔ Rust ↔ Lean all agree to bit-exactness on the canonical vector pack |
| Algorithm-bound input ranges | `requires (...)` clauses on each function are the formal expression of the operational range |
| Algorithm-bound output ranges | `ensures (result ...)` clauses on each function |
| Audit trail (21 CFR Part 11) | Git commit history on the source `.eml` file; the build artefacts in `build/` are the regenerable outputs |
| Change control | Any change to the `.eml` requires a new commit; the cross-target equivalence harness fails if the C / Rust / Lean / FPGA outputs diverge |
| Functional specification | The header docstring of each `.eml` file plus the type and constants section |
| Performance qualification (PQ) testing | `tests/industry/test_chemistry.py` — output-vs-reference deltas at the canonical vector pack |
| Disaster-recovery / source escrow | The `.eml` source is the canonical artefact; everything else is regenerable from it |

## What this is NOT

- It is not a substitute for the manufacturer's Quality Unit. GMP
  governs the user's process, not the toolchain.
- It is not a regulator-blessed system. The artefacts produced by
  Forge are evidence the user submits to the regulator; the
  regulator approves the user's filing, not the toolchain.
- It is not a substitute for the manufacturer's data-integrity
  controls (ALCOA+). `requires` clauses enforce a domain bound at
  computation time; they do not validate that the input sensor is
  calibrated, locked, or that the recording medium is tamper-
  evident.

## Suggested deliverable bundle for an inspection

For each chemistry primitive in production use:

1. The `.eml` file (canonical source).
2. The C and Rust outputs from `eml-compile <file> --target c`
   and `--target rust` (showing implementation parity across the
   language used by the firmware engineer).
3. The Lean theorem statement (formal-verification evidence).
4. The numerical equivalence report from
   `tools/equivalence/cross_target_check` against the firm's
   canonical vector pack.
5. The `eml-cost analyze --json` output, evidencing chain order,
   cost class, and drift risk for the deployed precision.
6. A short narrative document mapping the firm's QMS questionnaire
   fields onto the artefacts above.

## Theorem index — chemistry primitives

| Function | Theorem | Statement (informal) |
|---|---|---|
| `arrhenius.rate_constant` | `arrhenius_monotone_in_temperature` | k(T) is strictly increasing in T for Ea > 0. |
| `eyring.eyring_rate_constant` | `eyring_rate_positive` | k(T) > 0 always. |
| `michaelis_menten.velocity` | `michaelis_menten_saturating` | v ∈ [0, Vmax] for all S ≥ 0. |
| `hill.hill_velocity` | `hill_monotone_in_substrate` | v is monotone increasing in S. |
| `first_order.concentration_at` | `first_order_decay_monotone` | C(t) ∈ [0, C0] and is non-increasing in t. |
| `second_order.concentration_at` | `second_order_decay_monotone` | Same monotonicity in t. |
| `boltzmann.population_ratio` | `boltzmann_ratio_positive` | n_i/n_0 ∈ (0, 1] for ΔE ≥ 0. |
| `gibbs.delta_g` | `gibbs_linear_in_temperature` | ΔG is linear in T at fixed ΔH, ΔS. |
| `gibbs.equilibrium_constant` | `equilibrium_constant_positive` | K(T) > 0 always. |
| `vant_hoff.predict_k` | `vant_hoff_predict_k` | K(T2) > 0 for K(T1) > 0. |
| `clausius_clapeyron.predict_pressure` | `clausius_clapeyron_predict_p` | P(T2) > 0 for P(T1) > 0. |
| `nernst.electrode_potential` | `nernst_monotone_in_q` | E is monotone decreasing in Q. |
| `butler_volmer.current_density` | `butler_volmer_zero_at_zero_overpotential` | i(η = 0) = 0. |
| `tafel.overpotential_from_current` | `tafel_monotone_in_current` | η is monotone in i. |
| `cottrell.diffusion_current` | `cottrell_decays_with_time` | i(t) ∝ 1/√t, monotone decreasing. |
| `beer_lambert.absorbance` | `beer_lambert_linear_in_concentration` | A is linear in c. |
| `beer_lambert.transmittance` | `transmittance_in_unit_interval` | T ∈ [0, 1]. |
| `lorentzian.lorentzian_density` | `lorentzian_peak_at_centre` | Maximum at ν = ν0. |
| `gaussian_peak.gaussian_density` | `gaussian_peak_at_centre` | Maximum at ν = ν0. |
| `voigt.pseudo_voigt` | `voigt_peak_at_centre` | Maximum at ν = ν0. |
| `one_compartment.plasma_concentration` | `iv_bolus_decay_monotone` | C(t) non-increasing in t. |
| `two_compartment.plasma_concentration` | `two_compartment_alpha_dominates_early` | At small t, the α term dominates. |
| `pk_absorption.plasma_concentration` | `po_absorption_rises_then_decays` | C(t) has a single maximum. |
| `dose_response.effect` | `dose_response_saturating` | E ∈ [0, Emax]. |
| `drug_clearance.clearance` | `clearance_proportional_to_dose` | CL is linear in dose at fixed F, AUC. |
| `drug_clearance.crcl_male` | `cockcroft_gault_decreases_with_age` | CrCL is monotone decreasing in age above peak. |
| `langmuir.coverage` | `langmuir_saturating` | θ ∈ [0, 1]. |
| `freundlich.adsorbed_amount` | `freundlich_monotone_in_concentration` | q is monotone in C. |
| `bet.ratio_to_monolayer` | `bet_diverges_at_p0` | V/Vm → ∞ as P/P0 → 1. |
| `flory_huggins.delta_g_per_site` | `flory_huggins_symmetric_under_phi_swap` | Symmetric in (φ1, N1) ↔ (φ2, N2). |
| `mark_houwink.intrinsic_viscosity` | `mark_houwink_monotone_in_m` | [η] is monotone in M. |
| `fick_first_law.flux` | `fick_flux_opposes_gradient` | sign(J) = −sign(dC/dx). |
| `fick_second_law.point_source_concentration` | `diffusion_kernel_normalised` | The kernel integrates to M over all x. |
| `reactor_temperature.reaction_heat_load` | `reaction_heat_monotone_in_temperature` | q_rxn(T) monotone in T. |
| `ph_control.pH_from_concentration` | `ph_decreases_with_proton_concentration` | pH monotone decreasing in [H+]. |
| `distillation.antoine_pressure` | `antoine_increases_with_temperature` | P_sat(T) monotone in T. |
| `crystallization.power_law_growth_rate` | `growth_rate_nonneg_above_solubility` | G ≥ 0 when C ≥ C_sat. |
