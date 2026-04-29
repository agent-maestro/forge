# Changelog

All notable changes to Monogate Forge will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-04-29 (Phase 2 SHIPPED -- import system + optimizer + 7 verticals)

The full marathon push from 2026-04-28 evening through 2026-04-29
morning. **525+ tests passing**, 24 skipped (Verilator-dependent).

### Added

- **`use stdlib::name;` import system** with selective imports
  (`{a, b}`), aliases (`{lerp as interp}`), and `local::sibling`
  resolution. Loader caches by resolved file path so symlinks
  + duplicate spellings dedupe. Tree-shaker drops imported fns
  no local code reaches.
  Commits: `46adca6`, `016feb0`, `3f74c43`, `86e6254`, `956003d`
- **Real 5-pass optimizer pipeline** wired into all backends:
  inline → constant_folding → CSE → SuperBEST → tree_shake.
  Backends + FPGAAllocator default to `optimize=True`; pass
  `optimize=False` to bypass.
  - Constant folding: 51 tests, idempotent + non-mutating
  - CSE: hoists duplicate sub-trees into `let _cse_N`
  - SuperBEST: real `eml_cost.recommend_form` integration with
    pre-filters (no-exp/tanh, n_atoms > 10, irrational floats)
    so a full stdlib snapshot runs in 0.7s instead of minutes
  - Tree-shaker: drops imported fns nothing local calls
  - Inliner: substitutes single-expr same-module CALLs
  Commits: `1a51dec`, `4abe703`, `016feb0`
- **Cross-target equivalence harness** (`tools/equivalence/`) --
  operational proof of Patent #22. Runs every backend on the same
  `.eml` source + asserts ULP agreement against a SymPy reference.
  Lean target verifies structural shape + optionally `lean
  --no-deps` when toolchain present.
  Commits: `d2a4f43`, `016feb0`
- **`eml-fmt` canonical formatter** (`tools/fmt/`). Idempotent
  + AST-preserving; round-trips `use ... as alias`. CLI:
  `--fmt` / `--fmt --check` / `--fmt --write`. 31 tests.
  Commit: `4abe703`
- **`--explain` CLI** with text + JSON output + multi-target
  backend stats. Per-fn diff showing inliner / fold / CSE /
  SuperBEST effects + node-count delta + digits-saved.
  Commits: `3f74c43`, `cdd3e63`, `86e6254`
- **stdlib (6 modules, 64 fns)** -- math (15) + ml (7) + control
  (12) + signal (11) + linalg (13) + constants (16). Every
  function chain-order verified against the profiler.
  Commits: `a7ef7a4`, `cdd3e63`, `86e6254`
- **11 industry verticals** (was 6). Production-shape `.eml`
  designs spanning aerospace, automotive, defense, energy,
  medical, robotics, ML inference, audio (DSP + synthesis),
  scientific (physics), manufacturing (process control). Three
  refactored to `use stdlib::control::pid` (autopilot, motor_foc,
  infusion_pump); motor_foc additionally uses
  `use local::three_phase` for the Park + Clarke transforms.
  Commits: `46adca6`, `016feb0`, `3f74c43`, `86e6254`, `956003d`
- **Patent #14 demo** (`industries/audio/synthesis/additive_voice.eml`)
  -- 4 sin call sites + 1 exp = 5 transcendentals. FPGA allocator's
  sharing decision lights up: `sin: count=4, sharing=shared`,
  `exp: count=1, sharing=dedicated`. 7 tests pin the behaviour.
  Commit: `956003d`
- **VS Code extension** (`tools/ide/vscode/`) with inline profile
  CodeLens + chain-order diagnostics on save. Shells out to the
  Python CLI -- no parsing reimplemented in TypeScript.
  Commit: `307d077`
- **Hardware module library** (`hardware/modules/transcendental/`)
  -- 12 SCAFFOLD Verilog modules (eml_exp/ln/sin/cos/tan/sqrt/
  sinh/cosh/tanh/asin/acos/atan) with shared interface, range
  documentation, structural lint tests + Verilator hooks.
  Commit: `8b2c3c1`
- **Vertical + stdlib regression gates** (`tools/benchmarks/`).
  Per-fn baselines pin chain_order, node_count, fpga_cycles,
  mac_units, trig_units. Any optimizer change that grows a
  metric fails the test loudly. 23 vertical fns + 58 stdlib fns
  baselined. Markdown dashboard at
  `tools/benchmarks/DASHBOARD.md`.
  Commits: `cdd3e63`, `956003d`
