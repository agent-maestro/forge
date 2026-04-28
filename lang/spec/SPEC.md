# EML-lang — Language Specification

**Version:** 0.0.1 (DRAFT)
**Status:** SCAFFOLD — semantics finalized in `EML_LANG_DESIGN.md`

> This file is the **technical reference** for syntax + semantics.
> For the high-level vision, design principles, and rationale,
> read `EML_LANG_DESIGN.md` first.

---

## Overview

EML-lang is a programming language for verified mathematical
computation. Every expression compiles to an EML tree under the
hood. The compiler:

1. **Parses** `.eml` source into a typed AST
2. **Profiles** every expression automatically (chain order, cost
   class, dynamics counter, FPGA estimate)
3. **Type-checks** chain-order constraints declared in function
   signatures
4. **Optimizes** via SuperBEST routing (default, not opt-in)
5. **Emits** to one or more targets (C / Rust / Python / LLVM /
   WASM / Verilog / VHDL / Chisel / SystemC / Lean)

The same source produces both **executable code** and
**synthesizable HDL**, with **provable precision equivalence**
between them (Patent #22).

---

## Syntax

### Constants

```eml
const Kp: Real = 2.5
const Ki: Real = 0.1
const omega: Real = 60.0    // rad/s
```

### Type aliases with chain-order constraints

```eml
type Polynomial   = Real where chain_order == 0
type SingleExp    = Real where chain_order == 1
type Stable       = Real where chain_order <= 1
type StableSignal = Real where chain_order <= 2
type Oscillatory  = Real where chain_order >= 2
type OscSignal    = Real where chain_order >= 2
```

### Functions

```eml
fn pid_output(error: Real, integral: Real, deriv: Real) -> StableSignal {
    Kp * error + Ki * integral + Kd * deriv
}
```

The compiler infers `chain_order = 0` from the body; `0 <= 2`
satisfies the `StableSignal` return type. ✓

### Annotations

```eml
@target(fpga, clock_mhz = 100, precision = float32)
fn realtime_control(sensor: Real) -> Real { ... }

@verify(lean, theorem = "pid_bounded")
fn safe_pid(error: Real) -> Real
    requires abs(error) < 1000.0
    ensures abs(result) < 50000.0
{ ... }
```

`@target` directs the compiler to emit hardware (Verilog +
synthesis-ready) with the given constraints. `@verify` emits a
Lean 4 theorem template (the proof tail is auto-attempted; falls
back to `sorry` if not closeable).

### Built-in functions

The grammar reserves these as keywords in addition to user-defined
functions:

| Keyword | Chain order contribution | Domain restriction |
|---------|--------------------------|---------------------|
| `exp(x)` | +1 | none |
| `ln(x)` | +1 | `x > 0` |
| `sin(x)` | +2 | none (real path via complex Euler) |
| `cos(x)` | +2 | none |
| `tan(x)` | +2 | `x != (n+1/2)*pi` |
| `sqrt(x)` | +1 | `x >= 0` |
| `pow(x, n)` (integer n) | 0 | none |
| `pow(x, b)` (general b) | +1 | `x > 0` |
| `eml(x, y)` | 1 (raw primitive) | `y > 0` |

Higher towers (erf, J_0, Ai, Gamma, W, Si, K-elliptic, _2F_1) come
in via `@target(import = "stdlib/special")` once the stdlib
catches up — see `lang/spec/stdlib/STDLIB.md`.

### Statements

```eml
fn example(x: Real) -> Real {
    let y = exp(x)         // let binding
    let z = sin(y * 2.0)
    z + ln(x)              // last expression is the return value
}
```

### Domain + precision constraints

```eml
fn arrhenius_rate(A: Real, Ea: Real, T: Real) -> Real
    where chain_order <= 1,
          domain: T > 0.0,
          precision <= 1.0e-12
{
    A * exp(-Ea / (8.314 * T))
}
```

The `domain:` clause is a predicate inferred / guarded at call
sites; `precision <=` is verified via `eml-cost.predict_precision_loss`
(Patent #20) and any `@verify` block.

---

## Type system

Three layers, all enforced statically:

1. **Numeric** — `f64`, `f32`, `f16`, `bf16`, `fixed<W,F>`, `int`,
   `bool`. Default: `f64` (= `Real`).
2. **Chain-order** — `chain_order <= N`, `>= N`, `== N`. The
   inferred chain order of a function body must satisfy the
   declared constraint.
3. **Domain + precision** — `domain: <pred>`, `precision <= eps`.

See `types/TYPES.md` for the full type-system overview and
`types/chain_order_types.md` for the inference rules.

---

## Profiling output (always visible)

For every function, the compiler emits a profile block:

```
PROFILE: example
  chain_order: 3
  max_path_r: 2
  eml_depth: 7
  cost_class: p3-d7-w2-c1
  dynamics: 1 oscillation, 0 decays
  nodes: 7 (SuperBEST optimal)
  siblings: ["damped oscillator (physics)",
             "FM carrier (audio)"]
  stability: ln(x) undefined for x <= 0 — domain restriction
  fpga_estimate: 2 exp + 1 ln + 1 cos + 3 MAC = 7 units
```

This is NOT opt-in. Profiling is part of compilation.

---

## Compilation targets

Software:
- **C99** via `libmonogate.h` (see `software/runtime/c/`)
- **Rust** via the `monogate-sys` crate
- **Python/NumPy** via the eml-cost Tool 5 transpiler (already shipped)
- **LLVM IR** for portability (x86, ARM, RISC-V, WASM)
- **WebAssembly** for browser deployment

Hardware:
- **Verilog** for FPGA synthesis (Vivado, Quartus)
- **VHDL** for alternative FPGA flows
- **Chisel/FIRRTL** for parameterized hardware generation
- **SystemC** for hardware simulation

Verification:
- **Lean 4** formal proofs of precision and correctness
- **Z3 / SMT** for automated constraint checking
- **CBMC** for bounded model checking of generated C

---

## What this spec does NOT yet cover (TODO)

Everything in `EML_LANG_DESIGN.md`'s "TODO" list, plus:
- Module imports / namespacing
- Generic / parametric types
- Effect system for I/O (HDL ports vs C function args)
- Concurrency / pipelining annotations
- Unit-of-measure types (SI prefixes, dimensional analysis)
- Macro / template system

Tracked in `roadmap/phases/phase1_language.md`.

---

## References

- The 23-operator EML family: `data/operators.json`
- The 10-tower Pfaffian census: `data/tower_registry.json`
- The 578-expression cost-profile corpus: `data/corpus_profiles.json`
- The chain-order additivity rule (Patent #15): see
  `monogate-research/exploration/9th-tower-promotion-2026-04-27/`
- Full design vision: `EML_LANG_DESIGN.md` (this directory)
