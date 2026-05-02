# Quickstart

Five minutes from `pip install` to your first compiled kernel.

## 1. Install

```bash
pip install monogate-forge
```

This gives you the `eml-compile` CLI. Check it works:

```bash
eml-compile --version
```

The Free tier covers C, C++, Rust, Python, Go, Java, Kotlin, Lean, and MATLAB — no license required. For the other targets (GPU shaders, FPGA, Solidity, Coq/Isabelle, safety-critical), grab a Pro license at [monogateforge.com/get-started](https://monogateforge.com/get-started).

## 2. Install the VS Code extension (optional but recommended)

```
ext install monogate.eml-lang
```

You get syntax highlighting, hover-for-chain-order, completions, diagnostics, format-on-save, and the FPGA status bar.

## 3. Write your first `.eml` file

Save this as `pid.eml`:

```eml
module pid;

const KP: Real = 1.0;
const KI: Real = 0.2;
const KD: Real = 0.3;

fn pid(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
    requires (-1.0 <= error && error <= 1.0)
{
    KP * error + KI * integral + KD * derivative
}
```

What this says:

- **`module pid;`** — names the file's module so Lean theorems and other backends namespace cleanly.
- **`const KP: Real = 1.0;`** — file-scope constants with explicit types.
- **`fn pid(...)`** — the function. Parameters and return are typed.
- **`where chain_order <= 0`** — a compile-time constraint: this function must be polynomial-only (no transcendentals). The compiler verifies it; if you accidentally call `exp` or `sin` here, it fails to compile.
- **`requires (...)`** — precondition contract. Becomes a `debug_assert!` in Rust, a runtime check in Python, and a Lean hypothesis in `pid.lean`.

## 4. Profile before compiling

```bash
eml-compile pid.eml --profile-only
```

Output:

```
pid.eml — 1 function, chain_order=0
  pid: chain_order=0  cost_class=poly  nodes=6  fp16_drift_risk=LOW
```

`chain_order=0` means there's no nested transcendental — purely polynomial. `nodes=6` is the SuperBEST-optimal node count.

## 5. Compile to one target

```bash
eml-compile pid.eml --target rust -o pid.rs
```

`pid.rs` now contains:

```rust
#[inline(always)]
pub fn pid(error: f64, integral: f64, derivative: f64) -> f64 {
    debug_assert!((-1.0_f64) <= error && error <= 1.0_f64);
    KP * error + KI * integral + KD * derivative
}
```

## 6. Compile to all targets

```bash
eml-compile pid.eml --target all -o build/
```

You now have `build/pid.c`, `build/pid.rs`, `build/pid.py`, `build/pid.lean`, `build/pid.v`, … — one file per target. The Free tier gets you 9 of these; a Pro license unlocks the rest.

## 7. See what the optimizer did

```bash
eml-compile pid.eml --explain
```

Shows per-function before/after node counts, which optimizer passes fired (constant folding, CSE, SuperBEST), and what the chain-order analyzer concluded.

## 8. Verify with Lean

The `--target lean` output is a Lean 4 file with a theorem skeleton derived from your `requires`/`ensures` clauses. Drop it into a Lean project that depends on MachLib, run `lake build`, and Lean checks the contract.

See the [verify guide](verify-guide.md) for a full walkthrough including how to discharge `sorry` placeholders.

## What next

- **[Language reference](language-reference.md)** — every keyword, builtin, and annotation.
- **[Backends](backends.md)** — every target documented with examples.
- **[FPGA guide](fpga-guide.md)** — synthesizing a kernel for an Artix-7.
- **[monogate.dev/learn/eml/intro](https://monogate.dev/learn/eml/intro)** — the guided tutorial with interactive examples.

Stuck? File a bug at [github.com/agent-maestro/forge/issues](https://github.com/agent-maestro/forge/issues).
