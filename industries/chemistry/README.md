# chemistry — Chemical & Pharmaceutical Engineering vertical

> Forge for chemistry, pharma, and process engineering. Reaction
> kinetics, thermodynamics, electrochemistry, spectroscopy,
> pharmacokinetics, and process control as `.eml` source — same file
> compiles to C, Rust, Python, Verilog, VHDL, Chisel, LLVM, and an
> associated Lean theorem.

**Certification target:** FDA 21 CFR Part 11 / Part 211 (process
validation) + ICH Q8/Q9/Q10 (pharma quality-by-design) + ICH GMP +
EU REACH (chemical-substance compliance).
**Typical chain orders:** 0–1. The math here is dominated by
`exp`, `log`, and rational functions — Arrhenius, Boltzmann,
Beer-Lambert, Michaelis-Menten, Nernst, Langmuir. Almost everything
fits in one Pfaffian chain step over a polynomial / rational
argument.

## Why chemistry belongs in EML-lang

Pharma and chemicals are the **largest market by spend** that
EML-lang has not yet targeted. The combined annual R&D + process
spend across global pharma + speciality chemicals + bulk chemicals
clears $12T+. The headline forge property here is **regulator-
acceptable formal verification of reaction-rate, dosing, and
process-control software** — software that today lives in
LabVIEW / MATLAB / Excel macros / hand-rolled C and is validated
by hand under FDA Process Validation Guidance and ICH Q8/Q9/Q10.

The pitch:

  - One source of truth (`.eml`) for the physical-chemistry math.
  - A Lean theorem attached to every callable: monotonicity in
    temperature, dose-response saturation, mass-balance
    invariants, etc.
  - The same source emits the C reference (process-control PLC),
    the FPGA bitstream (real-time spectroscopy DSP), and the
    regulator-facing PDF (FDA 21 CFR Part 11 audit trail).
  - Bit-exact equivalence across backends — quality-by-design
    teams stop arguing about which language is canonical.

The audience is the process-engineering and pharma-development
teams at Big Pharma, generic manufacturers, contract development
and manufacturing organisations (CDMOs), bulk and speciality
chemical producers, and the food-processing arms of CPG companies.

## Subdirectories

| Path | Family | Headline files | Chain order |
|------|--------|----------------|-------------|
| `kinetics/` | Reaction-rate laws | `arrhenius.eml`, `eyring.eml`, `michaelis_menten.eml`, `hill.eml`, `first_order.eml`, `second_order.eml` | 0–1 |
| `thermodynamics/` | Equilibrium + statistical mechanics | `boltzmann.eml`, `gibbs.eml`, `vant_hoff.eml`, `clausius_clapeyron.eml` | 0–1 |
| `electrochemistry/` | Electrode kinetics + potentials | `nernst.eml`, `butler_volmer.eml`, `tafel.eml`, `cottrell.eml` | 0–1 |
| `spectroscopy/` | Absorbance + lineshapes | `beer_lambert.eml`, `lorentzian.eml`, `gaussian_peak.eml`, `voigt.eml` | 0–1 |
| `pharma/` | Pharmacokinetics + dose-response | `one_compartment.eml`, `two_compartment.eml`, `dose_response.eml`, `drug_clearance.eml`, `pk_absorption.eml` | 0–1 |
| `diffusion/` | Mass transport | `fick_first_law.eml`, `fick_second_law.eml` | 0–1 |
| `surface/` | Adsorption isotherms | `langmuir.eml`, `freundlich.eml`, `bet.eml` | 0–1 |
| `polymer/` | Polymer thermodynamics + viscometry | `flory_huggins.eml`, `mark_houwink.eml` | 0–1 |
| `process_control/` | Online process loops | `reactor_temperature.eml`, `ph_control.eml`, `distillation.eml`, `crystallization.eml` | 0–1 |
| `certification/` | Regulator-facing docs | `GMP_COMPLIANCE.md`, `FDA_PROCESS_VALIDATION.md`, `ICH_Q8_Q9_Q10.md`, `REACH_COMPLIANCE.md` | n/a |

## Numerical notes

The chemistry stack lives almost entirely in the
`exp / log / sqrt / pow` corner of EML's stdlib. Two things make
this vertical numerically friendly:

  1. **Inputs are physically bounded.** Temperatures live in
     `[200 K, 2000 K]`, concentrations in `[0, c_sat]`, dose in
     `[0, MTD]`. The `requires` clauses on every callable encode
     these bounds, and the resulting chain-1 expression
     (`exp(-Ea/(R*T))` and friends) never enters the tails where
     `f64` precision matters. f32 is acceptable for most lab and
     plant-floor work; pharma dosing pins to f64.
  2. **Most of the "complicated" curves degenerate to chain 0
     after `where` analysis.** Michaelis-Menten, Hill (integer
     `n`), Langmuir, BET, Lorentzian — all rational. The chain
     order rises only when an `exp` or `log` enters explicitly
     (Arrhenius, Boltzmann, Nernst, Beer-Lambert, Antoine VLE).

The Voigt profile is the lone outlier — a true convolution of
Gaussian + Lorentzian. We ship the Faddeeva-approximation form
(chain 1: a polynomial-in-`erf`-like approximation), which is the
form spectroscopy software actually uses in production.

## Adding an application

1. Pick the right subdirectory (or open a new one if the model
   doesn't fit kinetics / thermo / electrochem / spectroscopy /
   pharma / diffusion / surface / polymer / process control).
2. Write a `<name>.eml` file with chain-order + domain +
   precision declarations.
3. Add the regulator-facing theorem statement in
   `certification/` if the function is in production use under
   GMP, FDA Process Validation, or ICH Q8/Q9/Q10.
4. Add a test in `tests/industry/test_chemistry.py`.

## Cross-references

- Stdlib transcendentals (`exp`, `log`, `sqrt`, `pow`) come from
  `lang/spec/stdlib/math.eml`.
- The cross-target equivalence harness at `tools/equivalence/`
  produces the bit-exact agreement claim that GMP / FDA Process
  Validation auditors look for.
- The certification posture mirrors `industries/medical/`
  (IEC 62304) and `industries/aerospace/` (DO-178C) — same
  procedural shape, different domain content.
