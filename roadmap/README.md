# Roadmap

The forge ships in 4 phases. Each phase has its own milestone
file in `phases/`. Per-industry rollouts live in `industries/`.
Business / GTM lives in `business/`.

## Phases (sequential)

| Phase | Status | Doc |
|-------|--------|-----|
| 1 | Language: grammar + parser + profiler + type checker | [`phases/phase1_language.md`](phases/phase1_language.md) |
| 2 | Software backends: C / Rust / Python / LLVM / WASM + Lean / SMT / CBMC verify | [`phases/phase2_software.md`](phases/phase2_software.md) |
| 3 | Hardware backends: FPGA allocator + Verilog/VHDL/Chisel + module library | [`phases/phase3_hardware.md`](phases/phase3_hardware.md) |
| 4 | IDE / CLI: VS Code extension + `eml-compile` UX | [`phases/phase4_ide.md`](phases/phase4_ide.md) |

## Industries (parallel after Phase 2)

After Phase 2 ships, industry verticals roll out in parallel.
Each vertical has its own roadmap in `industries/<vertical>.md`.

## Business

- `business/pricing.md` — Free / Pro / Enterprise / Silicon tiers
- `business/go_to_market.md` — GTM per vertical
- `business/certification_partners.md` — DO-178C / ISO 26262 partners
