# radar — Radar / Sonar / Lidar vertical

> Production vertical. The pulse-compression CFAR cell, the
> Doppler matched filter, the Kalman track update, the SAR
> azimuth-phase compensator, and the monopulse angle estimator
> all ship as `.eml` source — every module compiles to nine
> targets (C, Rust, Python, LLVM IR, wasm IR, Verilog, VHDL,
> Chisel, Lean) under one optimizer pass.

**Certification target:** DO-254 (airborne hardware), MIL-STD-882E
(safety; defence systems), ITU-R M.1796 (radar emissions).

**Typical chain orders:**

  - Pulse compression (matched filters): chain 1
  - Doppler processing (sin/cos/exp): chain 1
  - Kalman track update: chain 1 (one divide for the gain)
  - SAR azimuth compensation: chain 2 (cos∘poly, then sin/cos)
  - Monopulse angle: chain 1 (single arctan)

## Why radar belongs in EML-lang

Modern phased-array radars push hundreds of millions of complex
multiplies per second through FPGAs. The bottleneck is not the
arithmetic — it's the verification that the FPGA implementation
matches the algorithmic spec. The defence-prime cycle today is:

  1. Algorithm engineers prototype in MATLAB.
  2. FPGA engineers retranslate into Verilog.
  3. Test teams attempt to prove equivalence by exhaustive vector
     comparison, fail to cover the corner cases, and ship anyway.
  4. A precision bug is discovered post-deployment, requiring an
     OTA bitstream update and a fresh DO-254 audit.

Forge collapses the loop: one .eml source, one Lean theorem,
one cross-target equivalence report. The test team's evidence
package is generated, not handcrafted.

## Modules

| Module                                  | Functions                                                                | Chain |
|-----------------------------------------|--------------------------------------------------------------------------|-------|
| `cfar_threshold.eml`                    | `cfar_threshold`, `cfar_scale`                                           | 0–1   |
| `doppler/range_doppler.eml`             | `doppler_real`, `doppler_imag`, `pulse_phase`                            | 0–1   |
| `tracking/kalman_track.eml`             | `predict_position`, `innovation`, `kalman_gain`, `update_position`, `update_variance` | 0–1   |
| `imaging/sar_phase.eml`                 | `sar_phase_arg`, `sar_kernel_real`, `sar_kernel_imag`                    | 1–2   |
| `beamforming/monopulse.eml`             | `monopulse_angle`, `sum_magnitude`                                       | 1     |

Every module ships:

- A `build/` directory with all 9 backend artifacts.
- `@verify(lean, theorem = ...)` annotations on every safety-
  critical function.
- `requires` / `ensures` clauses gating input domains and bounding
  outputs.

## Certification mapping

- [`certification/DO_254.md`](certification/DO_254.md) — DO-254
  airborne hardware artifact mapping (TQL 5 tool qualification).
- [`certification/MIL_STD_882E.md`](certification/MIL_STD_882E.md)
  — MIL-STD-882E system-safety task mapping (Tasks 101–205) and
  per-function safety case.

## Cross-references

- Telecom (`industries/telecom/`) shares the FFT + matched-filter
  primitives.
- Defense (`industries/defense/`) shares the Kalman /
  state-estimation primitives.
- Aerospace (`industries/aerospace/`) shares the float-precision +
  DO-178C / DO-254 evidence flow.
