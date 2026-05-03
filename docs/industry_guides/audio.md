# Audio — DSP + synthesis

> Forge Pro vertical. Real-time audio kernels for filters,
> synthesizers, reverb, FFT-adjacent transforms, and the
> sample-accurate building blocks that ship inside professional
> audio software.

---

## What audio needs from a compiler

Audio DSP runs at sample rate (44.1 kHz to 192 kHz) with hard
deadlines: miss one and the output clicks. Filters need to be
provably stable. Synth voices need bounded amplitude. FFT-bin
math has to round-trip across float32, float64, and fixed-point
without drift. Forge delivers:

- **Stability proofs** — biquad filter pole-radius checks and
  amplitude bounds become Lean theorems.
- **Float / fixed equivalence** — the same source compiles to
  AVX2 / NEON intrinsics for desktop and to fixed-point Verilog
  for FPGA-based outboard gear.
- **WGSL + Metal targets** — render audio meters and visualizers
  on the GPU from the same kernel as the audio thread.

---

## What ships in the Pro tier

The audio pack covers the DSP primitives every plugin author
rewrites by hand. Typical chain orders run 0–2 (linear filters
are chain 0; oscillators with `sin` are chain 1; reverb tails
with `exp * sin` lift to chain 2). Every kernel ships with:

- A `@verify(lean)` contract proving filter stability or output
  amplitude bounds.
- An `@target(fpga, ...)` profile for hardware-accelerated
  variants (audio I/O cards, eurorack modules).
- The full backend matrix (C, Rust, JavaScript, WASM, Verilog,
  Lean) — same source compiles for AudioWorklet, JUCE plugin,
  Eurorack FPGA module, or AVX/NEON DSP code.

Coverage areas include:

- Direct-Form-I biquad family (lowpass, highpass, bandpass,
  notch, peak, shelf)
- Additive + subtractive synthesizer voices
- Reverb networks (Schroeder, Freeverb, FDN)
- Pitch shifting, time stretching, granular
- Spectral kernels (FFT-bin scaling, mel filterbank)

---

## Working with the kernels

Open a kernel and the LSP surfaces:

- Chain order + cost class for the DSP body
- Sample-rate budget on the status bar (cycles per sample at
  the active clock)
- Lean stability theorem next to `@verify(lean)` blocks
- Cross-target equivalence harness output (float32 vs fixed)

Compile to every backend in one command:

```
eml-compile <kernel>.eml --target all -o build/
```

The C lands ready for a JUCE plugin; the WASM lands ready for
an AudioWorklet; the Verilog drops into a Lattice ECP5 module.

---

## Get access

The audio kernel pack ships with **Forge Pro**. Visit
<https://monogateforge.com/get-started> for the full library.

Free tier covers the compiler and 12 software backends — write
your own audio `.eml` from scratch today.
