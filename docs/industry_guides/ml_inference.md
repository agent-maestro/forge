# ML inference — bit-exact deployment

> The SuperBEST canonical-form pass means you can write a
> classifier in EML-lang and ship it to CPU, FPGA, ASIC, and
> WebAssembly — all with bit-equivalent inference paths.

---

## Why ML inference lives in EML-lang

Embedded ML deployment lives or dies on numerical agreement
across runtimes. A model that works on the dev box but
mis-classifies in fp16 on the edge inference accelerator is
a fire drill nobody wants to run.

Forge fixes this structurally: the same `.eml` source produces
the C inference path (deployable as a `.so`), the LLVM IR (for
WebAssembly browser deployment), and the Verilog (for FPGA
inference accelerators). Patent #01's SuperBEST routing
guarantees that any function expressible as a sigmoid +
weighted sum gets the *same* canonical form regardless of
target — no per-target rewrites, no inadvertent precision
loss.

---

## Shipping vertical

`industries/ml/inference/binary_classifier.eml` is the
**Patent #01** demo. The function uses `sigmoid_alt` (an
algebraically-equivalent but numerically inferior form of
sigmoid) on input; the SuperBEST pass rewrites to the
canonical `1 / (1 + exp(-x))` form, saving 1.08 decimal
digits of precision.

```bash
$ eml-compile industries/ml/inference/binary_classifier.eml --explain --json
{
  "name": "classify",
  "passes": {
    "superbest_module": {
      "fired":         true,
      "family":        "sigmoid_tanh_form",
      "digits_saved":  1.08,
      "before_score":  3.4,
      "after_score":   2.32
    }
  }
}
```

---

## Recommended `where` clauses

For a classifier that has to survive int8 quantization
downstream, keep the chain order low and bound the input
domain:

```eml
fn classify(features: Real, weight: Real, bias: Real) -> Real
  where chain_order <= 1,
        domain: features > -10.0 && features < 10.0,
        domain: weight   > -1.0  && weight   < 1.0,
        domain: bias     > -1.0  && bias     < 1.0,
        precision: 1e-6
{
    sigmoid(weight * features + bias)
}
```

Real classifiers are wider than this, but the same shape
holds: `chain_order <= 1` for a single-layer classifier,
`<= 2` for an MLP with bounded activations, `<= 3` for any
function that nests `tanh` inside `exp` (which the SuperBEST
pass will likely rewrite away).

---

## Targeting the browser

```bash
eml-compile binary_classifier.eml --target wasm -o classifier.wasm
```

The output is a wasm32 module callable from JavaScript via
the standard `WebAssembly.Module` API. Drop it into a 1op.io
playground page and you have a browser-native classifier
that runs at native speed and matches the C build bit-for-bit.

When neither `llc` nor `clang` is on PATH the CLI emits the
LLVM IR instead and tells you which toolchain to install.

---

## FPGA inference

For an FPGA accelerator running tens of thousands of
inferences per second, target `lattice.ecp5` (open
toolchain) or `xilinx.artix7` (Vivado). The allocator
budgets:

- ~1 sigmoid unit per parallel inference lane.
- ~1 MAC per weight per lane (fully unrolled) or ~1 MAC per
  lane (sequential).
- 0 BRAM unless you instantiate the weight ROM, in which case
  the allocator picks the smallest BRAM macro that fits.

```bash
eml-compile binary_classifier.eml --allocate --fpga-target lattice.ecp5
```

---

## Common gotchas

- **softmax** — the canonical form is `exp(x_i) / sum(exp(x))`,
  but for numerical stability subtract the max before
  exp-ing. The optimizer recognizes the pattern and emits the
  stabilized form automatically.
- **GELU vs ReLU** — both live in `stdlib::ml`. GELU has a
  SuperBEST canonical form (the *tanh* approximation) that's
  ~0.6 digits more stable than the closed form on fp32.
- **Quantization-aware training** — Forge doesn't yet emit
  per-target quantization; that's a Phase 2 deliverable. For
  now, use the `precision` clause to specify your target's
  ULP and the optimizer will pick the safest canonical form
  that fits.
