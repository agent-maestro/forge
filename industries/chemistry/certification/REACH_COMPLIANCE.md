# REACH Compliance — EU Chemical Substance Registration

> Maps the EU REACH (Registration, Evaluation, Authorisation,
> Restriction of Chemicals) requirements onto the EML-lang
> chemistry primitives in this vertical.

## Scope

REACH (EC 1907/2006) requires registrants to submit a technical
dossier that includes physico-chemical, toxicological, and
ecotoxicological information for each substance manufactured or
imported into the EU at ≥ 1 t/yr. For tonnages ≥ 10 t/yr the
dossier must also include a Chemical Safety Report (CSR) with
exposure assessment.

Forge primitives in this vertical are useful for two REACH
activities:

  1. **Computing physico-chemical endpoints** that go into the
     dossier (vapour pressure, partition coefficient, water
     solubility, viscosity-MW relations).
  2. **Computing exposure-modelling intermediates** that go into
     the CSR (Beer-Lambert for analytical methods, Fick diffusion
     kernels for environmental-fate modelling, BET for activated-
     carbon control measures).

## Mapping table

| REACH requirement | Forge artefact |
|---|---|
| Annex VI dossier — endpoint study summary | The `.eml` source documents the equation, its operating range, and its expected output range — directly transferable into IUCLID dossier sections |
| Annex VII–X test data quality (Klimisch reliability rating) | The Lean theorem provides Klimisch-1 ("reliable without restriction") evidence for the computational method; the cross-target equivalence harness provides the implementation-fidelity evidence |
| Read-across justification | The `eml-cost analyze` `find_siblings` enumeration exposes structural analogues; the Pfaffian profile is a candidate similarity index (early-stage, see Mathlib Khovanskii gap) |
| QSAR (quantitative structure-activity relationship) audit trail | Same: `.eml` source + Lean theorem + cross-target equivalence — every QSAR computation is byte-reproducible across reviewer toolchains |
| Chemical Safety Report (CSR) | Exposure-modelling primitives (Fick diffusion, Antoine VLE, Beer-Lambert) are byte-reproducible across registrant / authority deployments |
| Substance evaluation | All inputs to the substance-evaluation calculations are bound by `requires` clauses; out-of-envelope inputs reject at the boundary |

## Selected REACH-relevant primitives

| Function | REACH endpoint | Use |
|---|---|---|
| `clausius_clapeyron.predict_pressure` | Annex VII 7.5 (vapour pressure) | Compute vapour pressure at 25 °C from a measured value at another temperature |
| `clausius_clapeyron.boiling_point_at_pressure` | Annex VII 7.2 (boiling point) | Convert observed BP at non-standard pressure to standard 101.325 kPa |
| `arrhenius.rate_constant` | Annex VII 7.7 (water hydrolysis as a function of pH) | Temperature extrapolation of hydrolysis rate constants |
| `freundlich.adsorbed_amount` | Annex VIII 9.3.1 (sorption screening) | Soil / sediment sorption isotherm fitting |
| `langmuir.coverage` | Annex VIII 9.3.1 | Same — Langmuir form for monolayer-saturation systems |
| `bet.ratio_to_monolayer` | Annex VII 7.6 (granulometry, surface area) | BET surface-area determination |
| `fick_second_law.point_source_concentration` | Annex IX 9.3.4 (bioconcentration, environmental fate) | 1-D point-source environmental-release model |
| `mark_houwink.intrinsic_viscosity` | Annex VIII (polymer-specific) | Viscosity-average MW for polymer-CSR |
| `beer_lambert.absorbance` | Annex VI test-method analytical methods | Spectrophotometric concentration determination — Klimisch-1 instrument-independent computation |

## What this is NOT

- It is not a substitute for the registrant's CSR. REACH governs
  the registrant's process, not the toolchain.
- It is not a regulator-blessed QSAR model. The European
  Chemicals Agency (ECHA) accepts a wide range of QSAR
  evidence; Forge primitives provide the computational-fidelity
  layer, not the domain-applicability or biological-relevance
  judgement.
- It is not a substitute for the registrant's data-quality
  assessment under Klimisch reliability scoring. The toolchain
  is one input to that assessment; the underlying experimental
  data is another.

## Suggested deliverable bundle for REACH submission

For each chemistry primitive used in a REACH dossier endpoint
calculation:

1. The `.eml` source file (canonical methodology, citable in
   IUCLID).
2. The Lean theorem statement (formal-verification evidence,
   Klimisch-1 supporting documentation).
3. The cross-target equivalence report (computational-fidelity
   evidence across IUCLID, ECETOC TRA, EUSES, and proprietary
   risk-assessment platforms).
4. The `eml-cost analyze --json` output (showing chain order,
   precision needs, drift risk).
5. A short narrative cross-walking the REACH dossier sections
   onto the artefacts above.

## Relationship to other certification documents

`GMP_COMPLIANCE.md` covers pharmaceutical manufacturing-software
validation (FDA / EU Annex 15). `FDA_PROCESS_VALIDATION.md`
covers the FDA 2011 PV Guidance. `ICH_Q8_Q9_Q10.md` covers the
pharmaceutical-quality-system trio. This document covers the
EU chemicals-regulation REACH framework. The four overlap on
the formal-verification-of-the-algorithm property and diverge on
the regulator-specific submission-format requirements.
