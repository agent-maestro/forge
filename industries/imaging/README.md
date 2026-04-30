# imaging — Imaging / Computer-Vision Hardware vertical

> Industry vertical scaffold. Phone cameras, security cameras,
> autonomous-vehicle perception stacks, and astronomical CCDs
> all push their pixels through an Image Signal Processor (ISP)
> that runs transcendental math on dedicated silicon. Forge
> compiles those primitives from one `.eml` source.

**Certification target:** ISO 21434 (automotive cybersecurity for
in-vehicle camera ECUs), IEC 62366 (medical imaging device
usability), DO-254 (airborne imaging hardware).

**Typical chain orders:**

  - Lens distortion correction (polynomial + trig): chain 0–2
  - Color-space conversion (matrix + γ via exp): chain 1
  - HDR tone mapping (log/exp curves): chain 1
  - Image stabilisation (gyro fusion, Kalman): chain 3
  - Neural ISP (activations on silicon): chain 1–2

## Why imaging belongs in EML-lang

Camera ISPs are quietly some of the most expensive hardware on
the SoCs that ship in phones and cars. The pipeline is largely:

  - Bayer demosaic (linear).
  - Lens distortion correction (poly + trig).
  - Tone curve / HDR (log / exp).
  - Color space convert (matrix multiply + gamma).
  - Auto-exposure / auto-white-balance (statistical kernels).
  - Optional: neural ISP (small CNN with sigmoids / GELUs).

Today every step is hand-rolled Verilog or RTL produced by
proprietary tools. Forge's pitch: write the steps once in EML,
get C for the desk reference, Verilog for the SoC, and a Lean
theorem for the safety case (especially for automotive, where a
precision bug in a pedestrian detector is a real-world hazard).

## Status

Stub. The `gamma_correct.eml` example below is illustrative; the
full vertical (Bayer demosaic, lens distortion, HDR tone-curve,
neural ISP activations) is on the roadmap.

## Scaffold

```
industries/imaging/
  README.md
  gamma_correct.eml             ← illustrative gamma-curve mapper
  certification/                 ← (planned) ISO 21434, IEC 62366
  isp/                          ← (planned) Bayer, distortion, white balance
  hdr/                          ← (planned) tone-mapping curves
  neural/                       ← (planned) small-net ISP activations
```

## Cross-references

- The ML inference vertical's activation primitives
  (`industries/ml/inference/`) are reused by the neural-ISP
  subdir once that lands.
- The audio DSP biquad family shares the same fixed-coefficient
  pipeline shape as a tone-curve LUT; the optimizer's CSE pass
  collapses them identically.
