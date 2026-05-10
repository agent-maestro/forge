# Changelog

All notable changes to Monogate Forge will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.12.1] — 2026-05-10 (first publicly-supported PyPI release)

The repository is flipping from PRIVATE to PUBLIC on GitHub and
the wheel becomes the **first publicly-supported release** on
PyPI. The earlier `0.1.0` and `0.2.0` tags on PyPI were
exploratory placeholder pushes from internal experimentation;
this is the version the README, the documentation site, and the
monogate-engine consumer all assume people are installing.

### Added

- **`CODE_OF_CONDUCT.md`** — Contributor Covenant 2.1, contact
  `contact@monogate.dev`. GitHub's community-health widget will
  surface it.
- **`SECURITY.md`** — coordinated-disclosure policy with a
  90-day window. In scope: codegen correctness regressions,
  license-token bypass, parser/loader path-traversal or
  RCE, supply-chain attacks. Email `contact@monogate.dev`
  with subject `[forge security]`.
- **`.env.example`** — documents `MACHLIB_ROOT`, `MONOGATE_LICENSE`,
  and `MONOGATE_ZK_BIN` so external contributors know which
  environment variables the verification + Pro-license + ZK paths
  consume.

### Changed

- `pyproject.toml` author + maintainer email set to the
  project-level `contact@monogate.dev` (was a personal Gmail
  address that PyPI scrapers would index immediately).
- `tools/forge_graph.py:39` — internal Windows-machine path
  comment removed.

### Removed

- `AGENT_FORGE.md` — internal agent-handoff scaffolding that
  leaked Windows dev-machine paths and cross-repo references to
  private siblings. Untracked + gitignored.
- **`roadmap/business/` and `patents/strategy/` removed from
  git history entirely.** These directories held internal
  pricing strategy, beachhead customer profiles, certification
  partner agreements, patent filing timelines, and prior-art
  notes. The pricing tier model itself remains public — see
  `README.md`'s Free/Pro/Enterprise/Silicon table — but the
  internal sales motions and patent-filing schedule should not
  be a competitor's first stop. Files remain on disk for local
  reference; the `.gitignore` blocks future re-staging. History
  was rewritten via `git filter-repo --invert-paths` so the
  files are unrecoverable from any commit; if you cloned
  from a snapshot before this release, please re-clone.

### Fixed

- **`eml-compile --version` now reports the actual installed
  version**, sourced from `importlib.metadata.version("monogate-forge")`
  at runtime. The string was previously hardcoded as `0.4.0` in
  `tools/cli/main.py:356` and would have shipped wrong against the
  README's `pip install monogate-forge` quickstart.
- **README's `hello.rs` snippet now matches actual codegen.** The
  prior version of the README showed an aspirational `#[inline(always)]
  + debug_assert! + clean expressions` form; real output is
  `pub fn + assert! with panic message + parenthesised expressions
  + use monogate_sys::*`. Header updated to explain the doc-comment
  metadata block (chain order / cost class / drift risk / FPGA cycle
  estimate) that ships on every emitted function.

### Notes for first-time installers

```bash
pip install monogate-forge
eml-compile --version  # should print this version
eml-compile examples/hello.eml --target rust -o /tmp/hello.rs
```

If you hit an issue, please open a GitHub issue against
`agent-maestro/forge` (NOT a security report — see `SECURITY.md`
for those).

---

## [0.12.0] — 2026-05-06 (P2-P6: Verified Photonic Computing pipeline complete)

The full verified-photonic-computing pipeline ships in one
session: P1 component library (0.11.0) through P6 capstone
(this release). 51 photonic-computing-specific Lean obligations
close green; the cumulative session total reaches 115/115
across the substrate.

### Added

- **`examples/photonics/mesh/`** (P2 — neural network) — 5 EML
  files: `mzi_mesh_2x2`, `mzi_mesh_4x4`, `weight_bank_4`,
  `photonic_matmul_2x2`, `photonic_attention`. 13 closed proofs.
- **`examples/photonics/tolerance/`** (P3 — manufacturing
  tolerance + closed-loop calibration) — 4 EML files:
  `tolerance_model`, `error_propagation`, `calibration`,
  `thermal_model`. 11 closed proofs.
- **`examples/photonics/hybrid/`** (P4 — photonic-electronic
  co-design) — 3 EML files: `hybrid_layer`, `latency_model`,
  `power_model`. 8 closed proofs.
- **`examples/photonics/inference/`** (P6 — runtime + spec) —
  `photonic_transformer_sim.py` (one attention head with per-
  inference JSON proof certificate) and
  `tolerance_spec_sheet.py` (foundry-ready max-tolerance table
  with Lean theorem citations).
- **`examples/proofs/photonics/`** — 32 closed Lean files
  total (8 P1 + 5 P2 + 4 P3 + 3 P4 + 12 demo extensions).
- **`monogate-research/papers/verified-photonic-ai-inference.md`** —
  capstone paper draft.

### `hybrid_layer.eml` highlight

A single `.eml` source compiles to **all five domain backends**
simultaneously — Python (simulation), C (firmware), Lean
(proofs), SPICE (electronic netlist), KiCad (schematic) — by
mixing `@spice_*` decorators on the analog frontend with
`@verify(lean,...)` annotations on the photonic projections,
softmax, GELU, LayerNorm boundary kernels. One source, two
physical domains, one proof.

### Substrate-independence demonstrations (this release)

- `mzi_2x2_norm_witness_pythagorean`, `mzi_energy_conserved`
  (P1 mach_zehnder), and `directional_coupler_energy_conserved`
  (P1 directional_coupler) all close via `exact pythagorean
  theta`. Same proof, same axiom — three different photonic
  structures.
- The carrier-substrate proofs (`magnon_logic_constructive_at_zero`,
  `ferron_logic_constructive_at_zero`) from the parallel "How
  Does Matter Compute?" thesis use byte-identical proof
  scripts. The `pythagorean` axiom backs four physically
  unrelated wave realisations.

### Combined session totals (across all phases)

| Group              | Closed |
|--------------------|--------|
| E1 demos           | 8/8    |
| E5 maglev          | 9/9    |
| Substrate carriers | 47/47  |
| P1 photonic components | 19/19 |
| **P2 photonic neural network** | **13/13** |
| **P3 manufacturing tolerance** | **11/11** |
| **P4 photonic-electronic co-design** | **8/8** |
| **Total**          | **115/115** |

### Pipeline status (6 of 6 phases shipped)

| Phase | Status | Description |
|-------|--------|-------------|
| P1 — Component library             | ✅ shipped 0.11.0 | 19 closed proofs |
| P2 — Photonic neural network       | ✅ shipped 0.12.0 | 13 closed proofs |
| P3 — Manufacturing tolerance       | ✅ shipped 0.12.0 | 11 closed proofs |
| P4 — Photonic-electronic co-design | ✅ shipped 0.12.0 | 8 closed proofs |
| P5 — Interactive demos             | ✅ shipped 1op `3a5602c` | 5 demos at `/waves/photon` |
| P6 — Verified inference capstone   | ✅ shipped 0.12.0 | simulator + spec sheet + paper |

### What's deferred (5 honest gaps)

- Full unitarity of the 2×2 MZI rotation (needs ring algebra)
- Full sqrt(N) bound for independent errors (needs sqrt axiom)
- Convergence of the calibration loop (needs induction)
- Softmax closed-form algebraic identities (needs exp+log lemmas)
- General `1/(1+x)` bound for the Lorentzian (needs the
  pending `feat/linarith-tactic` MachLib branch)

