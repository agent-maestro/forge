# ML inference — bit-exact deployment

> Forge Pro vertical. MLPerf-tiny aligned kernels for the
> activations, normalizations, attention primitives, and
> quantization paths that turn a trained model into a deployable
> binary on every target — desktop, mobile, browser, FPGA.

---

## What ML inference needs from a compiler

A model that runs in PyTorch on a GPU has to ship to a phone, a
browser, an edge MCU, and a custom FPGA accelerator. Each
target has different precision (float32 vs int8 vs Q15), different
runtime (NumPy vs JAX vs Eigen vs hand-rolled C), and different
accuracy budgets. Forge delivers:

- **One source, every target** — the same `.eml` activation
  compiles to AVX2 + Eigen for desktop, to int8 for mobile, to
  WebGPU compute shaders for the browser, and to Verilog for the
  FPGA accelerator.
- **Provable accuracy** — `@verify(lean)` blocks on softmax
  monotonicity, LayerNorm bounds, and quantization error bounds.
- **SuperBEST canonical form** — patent-protected pass that
  reduces the same network shape to the same minimal node count
  regardless of how it was originally written.

---

## What ships in the Pro tier

The ML inference pack covers the activations, normalizations,
and quantization primitives every model deployment rewrites by
hand. Typical chain orders run 0–2 (linear layers are chain 0;
sigmoid / softmax / attention lift to chain 2). Every kernel
ships with:

- A `@verify(lean)` contract proving output bounds, monotonicity,
  or quantization error bounds.
- An `@target(fpga, ...)` profile for accelerator deployment.
- The full backend matrix (C, Rust, Python, JavaScript, WASM,
  Verilog, HLSL, GLSL, WGSL, Metal, Lean), plus an MLPerf-tiny
  cert template.

Coverage areas include:

- Activations: ReLU, GeLU, SiLU / Swish, sigmoid, softmax, tanh
- Normalizations: BatchNorm, LayerNorm, RMSNorm
- Loss primitives: MSE, cross-entropy, Huber
- Optimizer steps: SGD, Adam, RMSprop
- Quantization: q8 quantize / dequantize, Q15 fixed-point
- Binary classifier inference + threshold paths

---

## Working with the kernels

Open a kernel and the LSP surfaces:

- Chain order + cost class for every activation
- Per-target accuracy diff (float32 vs int8) on the status bar
- Lean accuracy / monotonicity theorem next to `@verify` blocks
- SuperBEST canonical-form node count in the right pane

Compile to every backend in one command:

```
eml-compile <kernel>.eml --target all -o build/
```

The WASM lands ready for an AudioWorklet-shaped browser
inference loop; the WGSL lands ready for a WebGPU compute
shader; the Verilog drops into a custom inference accelerator.

---

## Get access

The ML inference kernel pack ships with **Forge Pro**. Visit
<https://monogateforge.com/get-started> for the full library.

Free tier covers the compiler and 12 software backends — write
your own activation in `.eml` and compile to Python / C / WASM
/ JavaScript / Lean today.
