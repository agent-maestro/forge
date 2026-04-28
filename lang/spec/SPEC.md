# EML-lang — Language Specification

**Version:** 0.0.1 (DRAFT)
**Status:** SCAFFOLD — semantics to be finalized

---

## Overview

EML-lang is a small declarative language for expressing real-valued
mathematical computations whose Pfaffian complexity is statically
known. Its compiler can emit either software (C / Rust / Python /
LLVM / WASM) or hardware (Verilog / VHDL / Chisel / SystemC) from
the same source.

Core principles:

1. **Math first.** The language reads like math: `sin(x) + erf(y)`,
   not bit-twiddling.
2. **Static chain-order types.** Every expression carries a
   chain-order bound the type checker enforces.
3. **One source, multiple targets.** A single `.eml` file compiles
   to executable code AND synthesizable HDL.
4. **Verifiable by construction.** `@verify` blocks emit Lean 4 /
   Z3 / CBMC artifacts.

---

## Syntax (preview)

```eml
// Module declaration
module pid_basic;

// Constants
const Kp: f64 = 0.5;
const Ki: f64 = 0.1;
const Kd: f64 = 0.05;

// Function declaration with chain-order constraint
fn pid(error: f64, integral: f64, derivative: f64) -> f64
  where chain_order <= 0
{
    Kp * error + Ki * integral + Kd * derivative
}

// Function with chain order > 0 (uses transcendentals)
fn nonlinear_gain(error: f64) -> f64
  where chain_order <= 2,
        domain: error > 0
{
    let scale = exp(-error * error);
    scale * sin(error)
}

// Verification block
@verify {
    forall e: f64 where 0 < e < 10 {
        precision(nonlinear_gain(e)) <= 1e-12
    }
}
```

---

## Type system (preview)

| Type | Meaning |
|------|---------|
| `f64`, `f32`, `f16`, `bf16` | Floating-point precisions |
| `fixed<W,F>` | Fixed-point: W total bits, F fractional |
| `chain_order <= N` | Pfaffian chain-order bound |
| `domain: <pred>` | Input domain restriction |
| `precision <= eps` | Output precision requirement |

Chain-order types compose:
- Add / sub / mul / div: `max(co(a), co(b))`
- exp, ln (real-EML primitive): chain order 1 each
- sin, cos: chain order 2 (via complex Euler)
- erf, J_0, Ai, Gamma, W: chain order ≥ 2 (per tower census)

See `types/chain_order_types.md` for the full inference rules.

---

## Standard library (preview)

The `lang/spec/stdlib/` modules ship with Forge:

| Module | Contents |
|--------|----------|
| `math` | exp, ln, sqrt, pow, abs, trig, hyp, log_b |
| `control` | PID, state-space, observer (Kalman, Luenberger) |
| `signal` | FFT, biquad, FIR, IIR, convolution |
| `linalg` | matmul, transpose, inv, eigvals (small, fixed-size) |
| `constants` | pi, e, c, h, k, G, ε₀, μ₀, etc. |

---

## Compilation pipeline

```
.eml source
    │
    ▼
lexer → parser → AST → type_checker
    │
    ▼
profiler (cost class, chain order, dynamics counter)
    │
    ▼
optimizer (SuperBEST routing, fusion, CSE, constant folding)
    │
    ├──▶ software/backends/<target>.py  ──▶ C / Rust / Python / LLVM / WASM
    │
    └──▶ hardware/allocator + hdl_gen   ──▶ Verilog / VHDL / Chisel
              │                              │
              ▼                              ▼
         FPGA targets                  Verilator simulation
       (Xilinx / Intel / Lattice)     (golden vs hardware diff)
```

`@verify` blocks branch out of the AST after the type checker and
go to `software/verification/lean/` (or `smt/` or `cbmc/`) to emit
their respective artifacts.

---

## What this spec does NOT yet cover (TODO)

- Module imports / namespacing
- Generic / parametric types
- Effect system for I/O (HDL ports vs C function args)
- Concurrency / pipelining annotations
- Unit-of-measure types (SI prefixes, dimensional analysis)
- Macro / template system

These are tracked in `roadmap/phases/phase1_language.md`.

---

## References

- The 23-operator EML family: `data/operators.json`
- The 10-tower Pfaffian census: `data/tower_registry.json`
- The 578-expression cost-profile corpus: `data/corpus_profiles.json`
- The chain-order additivity rule (Patent #15): see
  `monogate-research/exploration/9th-tower-promotion-2026-04-27/`
