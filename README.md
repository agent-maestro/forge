# Monogate Forge

> **Programming language and compiler for verified mathematical
> computation, targeting both software (C / Rust / WASM / Python)
> and hardware (Verilog / VHDL / FPGA / ASIC) from one source.**

**Status:** FOUNDATIONAL SCAFFOLD (v0.0.1) — under development
**Repository:** https://github.com/agent-maestro/monogate-forge (planned)
**License:** MIT for compiler, patents cover specific methods

---

## What is Monogate Forge?

A unified pipeline that takes a single `.eml` source file describing
mathematical computation and compiles it to:

- **Software targets:** C99, Rust, Python/NumPy, LLVM IR, WebAssembly
- **Hardware targets:** Verilog, VHDL, Chisel, SystemC — synthesized
  for Xilinx, Intel, Lattice FPGAs or open-PDK ASICs (SkyWater 130nm,
  GF180nm)
- **Verification artifacts:** Lean 4 theorems for `@verify` blocks,
  Z3 / SMT constraints, CBMC bounded model checks

The compiler enforces **chain-order types** (Patent #21) so the
Pfaffian complexity of every expression is statically known — and
the **FPGA resource allocator** (Patent #14) chooses precision,
sharing, and pipelining per-unit to fit any hardware budget.

## Why one source for software AND hardware?

Today, deploying a new control law to an FPGA means:
1. Write it in MATLAB/Simulink
2. Hand-translate to C for the simulator
3. Hand-translate to HDL for the FPGA
4. Hand-prove precision bounds for certification (DO-178C / ISO 26262)
5. Three implementations to keep in sync forever

Monogate Forge collapses this to one source plus one compile
invocation per target. The math is the same; the precision bounds
are machine-checked once.

## Quick start (planned)

```bash
# Install
pip install monogate-forge

# Compile a basic PID controller to C
eml-compile lang/spec/grammar/examples/pid_basic.eml --target c -o pid.c

# Profile any .eml expression
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
| `lang/` | Language spec, grammar, parser, profiler, optimizer |
| `software/` | C / Rust / Python / LLVM / WASM backends + verification |
| `hardware/` | FPGA allocator, HDL generators, module library, vendor targets |
| `industries/` | 10 verticals: aerospace, automotive, robotics, manufacturing, energy, medical, defense, audio, ml, scientific |
| `patents/` | Patent portfolio (17 filed + 5 pending + strategy) |
| `roadmap/` | Phase plans, per-industry plans, business plans |
| `tools/` | CLI (`eml-compile`), VS Code extension, benchmarks, audit |
| `data/` | Canonical numbers — operators, tower registry, profiles |
| `docs/` | Getting started, language guide, API reference, architecture |
| `tests/` | Integration + regression + per-industry test suites |

See `AGENT_FORGE.md` for the agent role file used by Claude Code
sessions working in this repo.

## Status

Currently SCAFFOLD — directory tree + key documentation files
shipped, individual modules awaiting development.

See `roadmap/phases/` for the phase plan and `CHANGELOG.md` for
version history.

## Contributing

See `CONTRIBUTING.md`. The compiler is open source under MIT;
specific methods (SuperBEST routing, fusion patterns, FPGA
allocator, etc.) are patented and listed in `patents/index.md`.

## Related projects

- [`monogate-research`](https://github.com/agent-maestro/monogate-research)
  (private) — research notebooks, tooling, the structured memory
  store, and the canonical data files this repo's `data/` mirrors.
- [`eml-cost`](https://pypi.org/project/eml-cost/) — the Pfaffian
  cost analyzer that powers `lang/profiler/`.
- [`monogate-lean`](https://github.com/agent-maestro/monogate-lean)
  — the Lean 4 formalization that backs `software/verification/lean/`.