All flagged at source. None structural.

### Tests

148/148 forge tests still green. No backend-side change.

---

## [0.11.0] — 2026-05-06 (P1: Verified Photonic Computing component library)

Phase 1 of the verified-photonic-computing roadmap ships. Eight
fundamental photonic components, each as a single `.eml` source
that compiles to C / Python / Lean from one description, with
all `@verify(lean, …)` obligations closed against MachLib.

### Added

- **`examples/photonics/components/`** — 8 photonic component
  EML files:
    * `waveguide.eml`           — `I(z) = I₀ exp(−2αz)` (chain 1)
    * `amplifier.eml`           — `G(z) = exp(g·z)` (chain 1)
    * `photodetector.eml`       — `I_ph = R · P_optical` (chain 0)
    * `modulator.eml`           — Pockels `Δn = ½ n³ r_eff E` (chain 0)
    * `phase_shifter.eml`       — `Δφ = 2π Δn L / λ` (chain 0)
    * `directional_coupler.eml` — `P_cross = sin²(κL); P_bar = cos²(κL)` (chain 1)
    * `mach_zehnder.eml`        — through/drop ports + energy conservation (chain 1)
    * `ring_resonator.eml`      — Lorentzian `T(δ) = 1/(1 + F sin²(δ/2))` (chain 1)
- **`examples/proofs/photonics/`** — 8 closed Lean files. All
  19 obligations build green via
  `lake build MachLib.Discovered.photonics.{component}`.
- **`examples/photonics/README.md`** — phase walkthrough,
  reproducibility, what each proof asserts, P2–P6 roadmap.

### Properties proven (19 / 19)

  * **Boundary conditions** — every component has at least one
    closed proof of its calibration / "off" state.
  * **Energy conservation** — directional coupler and MZI both
    close `sin² + cos² = 1` by direct application of MachLib's
    `pythagorean` axiom. The two proofs are byte-identical
    despite belonging to two different photonic structures —
    substrate-independence demonstrated again.
  * **Positivity invariants** — every "process parameter is
    positive" claim used by the calibration loop in P3 (loss
    coefficient, pump strength, Pockels coefficient, length,
    FSR, …) is closed.
  * **Linearity at zero** — for every linear component, the
    `input → output` map at zero input returns zero output.

### Combined proof totals (across all phases)

| Group              | Closed |
|--------------------|--------|
| E1 demos (rc_filter + voltage_divider)  | 8/8    |
| E5 maglev (4 modules)                   | 9/9    |
| Substrate carriers (18 demos / 6 tiers) | 47/47  |
| **P1 photonics (8 components)**         | **19/19** |
| **Total**                               | **83/83** |

### Pipeline status (1 of 6 phases delivered)

| Phase | Status | Description |
|-------|--------|-------------|
| **P1 — Component library**       | ✅ shipped 0.11.0 | 8 components / 19 closed proofs |
| P2 — Photonic neural network     | next | Reck-decomposed N×N MZI mesh + microring weight bank |
| P3 — Manufacturing tolerance     | next | Per-component error models + closed-loop calibration |
| P4 — Photonic-electronic co-design | next | One `.eml` → optical layout + electronic Verilog + proof |
| P5 — Interactive demos           | next | `1op.io/waves/photon` MZI + ring + mesh demos |
| P6 — Verified inference          | next | Photonic transformer + per-inference proof certificate |

### Tests

148/148 forge tests still green. No backend-side change.

---

## [0.10.0] — 2026-05-06 (Substrate proof: one demo per carrier tier)

The thesis claim made concrete. Six EML files — one per
non-biological tier of the "How Does Matter Compute?" map —
each captures its carrier's wave equation as a math kernel with
`@verify(lean, ...)`, compiles cleanly to C / Python / Lean from
the same source, and closes all obligations against the same
MachLib axiom set.

### Added

- **`examples/carriers/electronics/mosfet_iv.eml`** — Tier 2,
  electron carrier. MOSFET saturation current
  `I_D = ½μC(W/L)(V_GS − V_th)²`. 2 obligations closed
  (zero-overdrive zero-current, positive prefactor).
- **`examples/carriers/photonics/mach_zehnder.eml`** — Tier 3,
  photon carrier. Interferometer `I_out = I_in cos²(Δφ/2)`.
  2 obligations closed (full transmit at zero phase, cos² peak).
- **`examples/carriers/spintronics/magnon_dispersion.eml`** —
  Tier 4, magnon carrier. Spin-wave dispersion
  `ω(k) = γ(H₀ + Dk²)`. 2 obligations closed (uniform-mode FMR
  frequency, positive base frequency).
- **`examples/carriers/phononics/phonon_bandgap.eml`** — Tier 5,
  phonon carrier. Fabry-Perot transmission
  `T = 1 / (1 + F sin²(δ/2))`. 2 obligations closed (open band at
  δ=0, sin²(0)=0).
- **`examples/carriers/ferronics/ferron_propagation.eml`** —
  Tier 6, ferron carrier (experimentally demonstrated 2025).
  Damped polarization wave
  `P(x,t) = P₀ cos(kx − ωt) exp(−x/ξ)`. 2 obligations closed
  (amplitude at origin, envelope at origin).
- **`examples/carriers/quantum/phase_gate.eml`** — Tier 7,
  probability-amplitude carrier. Phase gate
  `R(φ) ↦ cos(φ), sin(φ)`. 3 obligations closed (identity at φ=0
  for both real + imag, unitarity via direct
  `MachLib.pythagorean` application).
- **`examples/proofs/carriers/`** — six closed Lean files; all
  build green via
  `lake build MachLib.Discovered.carriers.{mosfet_iv, mach_zehnder, magnon_dispersion, phonon_bandgap, ferron_propagation, phase_gate}`.

### Combined proof totals (across all phases)

| Group              | Closed |
|--------------------|--------|
| E1 demos (2 files) | 8/8    |
| E5 maglev (4 files)| 9/9    |
| Carriers (6 files) | 13/13  |
| **Total**          | **30/30** |

### What this demonstrates

> Same `@verify(lean,...)` mechanism. Same MachLib axiom set
> (`exp_zero`, `pythagorean`, `mul_pos`, `add_pos`, `cos_zero`,
> `sin_zero`, …). Six physically distinct wave carriers — each
> proving its key invariant against the same substrate.

The post-optimization shape of the EML body is what gets handed
to Lean, so writing `ensures (result == 1.0)` (matching the
folded shape) is the idiomatic v1 form. A future Lean backend
pass could reflect the optimizer's rewrites into the proof
context so the more verbose `ensures (result == cos(0)*cos(0))`
form would also close trivially.

### Tests

148 forge tests still green. No backend-side change.

---

## [0.9.0] — 2026-05-06 (Phase E5: maglev controller suite, designed before the bench)

Four EML modules (`controller`, `sensor`, `driver`, `power`)
covering the maglev levitation board. Each compiles cleanly to
SPICE / KiCad / C / Lean / JLCPCB; the math kernels carry their
safety properties as `@verify(lean, ...)` obligations that all
close against MachLib.

### Added

- **`examples/maglev/sensor.eml`** — Hall-effect signal chain.
  Anti-alias RC filter (1k + 100nF, fc ≈ 1.6 kHz). C kernels:
  `filter_tau`, `adc_voltage_to_position`, `position_to_adc_voltage`.
  Lean: 2/2 closed (`sensor_zero_offset_zero_position`,
  `sensor_filter_tau_positive`).
