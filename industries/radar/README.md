# radar — Radar / Sonar / Lidar vertical

> Industry vertical scaffold. Radar processors live or die on
> the speed and precision of pulse compression, Doppler
> processing, beamforming, and target-tracking math. Every
> piece of that chain runs transcendentals (sin / cos / exp /
> sqrt) on FPGAs at street prices.

**Certification target:** DO-254 (airborne hardware), MIL-STD-882E
(safety; defence systems), ITU-R M.1796 (radar emissions).

**Typical chain orders:**

  - Pulse compression (matched filters): chain 2
  - Doppler processing (FFT + exp): chain 2-3
  - Beamforming (sin/cos arrays): chain 2
  - Target tracking (Kalman filter): chain 3
  - SAR imaging (2D FFT + phase compensation): chain 3

## Why radar belongs in EML-lang

Modern phased-array radars push hundreds of millions of complex
multiplies per second through FPGAs. The bottleneck is not the
arithmetic -- it's the verification that the FPGA implementation
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

## Status

Stub. The `cfar_threshold.eml` example below is illustrative;
the full vertical (range-Doppler map, monopulse beamforming,
SAR phase history processing) is on the roadmap.

## Scaffold

```
industries/radar/
  README.md
  cfar_threshold.eml         ← illustrative single-cell CFAR
  certification/             ← (planned) DO-254, MIL-STD-882E
  doppler/                   ← (planned) FFT + exp pipelines
  tracking/                  ← (planned) Kalman, IMM
  imaging/                   ← (planned) SAR, ISAR phase processing
```

## Cross-references

- Telecom (`industries/telecom/`) shares the FFT + matched-filter
  primitives.
- Defence vertical (`industries/defense/`) shares the Kalman /
  state-estimation primitives.
