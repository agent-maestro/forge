# Audio — DSP + synthesis

> Biquad filters, additive synthesis, FFT-adjacent kernels —
> compiled to native C, WASM (for browser playgrounds), and
> FPGA Verilog.

---

## Why audio lives in EML-lang

Pro-audio kernels are the canonical case where bit-exact
agreement between the soft DSP path and the hardware path
matters: a 1-LSB drift in a IIR filter coefficient turns
into audible artifacts after a few seconds of accumulation.

Forge ships a CORDIC-backed transcendental library with
ULP-level Verilog/C agreement (verified by Verilator on
every PR). Same source compiles to:

- **C** for VST / AU plugin distribution.
- **WASM** for the 1op.io browser playground.
- **Verilog** for hardware synth / pedalboard targets.

---

## Shipping verticals

| File                                                | What it does |
|-----------------------------------------------------|--------------|
| `industries/audio/dsp/biquad_lowpass.eml`           | Direct-Form-1 biquad filter step |
| `industries/audio/synthesis/additive_voice.eml`     | 4-sin additive voice with single-exp envelope |

`biquad_lowpass.eml` imports `stdlib::signal::biquad_step` —
the canonical DF1 formulation that survives SuperBEST
routing without rewrite.

`additive_voice.eml` is the **Patent #14** demo. Four `sin`
calls are flagged for the *shared* sharing strategy by the
allocator (since count > 2), while the lone `exp` envelope
gets a *dedicated* unit. The `--allocate` output makes the
decision visible:

```
$ eml-compile additive_voice.eml --allocate --fpga-target xilinx.artix7
Allocation plan for additive_voice
  exp    count=1  sharing=dedicated  precision=32-bit  -> 1200 LUT  4 DSP
  sin    count=4  sharing=shared     precision=32-bit  -> 1700 LUT  5 DSP
Pipeline depth: 4 stages
Throughput:     24.0 Msamples/s @ 96 MHz
```

---

## Recommended `where` clauses

For biquad coefficients you trust to stay inside their
stability region:

```eml
fn biquad_step(x: Real, x_z1: Real, x_z2: Real,
               y_z1: Real, y_z2: Real,
               b0: Real, b1: Real, b2: Real,
               a1: Real, a2: Real) -> Real
  where chain_order <= 0,
        precision: 1e-9
{
    b0*x + b1*x_z1 + b2*x_z2 - a1*y_z1 - a2*y_z2
}
```

`chain_order <= 0` is the strongest stability promise — pure
multiply-add. The optimizer's CSE pass will hoist `x_z1` /
`y_z1` shared subexpressions when this function is called in
a loop.

For envelopes / waveshapers:

```eml
fn additive_voice(t: Real, freq: Real) -> Real
  where chain_order <= 1
{
    let env = exp(-t * 5.0);
    env * (sin(2.0*PI*freq*t)
         + 0.5 * sin(4.0*PI*freq*t)
         + 0.25 * sin(6.0*PI*freq*t)
         + 0.125 * sin(8.0*PI*freq*t))
}
```

`chain_order <= 1` lets the SuperBEST pass route through
canonical `exp(-x)` and `sin(2πfx)` forms.

---

## WASM target for the browser

```bash
eml-compile additive_voice.eml --target wasm -o additive_voice.wasm
```

When `llc` or `clang` is on PATH the output is wasm32
bytecode; otherwise Forge writes the LLVM IR text and tells
you which toolchain is missing. Drop the bytecode into a Web
Audio worklet and you have a browser-native synth voice that
matches the FPGA hardware bit-for-bit.

---

## Common gotchas

- **Direct-Form-2 transposed** is worse than DF1 in fp32 —
  the SuperBEST pass will rewrite a DF2T body to DF1 and
  flag the change in `--explain`.
- **Window functions** — `stdlib::signal::wave_*` provides
  Hann / Hamming / Blackman with cost classes the optimizer
  recognizes.
- **Logarithmic gain** — use `stdlib::signal::db_to_linear`
  rather than rolling `exp(0.05 * x * log(10))`. Same math,
  but the canonical form survives SuperBEST.
