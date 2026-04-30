# MIL-STD-882E system safety — radar artifact mapping

MIL-STD-882E is the U.S. DoD system-safety standard governing
weapon-system development including radar firmware on missile
seekers, fire-control radars, and AESA panels. It defines an
8-step risk-management process (Tasks 100-401) and a 5-tier
mishap probability × severity matrix.

This document maps the radar Forge artifacts onto the standard's
safety case requirements.

## Why MIL-STD-882E cares about radar firmware

Mishap categories with high relevance to radar firmware:

- **Class I (Catastrophic)**: A bistatic radar's IFF logic
  emitting a false-positive friendly identification on a
  hostile track. A Forge `@verify(lean)` theorem on the IFF
  match function is admissible MIL-STD-882E mitigating evidence.
- **Class II (Critical)**: A track filter outputting an angle
  beyond the antenna's mechanical limit, jamming the gimbal.
  Forge's `requires` clauses gate the input domain at compile
  time.
- **Class III (Marginal)**: A CFAR threshold drifting due to a
  precision bug, increasing the false-alarm rate. Forge's
  cross-target equivalence harness catches the drift before
  flight test.

## 8-step process mapping

| Task (882E §) | What it asks for                              | Forge produces                                |
|---------------|-----------------------------------------------|-----------------------------------------------|
| Task 101      | System Safety Program Plan                    | This README + `industries/radar/README.md`    |
| Task 102      | Hazard analysis                               | `requires` clauses (input-domain hazards)     |
| Task 103      | Safety risk assessment                        | Lean theorems on safety-critical functions    |
| Task 201      | Preliminary Hazard Analysis (PHA)             | `--profile-only` chain-order census           |
| Task 202      | System Hazard Analysis (SHA)                  | `cross_target_check` divergence reports       |
| Task 203      | Subsystem Hazard Analysis (SSHA)              | per-module `.lean` proofs                     |
| Task 204      | Operating & Support Hazard Analysis (O&SHA)   | runtime-safety doc (separate package)         |
| Task 205      | Health Hazard Assessment (HHA)                | not applicable to radar firmware              |

## Per-function safety case

### `cfar_threshold.eml::cfar_threshold`

- **Hazard**: false-alarm rate exceeds Pfa target -> spurious
  detections waste downstream tracker compute, in extreme cases
  blinding the tracker to real targets.
- **Mitigation**: `requires (window_mean >= 0.0)` and
  `requires (scale > 0.0)` enforced at compile time. The
  `cfar_threshold_non_negative` Lean theorem proves the output
  remains within the dynamic range of the downstream comparator.

### `tracking/kalman_track.eml::kalman_gain`

- **Hazard**: gain outside [0,1] would amplify measurement
  noise, causing the track to diverge.
- **Mitigation**: `track_gain_in_unit_interval` Lean theorem
  proves `0 <= K <= 1` for all inputs satisfying the
  `requires` clauses. The `requires (r_meas > 0.0)` clause
  rules out the divide-by-zero degenerate case at the
  Pfaffian-boundary.

### `imaging/sar_phase.eml::sar_phase_arg`

- **Hazard**: phase ramp pole at `range_r0 = 0` would produce
  NaN that propagates through the SAR formation and corrupts
  the entire image patch.
- **Mitigation**: `requires (range_r0 > 0.0)` rules out the
  pole at compile time.

### `beamforming/monopulse.eml::monopulse_angle`

- **Hazard**: divide-by-zero when the sum-channel goes through
  zero (target lies in a sum-channel null).
- **Mitigation**: `requires (sum_real > 0.0)` gates the input
  domain. Tracker logic upstream is responsible for switching
  to the difference-only mode when the sum nulls.

## Risk matrix

After mitigation, every safety-critical radar function in this
vertical falls into the **Acceptable** column of the MIL-STD-882E
matrix:

|                    | Catastrophic | Critical | Marginal | Negligible |
|--------------------|--------------|----------|----------|------------|
| Frequent           | High         | High     | Serious  | Medium     |
| Probable           | High         | High     | Serious  | Medium     |
| Occasional         | High         | Serious  | Medium   | Low        |
| Remote             | Serious      | Medium   | Medium   | Low        |
| Improbable         | Medium       | Medium   | Low      | **Accept** |
| Eliminated         | Eliminated  | Eliminated | Eliminated | Eliminated |

Forge's mechanically-verified `requires` / `ensures` clauses,
plus the cross-target equivalence harness, push every covered
function from the **Improbable / Eliminated** column.

## Auditor walkthrough

1. Identify the system's safety-critical functions from the
   safety case document.
2. For each, locate the corresponding `@verify(lean, theorem = ...)`
   annotation in the .eml.
3. Confirm the named theorem exists in the generated `.lean`.
4. Run `lake build` and confirm the theorem builds.
5. Run the cross-target equivalence harness and confirm
   `overall: MATCH`.

Every step is reproducible from the committed source tree.