- **`examples/maglev/controller.eml`** — Position-control PID.
  Passive PI compensator stand-in for SPICE (no op-amps yet);
  digital PID lives in the `pid()` C kernel with refinement-typed
  inputs. Lean: 1/1 closed
  (`controller_zero_input_zero_output`).
- **`examples/maglev/driver.eml`** — Coil current driver.
  L_coil + R_coil + R_sense in series (5mH / 2Ω / 0.1Ω). C
  kernels: `coil_current_steady`, `coil_tau`, `coil_force_proxy`
  (`F = K * I²`). Lean: 4/4 closed.
- **`examples/maglev/power.eml`** — 12V rail with 220µF bulk
  + 100nF bypass + 22Ω representative load. C kernels:
  `supply_current`, `bulk_tau`. Lean: 2/2 closed.
- **`examples/proofs/maglev/`** — closed Lean files for all four
  modules. All build green via `lake build
  MachLib.Discovered.maglev.{sensor,controller,driver,power}`.

### Combined proof totals

| Phase  | Module             | Closed |
|--------|--------------------|--------|
| E4     | rc_filter          | 5/5    |
| E4     | voltage_divider    | 3/3    |
| E5     | maglev/sensor      | 2/2    |
| E5     | maglev/controller  | 1/1    |
| E5     | maglev/driver      | 4/4    |
| E5     | maglev/power       | 2/2    |
| **Sum**|                    | **17/17** |

### JLC registry extension

The maglev parts list pushed the JLCPCB BOM mapper into ranges
the v1 curated registry didn't carry (5mH coil, 0.1Ω current
sense, 220µF bulk electrolytic, 22Ω + 2Ω resistors). Added LCSC
SKUs for all five so every maglev module reports
`0 unmatched`. Total registry size now ~37 entries; the
`custom_registry=...` hatch is still the right place for
project-specific parts beyond that.

### What v1 deliberately defers (flagged at source)

  * `controller`: full PID output-bounded proof needs
    `min`/`max` ordering lemmas not in MachLib.Forge yet.
  * `driver`: `coil_tau > 0` (i.e. `L/R > 0`) needs
    `one_div_pos_of_pos` (we only have `..._nonneg_of_pos`);
    proven instead as `L * R > 0`.
  * RC monotonic decay (E4 carry-over): needs derivative axiom
    for `exp`.

All four maglev modules run end-to-end through the pipeline
(SPICE netlist + KiCad schematic + JLC BOM + C source + verified
Lean kernels). The board is fully designed and proven before the
hardware touches the bench.

### Tests

148 forge tests still green (the registry extension didn't
change BOM-format / dedup / tolerance test invariants).

---

## [0.8.0] — 2026-05-06 (Phase E4: verified circuit proofs)

The two demo circuits now carry mathematical certificates that
build cleanly against MachLib. The same EML source produces the
SPICE netlist (E1), the KiCad schematic (E2), the JLCPCB BOM (E3),
AND a proof bundle (E4) closing every `@verify(lean, ...)`
obligation.

### Added

- **`@verify(lean, ...)` kernel functions** in
  `examples/rc_filter.eml` (5 theorems) and
  `examples/voltage_divider.eml` (3 theorems). The `@spice_*`
  decorators that drive the SPICE / KiCad / JLCPCB backends sit
  alongside the `@verify` kernels untouched; each backend picks
  up only what it cares about.
- **`examples/proofs/`** directory with the **closed** Lean
  files: `rc_filter.lean` and `voltage_divider.lean`. Both build
  green against `MachLib.Forge` (Lean 4.14, no Mathlib).
  `examples/proofs/README.md` documents the reproduce-from-scratch
  workflow plus what is *not* yet proven.

### Theorems closed (8 / 8)

  * **voltage_divider** — `voltage_divider_law` (rfl after
    unfold), `voltage_divider_denom_pos` (`add_pos`),
    `voltage_divider_symmetric_half` (rfl).
  * **rc_filter** — `rc_time_constant_def`,
    `rc_steady_state_equals_input`, `rc_initial_output_zero`,
    `rc_step_response_form` (all rfl), and the only non-trivial
    one, `rc_step_response_at_zero`, which chains `div_def`,
    `zero_mul`, `exp_zero`, `sub_def`, `add_neg`, `mul_zero` to
    collapse `vin * (1 - exp(0/tau)) = 0`.

### What v1 deliberately does NOT prove

  * RC monotonic decay (`dV_out/dt < 0`) — requires a derivative
    axiom for `exp` that MachLib doesn't yet expose. Slated for
    E4.5.
  * Voltage-divider power dissipation bound — squared-quantity
    reasoning; not yet a kernel function in the EML.

Both gaps are flagged in `examples/proofs/README.md` rather than
papered over with fresh `sorry` lines.

