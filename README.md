# Monogate Forge

> **EML-Lang: a programming language for verified mathematical
> computation. Every expression is an EML tree. The compiler
> optimizes via SuperBEST routing, verifies via Lean, and targets
> both software (C / Rust / Python / LLVM) AND hardware (FPGA /
> ASIC) from one source.**

**Status:** FOUNDATIONAL SCAFFOLD (v0.0.1) — under development
**Repository:** local only (private project)
**License:** MIT for compiler, patents cover specific methods

---

## Why this exists

Industrial automation today is stuck on ladder logic — Boolean rungs
from the 1960s that can't express transcendental functions, can't
prove correctness, can't optimize node count, and treat PID loops
as black boxes. Structured Text is marginally better but still
opaque. MATLAB/Simulink + HDL Coder will get you to FPGA but the
math is hidden inside vendor library calls and you have no formal
proof of precision.

EML-Lang makes every mathematical operation visible, measurable,
optimizable, and formally verifiable.

```
EML-LANG:
  control pid(error: Real, integral: Real, derivative: Real) -> Real {
    Kp * error + Ki * integral + Kd * derivative
  }

  // Compiler tells you (always, not opt-in):
  //   chain_order: 0 (purely polynomial — no transcendental risk)
  //   total_nodes: 6 (SuperBEST optimal)
  //   precision: bounded by Lean theorem pid_relerr_bound
  //   FPGA: 6 MAC units, 0 transcendental units needed
```

vs.

```
LADDER LOGIC:
  |---[ EN ]---[ PID_BLOCK ]---( OUT )---|

  What's inside PID_BLOCK? Nobody knows.
  What precision does it use? Vendor-dependent.
  Is it optimal? No way to measure.
  Is it correct? Hope so.
```

See `tools/benchmarks/versus/vs_ladder_logic.md` for the full
comparison and `lang/spec/EML_LANG_DESIGN.md` for the canonical
language design document.

## Compilation pipeline

```
.eml source
    │
    ▼
PARSER → PROFILER → TYPE CHECK → OPTIMIZER (SuperBEST)
    │
    ├──▶ SOFTWARE: C99 / Rust / Python / LLVM IR / WebAssembly
    │
    ├──▶ HARDWARE: Verilog / VHDL / Chisel / SystemC
    │           (FPGA allocator selects per-unit precision +
    │            sharing + pipelining — Patent #14)
    │
    └──▶ VERIFY:  Lean 4 theorems / Z3 SMT / CBMC bounded model check
```

Profiling is **automatic** (every expression always carries its
chain order, cost class, dynamics counter). The optimizer is
SuperBEST routing by default. Chain-order types are enforced at
compile time. The compiler never silently loses precision.

## Quick start (planned)

```bash
# Install
pip install monogate-forge

# Compile a basic PID controller to C
eml-compile lang/spec/grammar/examples/pid_basic.eml --target c -o pid.c

# Profile any .eml expression (no compilation)
eml-compile lang/spec/grammar/examples/sigmoid.eml --profile-only

# Compile to Verilog and simulate against the C reference
eml-compile lang/spec/grammar/examples/motor_foc.eml --target verilog -o foc.v
eml-compile lang/spec/grammar/examples/motor_foc.eml --fpga-sim

# Generate Lean 4 verification artifact
eml-compile aerospace/flight_control/autopilot.eml --verify
```

## Repository layout

| Directory | Purpose |
|-----------|---------|
| `lang/` | Language spec (`EML_LANG_DESIGN.md`), grammar, parser, profiler, optimizer |
| `software/` | C / Rust / Python / LLVM / WASM backends + Lean / SMT / CBMC verification |
| `hardware/` | FPGA allocator, HDL generators, module library, vendor targets |
| `industries/` | 10 verticals: aerospace, automotive, robotics, manufacturing, energy, medical, defense, audio, ml, scientific |
| `patents/` | Patent portfolio (17 filed + 5 pending + strategy) |
| `roadmap/` | Phase plans (4 phases × ~3 sub-sessions), per-industry plans, business plans |
| `tools/` | CLI (`eml-compile`), VS Code extension, benchmarks (incl. vs-ladder-logic) |
| `data/` | Canonical numbers — operators, tower registry, profiles |
| `docs/` | Getting started, language guide, API reference, architecture |
| `tests/` | Integration + regression + per-industry test suites |

See `AGENT_FORGE.md` for the agent role file used by Claude Code
sessions working in this repo.

## Status

Currently SCAFFOLD — directory tree, language design document
(`lang/spec/EML_LANG_DESIGN.md`), foundational files, and skeleton
modules in place. No backend produces working output yet.

13 sessions planned over 7 months (Phase 1: 3 sessions; Phase 2:
4 sessions; Phase 3: 4 sessions; Phase 4: 2 sessions). See
`roadmap/phases/` for the phase plan and `CHANGELOG.md` for
version history.

## Contributing

See `CONTRIBUTING.md`. The compiler is open source under MIT;
specific methods are patented and listed in `patents/index.md`.

## Related projects

- [`monogate-research`](file:///D:/monogate-research) (private) —
  research notebooks, tooling, the structured + auto memory store,
  and the canonical data files this repo's `data/` mirrors.
- [`eml-cost`](https://pypi.org/project/eml-cost/) — the Pfaffian
  cost analyzer that powers `lang/profiler/`.
- [`monogate-lean`](file:///D:/monogate-lean) — the Lean 4
  formalization that backs `software/verification/lean/`.