- **CI workflow** (`.github/workflows/forge.yml`) -- ubuntu +
  windows × py3.11 + py3.12 matrix; cargo cached; separate
  Linux Verilator job runs the HW-simulation paths.
  Commit: `4abe703`
- **`getting_started.md` tutorial** walking the autopilot.eml
  vertical end to end (parse → profile → backend emits).
  Commit: `b9abf37`

### Changed

- **Stdlib `math.eml` shrunk from 21 to 15 fns**. The 6
  activation functions (sigmoid, softplus, swish, gelu, relu,
  leaky_relu) moved to a new `stdlib::ml` module. New
  `stdlib::ml::sigmoid_alt` is the SuperBEST trigger demo.
  Commit: `cdd3e63`
- **Rust backend mangles param names** that collide with
  module-level consts (Rust 2021 const-pattern shadowing
  E0005). E.g. imported `pid_integrate(... dt: f64)` no longer
  conflicts with a vertical's `const dt = ...`.
  Commit: `46adca6`
- **FPGA allocator runs `optimize_module` first** by default
  (matches backends). Without it, helper CALLs would hide the
  transcendentals from the allocator's count.
  Commit: `956003d`

### Tests

- 525+ passing across the whole suite (was 220 at session start)
- New test directories this push:
  `lang/loader/tests/`, `lang/optimizer/tests/`,
  `tests/equivalence/`, `tests/benchmarks/`,
  `tests/stdlib/`, `tools/fmt/tests/`, `tools/cli/tests/`,
  `tools/benchmarks/`

### Known papercuts

- Windows pytest stdout buffering hides the summary line in
  background-task output; exit codes still reliable
- Defender scanning adds ~90s to subprocess Python spawn; CLI
  test timeouts bumped to 240s

### Patent demos operational today

- **#22 (dual-target compilation)** -- `cross_target_check()`
  proves Rust-vs-Python ULP agreement on every stdlib + vertical fn
- **#14 (FPGA resource allocator)** -- `additive_voice.eml`
  shows sharing-vs-dedicated decision visible in plan
- **#01 (SuperBEST routing)** -- `ml::sigmoid_alt` rewrites to
  canonical sigmoid, saves 1.08 decimal digits of precision

---

## [0.1.0-pre] — 2026-04-28 (Phase 1 SHIPPED)

### Added (commits `1df5090` parser + `0099bdd` profiler)

- **Working lexer** at `lang/parser/lexer.py` — longest-match
  operator handling, line + col tracking, keyword classification
- **Working parser** at `lang/parser/parser.py` — full
  recursive-descent + Pratt expression precedence; 11/11 demo
  `.eml` files parse cleanly into typed `EMLModule` /
  `EMLFunction` / `EMLConstant` / `EMLTypeAlias` ASTs with
  source-location info on every node
- **AST → SymPy bridge** at `lang/profiler/ast_to_sympy.py` —
  handles let-binding inlining, tuple-return decomposition,
  builtin dispatch (exp/ln/sin/cos/tan/sqrt/asin/acos/atan/sinh
  /cosh/tanh/abs/clamp/eml). Functions with `let mut` / `while` /
  assignment correctly land in `complex_body` status.
- **Working profiler** at `lang/profiler/profiler.py` — every
  function gets a populated `profile` dict (chain_order,
  cost_class, eml_depth, dynamics counter, FPGA estimate,
  stability warnings, drift risk) via `eml-cost.analyze` +
  `eml-cost.analyze_dynamics`
- **AST node extensions** in `lang/parser/ast_nodes.py`:
  `Param`, `Annotation`, `WhereClause`, `EMLModule` dataclasses;
  `LET_MUT` / `ASSIGN` / `WHILE` / `BLOCK` / `EXPR_STMT` /
  `TUPLE` NodeKinds; `BUILTIN_NAMES` + `BUILTIN_TO_KIND` tables
- **66 tests passing** across `lang/parser/tests/` (43) +
  `lang/profiler/tests/` (21) + `tests/integration/` (2).
- End-to-end `parse → profile → type_check` pipeline closed.
  Type checker correctly rejects `sin(x)` against
  `chain_order <= 1` constraint.

### Phase 1 status

- 1.1 Grammar — DONE (hand-rolled parser preferred over ANTLR codegen)
- 1.2 Parser — DONE
- 1.3 Profiler + type checker — DONE
- 1.6 Domain + precision constraint INFERENCE at call sites — deferred to a later sub-phase

See `roadmap/phases/phase1_language.md` for the per-milestone
checklist and `lang/spec/EML_LANG_DESIGN.md` for the canonical
design vision.

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