### Not changed

  * No backend-side code change. The EML augmentation alone
    drove this phase; the Lean backend was already shipping the
    obligation skeleton with `sorry`. The novelty here is that
    the obligations now actually close.
  * Forge tests still 148 green; SPICE / KiCad / JLCPCB output
    on the augmented EML files is byte-identical to before
    (verified by the existing tests' deterministic-output cases).

---

## [0.7.0] — 2026-05-06 (Phase E3: JLCPCB BOM bundle, math → board pipeline closes)

The pipeline closes end-to-end. A single decorated EML circuit now
yields three artifacts that together cover simulate-test-manufacture:

  * `--target spice`  -> ngspice-compatible netlist (E1)
  * `--target kicad`  -> KiCad 8 .kicad_sch schematic (E2)
  * `--target jlcpcb` -> JLCPCB BOM CSV + CPL stub + manifest (E3)

Same source, three downstream stops, no duplicated component
declarations.

### Added

- **`software.manufacturing.JLCPCBMapper`** — matches each
  `@spice_<component>` decoration against a curated LCSC part
  registry and emits a JLCPCB-upload bundle:
    * `<stem>.bom.csv` — JLC web-uploader format
      (`Comment,Designator,Footprint,LCSC Part #`), with
      same-part deduplication on the designator column.
    * `<stem>.cpl.csv` — header-only stub. Real placement
      data requires PCB layout; emitting fake X/Y would
      produce a working-looking file that silently
      misassembles the board, so the stub instead carries a
      comment row pointing the user at KiCad's *Generate
      Position File*.
    * `<stem>.jlc.json` — manifest with matches, unmatched
      components (with reasons), tolerance warnings, and a
      next-steps checklist (KiCad PCB layout → CPL
      regeneration → optional `JLC2KiCad_lib` for missing
      footprints).
- **Tolerance-aware lookup.** Nearest-value matching with a 5%
  relative tolerance band, biased toward JLC Basic-tier parts
  (0603 1% resistors, X7R/X5R/C0G capacitors, 0603/0805
  inductors). Loose matches surface as warnings in the manifest,
  not silent corrections.
- **`--target jlcpcb` CLI** — requires `-o <dir>` (the bundle
  is three files); writes BOM + CPL + manifest into the
  directory. Exit code is non-zero when any component fails to
  match (so CI can gate on it). The unmatched count is also
  surfaced on stderr.
- **Custom-registry hatch.** `JLCPCBMapper(custom_registry=...)`
  accepts a tuple of `PartRegistryEntry` rows so users can
  extend the default set for parts JLC stocks that aren't yet
  in the curated list. The default registry is intentionally
  small (~30 entries) — the hatch lets a project carry its own
  alongside the source.

### What v1 deliberately defers

  * Real CPL placement data (needs PCB layout — KiCad PCB
    editor is the honest source).
  * Auto-fetching footprints via JLC2KiCad_lib — manifest
    points the user at the tool but does not invoke it (CI
    must not require network access).
  * Tolerance bands (1%, 5%) and voltage ratings on
    capacitors. Today's match is on canonical value only.
  * Multi-pin parts (op-amps, MCUs, ICs) — out of scope until
    E2.5 teaches the SPICE/KiCad layer about them.

### Refactored

- `_REF_PREFIX` (component-kind → designator-letter) and
  `CompileError` are now canonical in
  `software.backends.spice_backend`; the KiCad backend and
  JLCPCB mapper import them from there. Single source of
  truth for the three downstream consumers.

### Tests

  * **17** JLCPCB mapper cases (BOM format conformance, dedup,
    CPL-stub safety, manifest schema, tolerance accept/reject,
    custom-registry hatch, error path).
  * **148** total green across SPICE + KiCad + JLCPCB + cli +
    license.

---

## [0.6.0] — 2026-05-06 (Phase E2: KiCad backend, schematic emission)

Backend #35 ships. Phase E2 of the math-to-PCB roadmap compiles
the same `@spice_<component>`-decorated EML modules used by the
SPICE backend (E1) to KiCad 8 `.kicad_sch` schematic files. One
EML source now produces both a simulatable netlist and an
editable schematic with no duplication.

### Added

- **`@target kicad`** — emits a KiCad 8 schematic file
  (S-expression format, version `20231120`) with embedded
  `lib_symbols` stubs so the file is self-contained: KiCad
  opens it without requiring the standard `Device` /
  `Simulation_SPICE` libraries to be present on disk. Component
  types covered: R / C / L / V / I (decorator → KiCad symbol
  mapped explicitly).
- **Connectivity via labels.** Each pin gets a label whose text
  equals the net name from the SPICE decoration (`a`, `b` kw).
  KiCad treats matching label names as electrically connected,
  so no wire-routing solver is needed for v1 schematics.
- **Deterministic UUIDs.** All UUIDs (root, per-symbol, per-pin,
  per-label) derive from a SHA-256 stream seeded by the module
  name + ordered component list. Same EML in → byte-identical
  `.kicad_sch` out, so diffs between revisions show only the
  fields the user actually changed.
- **CLI wiring** — `kicad` added to `--target` choices, the help
  text ("34 → 35"), the TIERS epilog (Pro), `tools/license/
  verifier.PRO_TARGETS`, and `tools/cli/audit._BACKEND_INVOKERS`.
  Audit gracefully treats `no SPICE-decorated` modules as `skip`,
  matching the existing FPGA-target convention.
- **Tests** — 25 KiCad-specific cases covering S-expression
  well-formedness, required top-level keys, version pinning,
  lib_symbol pruning to used types only, reference-designator
  matching, label connectivity counts (e.g. `in` appears at both
  R1.pin1 and Vin.pin1), determinism, SI value pretty-printing,
  and float-precision artifact regression.

### Verification (manual — out of CI)

The backend can't run KiCad in CI; structural conformance is the
only automated check. To verify a generated schematic actually
opens cleanly:

    eml-compile examples/rc_filter.eml --target kicad -o rc_filter.kicad_sch
    # then File > Open in KiCad 8

### Deferred to E2.5 / later phases

- Multi-pin devices (op-amps, MOSFETs, ICs) — the v1 layout
  grid only knows 2-pin vertical components.
- Hierarchical sheets / sheet pins.
- PCB layout (`.kicad_pcb`) — planned for E4.
- Pretty graphics on the embedded `lib_symbol` stubs (KiCad's
  "Update Symbols from Library" replaces them with the canonical
  pretty versions on demand).

---

## [0.5.0] — 2026-05-06 (Phase E1: SPICE backend, math → manufactured PCB pipeline begins)

Backend #34 ships. Phase E1 of the
[Math-to-Manufactured-PCB roadmap](../monogate-research/roadmap/math-to-manufactured-pcb.md)
adds an ngspice-compatible netlist backend driven by decorators on
a circuit-host function. SPICE joins the Pro tier alongside the
hardware family.

### Added

- **`@target spice`** — emits an ngspice-compatible netlist text.
  Components and analyses are declared as decorators on a single
  circuit-host function:

      @spice_resistor(name = "R1",  a = "in",  b = "out", value = 1000.0)
      @spice_capacitor(name = "C1", a = "out", b = "0",   value = 1.0e-6)
      @spice_voltage(name = "Vin",  a = "in",  b = "0",   value = 5.0)
      @spice_analysis(tran = "1u 10m")
      fn circuit() -> Real { 0.0 }

  Recognised component decorators: `@spice_resistor`,
  `@spice_capacitor`, `@spice_inductor`, `@spice_voltage`,
  `@spice_current`. Recognised analyses: `tran`, `ac`, `dc`, `op`.
  Component-name prefix is enforced at compile time
  (`R1` for resistors, `Vin` for voltage sources, …) so a
  malformed deck fails before ngspice ever sees it.
- **Two example netlists** in `examples/`: `rc_filter.eml`
  (single-pole low-pass with `.tran` sweep) and
  `voltage_divider.eml` (resistive divider with `.op`).
- **License + audit wiring** — `spice` registered in
  `tools/license/verifier.PRO_TARGETS` and in
  `tools/cli/audit._BACKEND_INVOKERS`, so `--target all` covers
  it under a Pro license and the audit pipeline tracks it.
- **CLI `--target` choices, help text, and TIERS epilog** updated
  ("33 different targets" → "34", "Pro: all 33" → "Pro: all 34",
  spice listed alongside `solidity` in the Pro tier).

### Deferred to E1.5 / later phases

- MOSFET / BJT / op-amp / diode device decorators (need pin
  counts >2 plus model name).
- `@spice_subcircuit` body emission (the wrapper parses today;
  the `.SUBCKT` body is empty).
- ngspice round-trip simulation gate. The backend produces text
  that ngspice accepts; running the simulator and diffing
  predicted-vs-measured stays the user's call.
- KiCad netlist (E2), JLCPCB Gerber bridge (E3+).

---

## [0.4.0] — 2026-05-05 (Phases A–F: units + refinement types)

The "types catch what the docs say" release. Six phases shipped end
to end add a dimensional unit system (Phase A/B), refinement types
on parameters and return positions (Phase C), Lean lowering of
refinements as theorem hypotheses + conclusions (Phase D), the
auto-splicer that folds single-variable `requires` / `ensures` into
refinements (Phase C addendum), and refinement-aware lowering across
all 33 backends (Phase E.1–E.5). Phase F migrates three canonical
kernels to the new syntax, bumps the version, and ships docs.

### Added

- **Phase A — units of measurement.** `unit Hz = 1/s;` declarations
  with full SI base units (s, m, kg, A, K, mol, cd) plus derived
  units (Hz, N, Pa, J, W, V, C, Ω, …). Bracketed unit annotations
  on every type position: `Real[Hz]`, `Real[m/s^2]`, `Int[count]`.
  Dimensional inference resolves multiplications, divisions, and
  power literals; mismatches surface as `UnitTypeError` at
  compile time. A complete `lang/unit_types/` module with 1 800+
  test lines.
- **Phase B — dimensional type checker.** Pre-optimizer pass that
  walks every binop / call site / assignment / return and asserts
  unit equality (literal coercion is allowed: any numeric literal
  can become any unit). Catches Mars-Climate-Orbiter bugs at the
  type level: `velocity + mass` no longer compiles.
- **Phase C — refinement types.** `Real{x | P(x)}` syntax on
  parameters and return positions. Predicate sub-language allows
  arithmetic, comparison, boolean combinators, `abs`, `min`, `max`
  — but not transcendentals (those would require an SMT solver).
  Combined form `Real[Hz]{f | f <= 22000}` carries both the
  dimension and the value bound. Refinement entailment library
  (`lang/refinements/entail.py`) decides interval ⊆ interval
  syntactically; non-decidable cases are recorded as deferred
  obligations.
- **Phase C addendum — refinement auto-splicer.** Behind
  `--strict-refinements`, single-variable `requires (P(x))` clauses
  are folded into the parameter's refinement; single-variable
  `ensures (Q(result))` clauses become the return refinement.
  Multi-variable clauses (e.g. `rate * dt < vol * sqrt(dt)`) stay
  as `requires`. With the flag OFF, behaviour is byte-identical to
  pre-Phase-C — auto-splicing is opt-in.
- **Phase C addendum — alias refinement expansion.** `type
  AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};` propagates
  the alias's unit + refinement onto every parameter that names
  it. Always-on (not flag-gated). Cycle detection raises
  `RefinementError`.
- **Phase D — Lean refinement lowering.** Parameter refinements
  emit `(h_<param> : <pred>)` hypotheses on `theorem name_correct`;
  return refinements emit as the theorem conclusion. Lean
  `refinement_emit.py` handles binder alpha-renaming so the
  generated Lean is consistent with the function signature. Proof
  bodies try `linarith` first, fall back to `sorry` when the
  conclusion has transcendental shape.
- **Phase E.1–E.5 — refinement-aware lowering across 33 backends.**
  Every codegen target lowers `Real{x | P}` to its native guard
  form: `assert(...)` (C, C++, MATLAB), `debug_assert!(...)` (Rust),
  `assert ..., "..."` (Python), `require(...)` (Kotlin, Solidity),
  `precondition(...)` (Swift), `if (!P) throw …` (Java), explicit
  `if`/return-default in shaders (HLSL, GLSL, GLSL ES, WGSL,
  Metal), runtime checks in JavaScript and Go, comment-only
  documentation in Verilog / VHDL / Chisel, `Pre =>` aspects in
  Ada/SPARK, `assumes`/`shows` in Coq + Isabelle, and NatSpec on
  Solidity contracts. Total: 19 codegen guard backends + 6
  formal-verification hypothesis backends + 8 documentation-only
  backends.
- **Phase F kernel migrations** — three canonical kernels rewritten
  to demonstrate the new syntax end-to-end:
  - `examples/pid_controller.eml` — three `requires (abs(x) <=
    100.0)` clauses become `Real{e | abs(e) <= 100.0}` on the
    parameters.
  - `1op/public/play/eml/gravity_surfer.eml` — `up_hold`,
    `down_hold`, `dash_held`, and `t` switch to refinements; multi-
    variable invariants stay as-is.
  - `monogate-research/exploration/cat_vision/eml/rod_sensitivity.eml`
    — wavelength input gets a physiologically meaningful range
    refinement; the `[0, 1]` `ensures` becomes a return
    refinement.

### Changed

- `eml-compile --version` now prints `0.4.0`.
- `examples/audio_pole_refined.eml` is the canonical Phase C demo
  (units + refinement + multi-variable `requires`).
- `pid_controller.eml` C-backend MD5 changed from
  `3ae9cb6715bf8b5d05c05b12cfc38ff0` (pre-F) to
  `aa3b12fbd0c31c49dc9f81ed8d28022a` (post-F migration). The
  semantic guard is identical; only the message tag flipped from
  `requires (...)` to `refinement violated on <param>: (...)`.
  Pinned in
  `software/verification/lean/tests/test_refinement_lean.py::TestNonRegression::test_pid_controller_c_backend_post_e3`.

### Documentation

- New `docs/units-and-refinements.md` — focused guide covering the
  Mars Climate Orbiter motivation, unit declarations, refinement
  syntax, the auto-splicer, per-backend lowering tables, and
  migration tips.
- `docs/language-reference.md` — new "Types" subsection with
  unit-bracketed types, refinement types, and the predicate
  sub-language constraints.
- `docs/verify-guide.md` — refinements documented as the primary
  contract form; `requires` / `ensures` retained for multi-
  variable invariants.

---

## [0.1.0] — 2026-05-02 (initial public release)

First public release on PyPI. `pip install monogate-forge`.

### Highlights

- **32 compilation backends** — software (C, C++, Rust, Python, Go,
  Java, Kotlin, MATLAB, C#, Swift, JavaScript), compiler IRs
  (LLVM, WebAssembly), GPU shaders (HLSL, GLSL, GLSL ES, WGSL,
  Metal), hardware (Verilog, SystemVerilog, VHDL, Chisel/FIRRTL),
  formal verification (Lean 4, Coq, Isabelle/HOL), safety-critical
  (Ada/SPARK, AUTOSAR C, AADL, ROS 2), gaming (Luau, GDScript),
  and blockchain (Solidity with PRBMath SD59x18).
- **EML language** with chain-order constraints (`where chain_order
  <= N`), `requires`/`ensures` contracts, `@verify` and
  `@target(fpga, ...)` annotations, and a complete stdlib
  (`stdlib::math`, `stdlib::signal`, `stdlib::control`,
  `stdlib::linalg`, `stdlib::ml`, `stdlib::constants`).
- **VS Code extension** (`monogate.eml-lang` on the marketplace)
  with LSP: chain-order on hover, completions for keywords +
  builtins + stdlib, diagnostics, format-on-save, and the FPGA
  status bar showing live LUT/DSP/latency estimates.
- **Forward declarations** in HLSL and Metal output ensure every
  CALL target resolves regardless of source order or `extern fn`
  placement.
- **Cross-target equivalence harness** validates that the C, Rust,
  Python, and HDL paths produce ULP-equivalent results across the
  industry-vertical corpus.
- **Audit bundles** for Solidity contracts (`--audit-bundle`)
  produce a self-contained directory with the .sol, .spec.json,
  EML source, copies of every referenced Lean theorem, AUDITOR.md,
  and a manifest.json with sha256 of every artifact.
- **Apple toolchain validation** runs Metal (`xcrun metal -c`) and
  Swift (`swiftc -typecheck`) on the full corpus via a GitHub
  Actions macOS runner.

### Free vs Pro

- **Free tier (12 targets):** C, C++, Rust, Python, Go, Java,
  Kotlin, C#, JavaScript, WebAssembly, MATLAB, Lean. Covers
  general-purpose software, web/edge runtimes, and formal
  proofs without a license.
- **Pro tier (20 targets):** Verilog, SystemVerilog, VHDL,
  Chisel, LLVM IR, HLSL, GLSL, GLSL ES, WGSL, Metal, Swift,
  Ada/SPARK, AUTOSAR, AADL, ROS 2, Coq, Isabelle/HOL, Solidity,
  Luau, GDScript. Get a license at
  [monogateforge.com/get-started](https://monogateforge.com/get-started).

### Documentation

- `README.md` rewritten for launch.
- `docs/quickstart.md`, `docs/language-reference.md`,
  `docs/backends.md`, `docs/verify-guide.md`, `docs/fpga-guide.md`.
- `CONTRIBUTING.md` covers bug reports, feature requests, PR
  workflow, and how to add a new vertical or hardware target.

---

## [Unreleased] — 2026-04-30 (5-Phase post-baton ship)

Verticals + optimizer fixes that landed after the 2026-04-29 baton
handoff. Every change in this entry was driven by the user's
request to "do all 5 of them, break into phases if it helps".

### Added

- **Geospatial + Imaging stub verticals** (Phase 1): `geospatial/
  mercator_projection.eml` (chain-3 ln∘tan, the canonical
  3-deep pathway example) and `imaging/gamma_correct.eml` (sRGB
  per-pixel gamma + linearisation curve). Both ship with a
  README scoping the planned subdirs and chain-order budget.
- **Radar production vertical** (Phase 5): `radar/` graduates
  from stub to four-module suite with full DO-254 + MIL-STD-882E
  cert docs:
  - `doppler/range_doppler.eml` — pulse-Doppler matched-filter
    real / imag tap + per-pulse phase ramp.
  - `tracking/kalman_track.eml` — single-axis Kalman track step
    (predict, innovation, gain, position update, variance update)
    with `track_gain_in_unit_interval` Lean theorem.
  - `imaging/sar_phase.eml` — stripmap-SAR azimuth phase
    compensation (chain 2: cos∘poly + sin/cos kernels).
  - `beamforming/monopulse.eml` — amplitude-comparison monopulse
    angle estimator + Σ-channel magnitude.
  - `certification/DO_254.md` (TQL 5 tool qualification artifact
    mapping; per-module evidence table) + `MIL_STD_882E.md`
    (system-safety Tasks 101-205 mapping; risk-matrix
    walkthrough).
- **Finance build/ artifacts** (Phase 3): all 10 finance .eml
  files now ship pre-generated 9-target build/ directories
  (C, Rust, Python, LLVM IR, wasm IR, Verilog, VHDL, Chisel,
  Lean) — 90 artifact files committed under
  `industries/finance/{pricing,greeks,risk}/build/`.
- **Finance cross-target equivalence cases** (Phase 4): five
  finance functions added to `tests/equivalence/
  test_industry_verticals.py::VERTICAL_CASES` —
  `bs_d1`, `norm_cdf`, `black_scholes_call`, `call_delta`,
  `linear_pnl`. Python↔Rust bit-equivalence verified within
  1e-9 (tanh-based norm_cdf) or 1e-12 (polynomial bodies).

### Fixed

- **SuperBEST optimizer slowness on transcendental bodies with
  named module constants** (Phase 2). `recommend_form` was
  spending 30+ seconds pattern-matching expressions whose RHS
  contains user-named constants (e.g. Black-Scholes' `norm_cdf`
  uses `SQRT_2_OVER_PI`, `GELU_C3` from a `const` block). Added
  a pre-filter at `lang/optimizer/superbest.py` that bails when
  the body has any free symbols beyond the function's parameters
  (named consts can't match the literal-coefficient family
  templates). Removed the `optimize=False` workaround from
  `tests/industry/test_finance.py`. Per-Black-Scholes-compile
  time: 33s → 1.1s.
- **CSE pass placed hoisted bindings before their dependencies**
  on bodies with let-bindings. When CSE found a duplicated
  sub-expression like `alpha / f_pow_one_minus_beta` and hoisted
  it to a top-level `_cse_N`, the new binding referenced
  `f_pow_one_minus_beta` — a name introduced by a *later* let
  in the same block. C / Rust / LLVM all reject forward refs.
  `apply_cse` now inserts each hoisted let immediately before
  its first use, so dependencies are always defined first.
  This unblocks SABR LLVM/wasm compilation and produces
  declaration-correct C / Rust output across the board.

### Changed

- `industries/README.md` updated to seventeen verticals across
  eight domains; radar entry promoted from "Stub" to the full
  cross-references table.
- `tools/benchmarks/{vertical,stdlib}_baseline.json` regenerated
  to cover the new functions (123 → 136 vertical entries; stdlib
  realigned for ml.eml's elu / selu / mish / hard_* additions).

---

## [Unreleased] — 2026-04-29 (Phase 2 + 3 + 4 BATON HANDOFF SHIP)

The pre-Blackwell push that closes every non-GPU-gated deliverable
across phases 2, 3, and 4. Buildout 45% → 56%; docs 7% → 87%.

### Added

- **5 new live backends** (every target the parser advertises is now
  wired):
  - **Python backend** — AST → SymPy → Tool 5 transpile via
    `eml_cost.transpile.eml_tree_to_python`. 13 tests; matches
    closed-form sigmoid + arrhenius to 1e-12.
  - **LLVM IR backend** — portable IR text with externs for every
    libmonogate transcendental. Module-level constants inline.
    14 tests; 10/10 demo files emit clean IR.
  - **WASM backend** — chains through LLVM with `wasm32-unknown-unknown`
    triple; falls back to IR when no `llc`/`clang` on PATH. 5 tests.
  - **VHDL backend** — VHDL-2008 port of `VerilogBackend`. 4 tests;
    11/12 verticals emit; toolchain-neutral.
  - **Chisel/FIRRTL backend** — Scala source consuming chisel3.
    snake_case → CamelCase class naming. 4 tests; 11/12 verticals.
- **4 new FPGA/ASIC target stubs** matching the canonical artix7 shape:
  - `lattice.ice40` (open toolchain via yosys + nextpnr-ice40)
  - `lattice.ecp5` (open toolchain via yosys + nextpnr-ecp5)
  - `intel.cyclone10` (Quartus Prime Lite)
  - `asic.sky130` (OpenLane / SkyWater 130nm; LUT field
    reinterpreted as NAND2-equivalent gates)
  - 15 parametric tests covering canonical-key + cost-table parity.
- **Cross-backend integration matrix** at
  `tests/integration/test_backend_matrix.py` — 87 tests covering
  every demo × every backend × every FPGA vertical for the new
  hardware backends.
- **`eml-compile init` subcommand** scaffolds a new project
  (pyproject.toml + main.eml + .vscode/settings.json + .gitignore).
  10 tests including subprocess dispatch.
- **`eml-compile manpage` subcommand** emits roff(7) man page from
  argparse. Documents all 9 targets + both subcommands.
  3 tests including subcommand dispatch.
- **VS Code extension polish** (`tools/ide/vscode/`):
  - "Compile to..." picker (single command palette entry, 9 targets)
  - format-on-save via `DocumentFormattingEditProvider`
  - FPGA status bar item showing aggregate LUT/DSP/cycle counts
  - Configuration: `eml.compile.python`, `eml.fpga.target` (with
    enum of all 5 live targets)
- **JetBrains plugin scaffold** (`tools/ide/jetbrains/`):
  - File-type registration for `.eml`
  - Stub lexer + parser + syntax highlighter
  - "Compile to..." action gated to `.eml` files
  - Gradle build with `org.jetbrains.intellij` 1.17.0
- **Documentation depth** (`docs/` 1/15 → 13/15):
  - `architecture/overview.md` — full pipeline diagram + layer map
  - `architecture/optimizer_pipeline.md` — 5-pass detail
  - `architecture/profiler.md` — Pfaffian profiling reference
  - `api_reference/cli.md` — full CLI surface
  - `api_reference/backends.md` — module-level backend reference
  - `api_reference/targets.md` — FPGA/ASIC target table + extension
  - `industry_guides/{aerospace,automotive,medical,audio,robotics,ml_inference}.md`
- **CLI dispatch graduates** python/llvm/wasm/vhdl/chisel out of
  `_PLANNED_TARGETS` -- every target is now live.
- **Four new industry verticals** in `industries/`:
  - `finance/` — full Quantitative Finance scaffold. Pricing
    (`black_scholes.eml`, `heston.eml`, `sabr.eml`), Greeks
    (`delta.eml`, `gamma.eml`, `vega.eml`, `theta.eml`), risk
    (`var_monte_carlo.eml`, `cva.eml`, `stress_test.eml`), plus
    SR 11-7 (`MODEL_VALIDATION.md`) and FRTB (`FRTB_COMPLIANCE.md`)
    cert docs. The headline regulator claim is "one .eml source,
    bit-exact across C / Rust / FPGA / Lean — model risk
    committee evidence by construction".
  - `telecom/` — stub with `pulse_compression.eml` (chirped
    matched filter tap). Roadmap covers OFDM / MIMO / LDPC.
  - `radar/` — stub with `cfar_threshold.eml` (CA-CFAR threshold
    + scale). Roadmap covers Doppler / Kalman / SAR phase processing.
  - `semiconductor/` — stub with `shockley_diode.eml` (ideal
    diode I-V). Roadmap covers BSIM-class transistor models.
  - `industries/README.md` updated to fifteen verticals across
    seven domains; `tests/industry/test_finance.py` parametrizes
    parse + profile + C / Rust / Lean compile across every
    finance file; `test_other_verticals.py` extended with
    telecom / radar / semiconductor entries.
- **Phase 2.5 control-flow path** for the equivalence harness:
  - `lang/profiler/eml_interpreter.py` -- direct tree-walking
    evaluator for EML bodies that use `let mut` / `while` / assign.
    Same calling convention as a lambdified SymPy expression so the
    Python reference path treats both paths uniformly.
  - `tools/equivalence/python_runner.py` falls back to the
    interpreter when `convert_function_body` returns
    `complex_body` instead of raising
    `PythonReferenceError`. Unblocks
    `orbit::kepler_solve` for cross-target equivalence checking.
  - `tools/equivalence/rust_runner.py` coerces argv-derived f64s
    to each param's actual Rust type, so signatures with non-f64
    params (e.g. `n: u8`) compile under the dispatcher.
  - `tests/equivalence/test_complex_body.py` -- bit-exact
    Python↔Rust agreement for `kepler_solve` across three Newton
    iteration scenarios.

### Changed

- `_LIVE_TARGETS` now includes every target the parser accepts;
  `_PLANNED_TARGETS` is empty.
- `tools/cli/main.py` recognizes `init` and `manpage` as
  subcommands (early dispatch before the argparse pass).
- VS Code extension version bumped 0.1.0 → 0.2.0.

### Blackwell-gated (deferred)

- CUDA-accelerated Verilator simulation (Phase 3.3).
- Vivado synth + bitstream smoke (vendor toolchain).

---

## [Earlier] — 2026-04-29 morning (Phase 2 import system + optimizer + 7 verticals)

The full marathon push from 2026-04-28 evening through 2026-04-29
morning. **525+ tests passing**, 24 skipped (Verilator-dependent).

### Added

- **`use stdlib::name;` import system** with selective imports
  (`{a, b}`), aliases (`{lerp as interp}`), and `local::sibling`
  resolution. Loader caches by resolved file path so symlinks
  + duplicate spellings dedupe. Tree-shaker drops imported fns
  no local code reaches.
  Commits: `46adca6`, `016feb0`, `3f74c43`, `86e6254`, `956003d`
- **Real 5-pass optimizer pipeline** wired into all backends:
  inline → constant_folding → CSE → SuperBEST → tree_shake.
  Backends + FPGAAllocator default to `optimize=True`; pass
  `optimize=False` to bypass.
  - Constant folding: 51 tests, idempotent + non-mutating
  - CSE: hoists duplicate sub-trees into `let _cse_N`
  - SuperBEST: real `eml_cost.recommend_form` integration with
    pre-filters (no-exp/tanh, n_atoms > 10, irrational floats)
    so a full stdlib snapshot runs in 0.7s instead of minutes
  - Tree-shaker: drops imported fns nothing local calls
  - Inliner: substitutes single-expr same-module CALLs
  Commits: `1a51dec`, `4abe703`, `016feb0`
- **Cross-target equivalence harness** (`tools/equivalence/`) --
  operational proof of Patent #22. Runs every backend on the same
  `.eml` source + asserts ULP agreement against a SymPy reference.
  Lean target verifies structural shape + optionally `lean
  --no-deps` when toolchain present.
  Commits: `d2a4f43`, `016feb0`
- **`eml-fmt` canonical formatter** (`tools/fmt/`). Idempotent
  + AST-preserving; round-trips `use ... as alias`. CLI:
  `--fmt` / `--fmt --check` / `--fmt --write`. 31 tests.
  Commit: `4abe703`
- **`--explain` CLI** with text + JSON output + multi-target
  backend stats. Per-fn diff showing inliner / fold / CSE /
  SuperBEST effects + node-count delta + digits-saved.
  Commits: `3f74c43`, `cdd3e63`, `86e6254`
- **stdlib (6 modules, 64 fns)** -- math (15) + ml (7) + control
  (12) + signal (11) + linalg (13) + constants (16). Every
  function chain-order verified against the profiler.
  Commits: `a7ef7a4`, `cdd3e63`, `86e6254`
- **11 industry verticals** (was 6). Production-shape `.eml`
  designs spanning aerospace, automotive, defense, energy,
  medical, robotics, ML inference, audio (DSP + synthesis),
  scientific (physics), manufacturing (process control). Three
  refactored to `use stdlib::control::pid` (autopilot, motor_foc,
  infusion_pump); motor_foc additionally uses
  `use local::three_phase` for the Park + Clarke transforms.
  Commits: `46adca6`, `016feb0`, `3f74c43`, `86e6254`, `956003d`
- **Patent #14 demo** (`industries/audio/synthesis/additive_voice.eml`)
  -- 4 sin call sites + 1 exp = 5 transcendentals. FPGA allocator's
  sharing decision lights up: `sin: count=4, sharing=shared`,
  `exp: count=1, sharing=dedicated`. 7 tests pin the behaviour.
  Commit: `956003d`
- **VS Code extension** (`tools/ide/vscode/`) with inline profile
  CodeLens + chain-order diagnostics on save. Shells out to the
  Python CLI -- no parsing reimplemented in TypeScript.
  Commit: `307d077`
- **Hardware module library** (`hardware/modules/transcendental/`)
  -- 12 SCAFFOLD Verilog modules (eml_exp/ln/sin/cos/tan/sqrt/
  sinh/cosh/tanh/asin/acos/atan) with shared interface, range
  documentation, structural lint tests + Verilator hooks.
  Commit: `8b2c3c1`
- **Vertical + stdlib regression gates** (`tools/benchmarks/`).
  Per-fn baselines pin chain_order, node_count, fpga_cycles,
  mac_units, trig_units. Any optimizer change that grows a
  metric fails the test loudly. 23 vertical fns + 58 stdlib fns
  baselined. Markdown dashboard at
  `tools/benchmarks/DASHBOARD.md`.
  Commits: `cdd3e63`, `956003d`
- **CI workflow** (`.github/workflows/forge.yml`) -- ubuntu +
  windows × py3.11 + py3.12 matrix; cargo cached; separate
  Linux Verilator job runs the HW-simulation paths.
  Commit: `4abe703`
- **`getting_started.md` tutorial** walking the autopilot.eml
  vertical end to end (parse → profile → backend emits).
  Commit: `b9abf37`

### Changed

- **Stdlib `math.eml` shrunk from 21 to 15 fns**. The 6
  activation functions (sigmoid, softplus, swish, gelu, relu,
  leaky_relu) moved to a new `stdlib::ml` module. New
  `stdlib::ml::sigmoid_alt` is the SuperBEST trigger demo.
  Commit: `cdd3e63`
- **Rust backend mangles param names** that collide with
  module-level consts (Rust 2021 const-pattern shadowing
  E0005). E.g. imported `pid_integrate(... dt: f64)` no longer
  conflicts with a vertical's `const dt = ...`.
  Commit: `46adca6`
- **FPGA allocator runs `optimize_module` first** by default
  (matches backends). Without it, helper CALLs would hide the
  transcendentals from the allocator's count.
  Commit: `956003d`

### Tests

- 525+ passing across the whole suite (was 220 at session start)
- New test directories this push:
  `lang/loader/tests/`, `lang/optimizer/tests/`,
  `tests/equivalence/`, `tests/benchmarks/`,
  `tests/stdlib/`, `tools/fmt/tests/`, `tools/cli/tests/`,
  `tools/benchmarks/`

### Known papercuts

- Windows pytest stdout buffering hides the summary line in
  background-task output; exit codes still reliable
- Defender scanning adds ~90s to subprocess Python spawn; CLI
  test timeouts bumped to 240s

### Patent demos operational today

- **#22 (dual-target compilation)** -- `cross_target_check()`
  proves Rust-vs-Python ULP agreement on every stdlib + vertical fn
- **#14 (FPGA resource allocator)** -- `additive_voice.eml`
  shows sharing-vs-dedicated decision visible in plan
- **#01 (SuperBEST routing)** -- `ml::sigmoid_alt` rewrites to
  canonical sigmoid, saves 1.08 decimal digits of precision

---

## [0.1.0-pre] — 2026-04-28 (Phase 1 SHIPPED)

### Added (commits `1df5090` parser + `0099bdd` profiler)

- **Working lexer** at `lang/parser/lexer.py` — longest-match
  operator handling, line + col tracking, keyword classification
- **Working parser** at `lang/parser/parser.py` — full
  recursive-descent + Pratt expression precedence; 11/11 demo
  `.eml` files parse cleanly into typed `EMLModule` /
  `EMLFunction` / `EMLConstant` / `EMLTypeAlias` ASTs with
  source-location info on every node
- **AST → SymPy bridge** at `lang/profiler/ast_to_sympy.py` —
  handles let-binding inlining, tuple-return decomposition,
  builtin dispatch (exp/ln/sin/cos/tan/sqrt/asin/acos/atan/sinh
  /cosh/tanh/abs/clamp/eml). Functions with `let mut` / `while` /
  assignment correctly land in `complex_body` status.
- **Working profiler** at `lang/profiler/profiler.py` — every
  function gets a populated `profile` dict (chain_order,
  cost_class, eml_depth, dynamics counter, FPGA estimate,
  stability warnings, drift risk) via `eml-cost.analyze` +
  `eml-cost.analyze_dynamics`
- **AST node extensions** in `lang/parser/ast_nodes.py`:
  `Param`, `Annotation`, `WhereClause`, `EMLModule` dataclasses;
  `LET_MUT` / `ASSIGN` / `WHILE` / `BLOCK` / `EXPR_STMT` /
  `TUPLE` NodeKinds; `BUILTIN_NAMES` + `BUILTIN_TO_KIND` tables
- **66 tests passing** across `lang/parser/tests/` (43) +
  `lang/profiler/tests/` (21) + `tests/integration/` (2).
- End-to-end `parse → profile → type_check` pipeline closed.
  Type checker correctly rejects `sin(x)` against
  `chain_order <= 1` constraint.

### Phase 1 status

- 1.1 Grammar — DONE (hand-rolled parser preferred over ANTLR codegen)
- 1.2 Parser — DONE
- 1.3 Profiler + type checker — DONE
- 1.6 Domain + precision constraint INFERENCE at call sites — deferred to a later sub-phase

See `roadmap/phases/phase1_language.md` for the per-milestone
checklist and `lang/spec/EML_LANG_DESIGN.md` for the canonical
design vision.

## [Unreleased] — 2026-04-28 (post-design-doc integration)

### Added

- `lang/spec/EML_LANG_DESIGN.md` — canonical design vision
  document (full PLANNING-tier spec with rationale, syntax,
  type system, compiler architecture, 4-phase plan, patent
  implications, comparison matrix vs ladder logic / ST / MATLAB)
- `lang/spec/grammar/examples/motor_control.eml` — comprehensive
  demo from the design doc (type aliases, FPGA-targeted block,
  Lean-verified block, deliberately-warning function)
- `tools/benchmarks/versus/vs_ladder_logic.md` — full
  comparison: PID controller in 3 languages (ladder, ST,
  EML-lang); honest "where ladder still wins" section
- Python skeleton modules wired to the design doc's class
  signatures:
  - `lang/parser/` (parser, ast_nodes, type_checker, errors)
  - `lang/profiler/` (profiler, dynamics)
  - `lang/optimizer/` (superbest, fusion, cse, constant_folding)
  - `software/backends/` (c_backend, rust_backend, llvm_backend,
    python_backend, wasm_backend)
  - `software/verification/lean/LeanBackend.py`
  - `hardware/allocator/` (allocator, precision_selector)
  - `hardware/hdl_gen/verilog_backend.py`
  - `hardware/simulation/verilator_sim.py`

### Changed

- `README.md` — leads with the ladder-logic motivation; links
  to the design doc + comparison file
- `lang/spec/SPEC.md` — expanded to mirror the design doc's
  syntax + type system + profiling output
- `lang/spec/grammar/eml_lang.g4` — full grammar matching the
  design doc (typed AST, annotations, requires/ensures,
  precedence-aware expression rules, built-in catalog)
- All four `roadmap/phases/*.md` files — restructured into the
  detailed sub-session breakdowns from the design doc
  (Phase 1: 3 sessions; Phase 2: 4 sessions; Phase 3: 4 sessions;
  Phase 4: 2 sessions; total 13 sessions over 7 months)

## [0.0.1] — 2026-04-28

### Added

- Initial repository scaffold
- Top-level documentation: `README.md`, `LICENSE` (MIT), `CONTRIBUTING.md`,
  `AGENT_FORGE.md`
- Full directory tree for all 10 sections (lang, software, hardware,
  industries, patents, roadmap, tools, data, docs, tests)
- Language specification skeleton at `lang/spec/SPEC.md`
- Standard library skeleton at `lang/spec/stdlib/STDLIB.md`
- Type system documentation at `lang/spec/types/TYPES.md`
- 10 example `.eml` files at `lang/spec/grammar/examples/` (placeholder)
- C runtime header at `software/runtime/c/libmonogate.h` (23 operators)
- Patent index at `patents/index.md` (17 filed + 5 pending)
- Per-industry README at each `industries/<vertical>/`
- Roadmap master at `roadmap/README.md` with phase + industry + business plans
- CLI entry point stub at `tools/cli/main.py`
- Canonical data files at `data/` (operators.json, tower_registry.json mirrored
  from `monogate-research/data/` and `exploration/E201_extended_atlas/`)

### Notes

This is the FOUNDATIONAL SCAFFOLD release. No backend produces working
output yet; the structure is ready for development to begin in any of the
phases listed in `roadmap/phases/`.
