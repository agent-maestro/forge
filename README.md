# Monogate Forge

> **EML-Lang: a programming language for verified mathematical
> computation. Every expression is an EML tree. The compiler
> optimizes via SuperBEST routing, verifies via Lean, and targets
> both software (C / Rust / Python / LLVM / WASM) AND hardware
> (Verilog / VHDL / Chisel / FPGA / ASIC) from one source.**

**Status:** v0.2 — 9 live backends, 5 FPGA/ASIC targets, 11 industry
verticals, 34 pre-verified blocks, 677+ tests passing.

**Repository:** local only (private, pre-Blackwell baton handoff).

**License:** MIT for compiler; specific methods covered by filed patents.

---

## Why this exists

Industrial automation today is stuck on ladder logic — Boolean rungs
from the 1960s that can't express transcendental functions, can't
prove correctness, can't optimize node count, and treat PID loops
as black boxes. Structured Text is marginally better but still
opaque. MATLAB / Simulink + HDL Coder will get you to FPGA, but the
math is hidden inside vendor library calls and you have no formal
proof of precision.

**EML-Lang makes every mathematical operation visible, measurable,
optimizable, and formally verifiable.**

```
EML-LANG:
  fn pid(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
  {
    Kp * error + Ki * integral + Kd * derivative
  }

  // Compiler tells you (always, not opt-in):
  //   chain_order: 0 (purely polynomial — no transcendental risk)
  //   total_nodes: 6 (SuperBEST optimal)
  //   precision:   bounded by Lean theorem pid_relerr_bound
  //   FPGA:        6 MAC units, 0 transcendental units needed
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

---

## Compilation pipeline

```
.eml source
    │
    ▼
PARSER → PROFILER → TYPE CHECK → 5-PASS OPTIMIZER
    │                              (inline, fold, CSE,
    │                              SuperBEST, tree-shake)
    │
    ├──▶ SOFTWARE  C99 │ Rust │ Python │ LLVM IR │ WebAssembly
    │
    ├──▶ HARDWARE  Verilog │ VHDL │ Chisel/FIRRTL
    │              (FPGA allocator selects per-unit precision +
    │              sharing + pipelining — Patent #14)
    │
    └──▶ VERIFY    Lean 4 theorems via `eml_auto` (Z3 SMT and CBMC
                   planned for Phase 2.5)
```

Profiling is **automatic** — every expression carries its chain
order, cost class, and dynamics counter. The optimizer is SuperBEST
routing by default. Chain-order types are enforced at compile
time. The compiler never silently loses precision.

---

## Quick start

```bash
# Scaffold a new EML project
python tools/cli/main.py init my_project
cd my_project

# Profile your starter program
python ../tools/cli/main.py main.eml --profile-only

# Compile to all 9 backends in one shot
python ../tools/cli/main.py main.eml --target all -o build/

# Or pick a single backend
python ../tools/cli/main.py main.eml --target c       -o main.c
python ../tools/cli/main.py main.eml --target rust    -o main.rs
python ../tools/cli/main.py main.eml --target python  -o main.py
python ../tools/cli/main.py main.eml --target llvm    -o main.ll
python ../tools/cli/main.py main.eml --target wasm    -o main.wasm
python ../tools/cli/main.py main.eml --target verilog -o main.v
python ../tools/cli/main.py main.eml --target vhdl    -o main.vhd
python ../tools/cli/main.py main.eml --target chisel  -o Main.scala
python ../tools/cli/main.py main.eml --target lean    -o Main.lean

# Allocate FPGA resources
python ../tools/cli/main.py main.eml --allocate --fpga-target xilinx.artix7
```

Or skip writing EML entirely and use **`forge.blocks`** — 34
pre-verified computation blocks (PID, sigmoid, Park, Kalman,
biquad, FFT butterfly, …) where parse + profile + FPGA allocation
are all pre-cached at import time:

```python
from forge.blocks.polynomial   import linear, quadratic
from forge.blocks.exponential  import sigmoid_block
from software.backends.c_backend import CBackend

pipeline = linear >> sigmoid_block      # chain_order = max(...)
src = CBackend().compile(pipeline.to_module())
```

See [`docs/getting_started.md`](docs/getting_started.md) for the
10-minute tour and [`forge/blocks/README.md`](forge/blocks/README.md)
for the full block catalogue.

---

## Repository layout

| Directory | Purpose |
|-----------|---------|
| `lang/`        | Language spec, grammar, parser, profiler, 5-pass optimizer, stdlib (`math`, `ml`, `control`, `signal`, `linalg`, `constants`) |
| `software/`    | C / Rust / Python / LLVM / WASM backends + Lean / SMT / CBMC verification |
| `hardware/`    | FPGA allocator (Patent #14), HDL generators (Verilog / VHDL / Chisel), CORDIC module library, 5 vendor targets |
| `industries/`  | 11 verticals: aerospace, automotive, robotics, medical, defense, energy, audio (DSP + synthesis), ML inference, scientific physics, manufacturing |
| `forge/blocks/`| 34 pre-verified standard-library blocks (oscillator / exponential / polynomial / control / signal / transform) |
| `patents/`     | Patent portfolio + claim-to-implementation map |
| `roadmap/`     | Phase plans, per-industry plans, business plans |
| `tools/`       | CLI (`eml-compile` + `init` + `manpage`), VS Code extension (0.2.0), JetBrains plugin scaffold, benchmarks (incl. vs-ladder-logic), graph orientation tooling |
| `data/`        | Canonical numbers — operators, tower registry, profiles |
| `docs/`        | Getting started, language guide, software / hardware target guides, verification guide, architecture, API reference, industry guides |
| `tests/`       | 677+ tests across unit, integration, equivalence, per-industry, regression, and benchmarks |

See `AGENT_FORGE.md` for the agent role file used by Claude Code
sessions working in this repo.

---

## Status

**Production-ready compiler.** All nine backends emit working
output for every demo and every industry vertical. The cross-target
equivalence harness (Patent #22) verifies ULP-level agreement
between the software and hardware paths.

| Phase | Status |
|-------|--------|
| Phase 1 — Language design + parser  | shipped |
| Phase 2 — Software backends         | shipped (5 of 5 backends) |
| Phase 3 — Hardware backends         | shipped (3 HDL backends, 5 FPGA/ASIC targets); CUDA-accelerated Verilator gated on Blackwell delivery |
| Phase 4 — IDE + DX                  | VS Code 0.2.0 shipped (picker + format-on-save + FPGA status bar); JetBrains 0.1 scaffold shipped; full polish in 0.2 |

| Buildout      | Today | Last week |
|---------------|-------|-----------|
| Overall       | 56 %  | 26 %      |
| `software/`   | 35 %  | 20 %      |
| `hardware/`   | 42 %  | 24 %      |
| `docs/`       | 113 % | 7 %       |
| `tests/`      | 70 %  | 65 %      |

See `CHANGELOG.md` for the full ship history and
`roadmap/phases/` for the remaining phase work.

---

## Contributing

See `CONTRIBUTING.md`. The compiler is open source under MIT;
specific methods are patented and listed in `patents/index.md`.

---

## Related projects

- [`monogate-research`](file:///D:/monogate-research) (private) —
  research notebooks, tooling, the structured + auto memory store,
  and the canonical data files this repo's `data/` mirrors.
- [`eml-cost`](https://pypi.org/project/eml-cost/) — the Pfaffian
  cost analyzer that powers `lang/profiler/`.
- [`monogate-lean`](file:///D:/monogate-lean) — the Lean 4
  formalization that backs `software/verification/lean/` and
  `forge.blocks` Lean theorems.
