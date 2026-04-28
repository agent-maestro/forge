# Precision Types

**Status:** SCAFFOLD

A `precision <= eps` clause declares the maximum allowed output
error in ULPs or absolute units. The compiler uses
`eml-cost.predict_precision_loss` (E-193 R model) to estimate
the worst-case error of the expression and rejects the function
if the estimate exceeds the bound.

## Examples

```eml
fn cheap_sigmoid(x: f64) -> f64
  where chain_order <= 2,
        precision <= 1.0e-6      // permits aggressive approximation
{
    1.0 / (1.0 + exp(-x))
}

fn precise_sigmoid(x: f64) -> f64
  where chain_order <= 2,
        precision <= 1.0e-15     // basically full f64
{
    1.0 / (1.0 + exp(-x))
}
```

The two functions have the same body but different compile
artifacts: `cheap_sigmoid` may be compiled to a fixed-point
HW unit; `precise_sigmoid` requires f64 throughout.

## Bounds shipping

Each backend respects the bound differently:
- **C / Rust (`f64`)** — bound is checked against E-193 worst-case
  estimate; sufficient if estimate ≤ bound.
- **WASM / `f32`** — bound forces f32 → f64 promotion when needed.
- **HW (FPGA)** — bound drives bit-width selection in
  `hardware/allocator/precision_selector.py`.

## Verification

When a `@verify` block contains `precision(f(x)) <= eps`, the
Lean backend emits a theorem template (see
`software/verification/lean/templates/precision_bound.lean.j2`)
that the user fills in to PROVE the bound — converting the
estimate to a guarantee.
