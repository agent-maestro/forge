# Changelog

All notable changes to Monogate Forge will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-04-28 (post-design-doc integration)

### Added

- `lang/spec/EML_LANG_DESIGN.md` — canonical design vision
  document (full PLANNING-tier spec with rationale, syntax,
  type system, compiler architecture, 4-phase plan, patent
  implications, comparison matrix vs ladder logic / ST / MATLAB)
- `lang/spec/grammar/examples/motor_control.eml` — comprehensive
  demo from the design doc (type aliases, FPGA-targeted block,
  Lean-verified block, deliberately-warning function)
- `tools/benchmarks/versus/vs_ladder_logic.md` — full
  comparison: PID controller in 3 languages (ladder, ST,
  EML-lang); honest "where ladder still wins" section
- Python skeleton modules wired to the design doc's class
  signatures:
  - `lang/parser/` (parser, ast_nodes, type_checker, errors)
  - `lang/profiler/` (profiler, dynamics)
  - `lang/optimizer/` (superbest, fusion, cse, constant_folding)
  - `software/backends/` (c_backend, rust_backend, llvm_backend,
    python_backend, wasm_backend)
  - `software/verification/lean/LeanBackend.py`
  - `hardware/allocator/` (allocator, precision_selector)
  - `hardware/hdl_gen/verilog_backend.py`
  - `hardware/simulation/verilator_sim.py`

### Changed

- `README.md` — leads with the ladder-logic motivation; links
  to the design doc + comparison file
- `lang/spec/SPEC.md` — expanded to mirror the design doc's
  syntax + type system + profiling output
- `lang/spec/grammar/eml_lang.g4` — full grammar matching the
  design doc (typed AST, annotations, requires/ensures,
  precedence-aware expression rules, built-in catalog)
- All four `roadmap/phases/*.md` files — restructured into the
  detailed sub-session breakdowns from the design doc
  (Phase 1: 3 sessions; Phase 2: 4 sessions; Phase 3: 4 sessions;
  Phase 4: 2 sessions; total 13 sessions over 7 months)

## [0.0.1] — 2026-04-28

### Added

- Initial repository scaffold
- Top-level documentation: `README.md`, `LICENSE` (MIT), `CONTRIBUTING.md`,
  `AGENT_FORGE.md`
- Full directory tree for all 10 sections (lang, software, hardware,
  industries, patents, roadmap, tools, data, docs, tests)
- Language specification skeleton at `lang/spec/SPEC.md`
- Standard library skeleton at `lang/spec/stdlib/STDLIB.md`
- Type system documentation at `lang/spec/types/TYPES.md`
- 10 example `.eml` files at `lang/spec/grammar/examples/` (placeholder)
- C runtime header at `software/runtime/c/libmonogate.h` (23 operators)
- Patent index at `patents/index.md` (17 filed + 5 pending)
- Per-industry README at each `industries/<vertical>/`
- Roadmap master at `roadmap/README.md` with phase + industry + business plans
- CLI entry point stub at `tools/cli/main.py`
- Canonical data files at `data/` (operators.json, tower_registry.json mirrored
  from `monogate-research/data/` and `exploration/E201_extended_atlas/`)

### Notes

This is the FOUNDATIONAL SCAFFOLD release. No backend produces working
output yet; the structure is ready for development to begin in any of the
phases listed in `roadmap/phases/`.
