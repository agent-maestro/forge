# telecom — Telecommunications baseband vertical

> Industry vertical scaffold. The 5G/6G baseband math —
> OFDM modulation, channel estimation, beamforming, LDPC /
> Turbo decoding — runs on FPGAs and runs hot. Forge compiles
> the same .eml source to verified C, Rust, Verilog, VHDL, and
> Chisel; the same source has a Lean theorem attached.

**Certification target:** 3GPP TS 38 series (5G NR), ETSI EN
303 645 (cyber security baseline for consumer IoT), FCC Part 15
(unlicensed RF emissions).

**Typical chain orders:**

  - OFDM modulation (FFT + sin/cos banks): chain 2-4
  - Channel estimation (matrix exp): chain 1
  - Beamforming (complex trig arrays): chain 2
  - Error correction (Galois field arithmetic): chain 0
  - LDPC / Turbo decoding (tanh, log-likelihood): chain 2

## Why telecom belongs in EML-lang

Today's 5G basebands ship as a stack of:

  - C reference code from the vendor.
  - HDL (Verilog or VHDL) hand-translated by FPGA engineers.
  - Validation tests that compare the C and HDL output and
    pray the equivalence holds across regression cycles.

Forge collapses that to one source. The chain-order type system
flags drift-prone primitives (LDPC tanh tables, OFDM phase rotators)
and routes them through the libmonogate runtime's drift-aware
operators. The cross-target equivalence harness is what tells the
test team that the C and HDL agree, by construction.

## Status

Stub. The `pulse_compression.eml` example below is illustrative;
the full vertical (OFDM symbol pipeline, MIMO precoding, LDPC
inner decoder) is on the roadmap once the parser ships its
fixed-size array primitive.

## Scaffold

```
industries/telecom/
  README.md
  pulse_compression.eml      ← illustrative single-channel kernel
  certification/             ← (planned) 3GPP, ETSI, FCC
  baseband/                  ← (planned) OFDM, MIMO, beamforming
  decoding/                  ← (planned) LDPC, Turbo, Polar
```

## Cross-references

- The radar vertical (`industries/radar/`) shares the FFT and
  pulse-compression primitives. The two verticals will likely
  pull from a common `lang/spec/stdlib/dsp.eml` once that module
  expands beyond the scalar biquad.
