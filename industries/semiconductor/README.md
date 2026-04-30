# semiconductor — Semiconductor / EDA vertical

> Industry vertical scaffold. SPICE simulators, timing
> analysers, and signal-integrity tools all run transcendental
> math on top of device models. Most of those models reduce to a
> handful of canonical chains: exponential I-V curves, RC decay
> kernels, sin/cos for AC analysis. Forge can emit each as a
> verified primitive that EDA tools call into directly.

**Certification target:** IEC 60747 (semiconductor device
parameter measurement), JEDEC JESD22 (reliability test methods).
For tools used in safety-critical SoC design, IEC 61508 SIL
applies to the verification flow rather than the model itself.

**Typical chain orders:**

  - SPICE diode I-V (Shockley equation): chain 1
  - Timing analysis (exp decay): chain 1
  - Signal integrity (sin / cos + exp decay): chain 3
  - Power estimation (switching activity models): chain 1-2

## Why semiconductor belongs in EML-lang

The EDA market is dominated by Cadence, Synopsys, and Siemens
(Mentor). Their device-model libraries are commercial, opaque,
and version-locked to specific tool releases. A SPICE-accurate
diode model emitted as a verified Forge block is:

  - Open: the .eml source is auditable.
  - Portable: the same model compiles to C (for the host SPICE
    engine), to Verilog (for FPGA-accelerated SPICE), and to
    Lean (for monotonicity / asymptotic-bound theorems).
  - Drop-in: the C output exposes the same per-device-call API
    that SPICE engines already consume from BSIM source.

The pitch to the EDA team is not "replace your simulator" --
it's "use this verified block where you currently use BSIM's
hand-coded C", and let the verification pipeline tell you which
of the device parameters drive the chain order.

## Status

Stub. The `shockley_diode.eml` example below is the textbook
ideal-diode I-V curve. Full BSIM-style models (with capacitance,
temperature dependence, leakage) are roadmapped.

## Scaffold

```
industries/semiconductor/
  README.md
  shockley_diode.eml          ← illustrative ideal-diode I-V
  certification/              ← (planned) IEC 60747 mapping
  device_models/              ← (planned) BSIM-class transistors
  timing/                     ← (planned) RC delay + jitter
  power/                      ← (planned) switching-activity models
```

## Cross-references

- The eml-cost analyzer's `predict_precision_loss` (eml-cost
  >= 0.7.0) is the natural place to compute device-model
  precision envelopes; the chain-order signature carried by
  each .eml here drives that prediction.
- The audio vertical's biquad / IIR primitives share the RC
  kernel and may eventually live in a shared analog-signal
  module.
