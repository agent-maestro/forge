# Phase 4 — IDE + Developer Experience

**Duration:** ~2 sessions (months 6-7)
**Reference:** `lang/spec/EML_LANG_DESIGN.md` Phase 4 section

**Goal:** developer ergonomics — VS Code extension with inline
profiling annotations, polished CLI with helpful errors.

---

## 4.1 VS Code extension (1 session)

**Deliverable:** `tools/ide/vscode/` extension with the features
described in `EML_LANG_DESIGN.md` Phase 4.1.

- [ ] Syntax highlighting (`syntaxes/eml.tmLanguage.json` —
  already scaffolded; expand keyword set as the grammar settles)
- [ ] Inline Pfaffian profile annotations (chain order, cost
  class, dynamics counter shown beside each function header)
- [ ] Chain-order type error highlighting with hover explanations
  ("This function returns chain_order 3 but signature says <= 2")
- [ ] FPGA resource estimation in the status bar
- [ ] "Compile to..." command (C / Rust / Verilog / Lean)
- [ ] SuperBEST routing visualization (which 23-family operator
  was selected for each EML node)
- [ ] Auto-complete for EML operators + stdlib symbols
- [ ] Goto-definition for stdlib + user functions
- [ ] Format-on-save (basic indent-aligning formatter)

## 4.2 CLI compiler (1 session)

**Deliverable:** Polished `eml-compile` CLI at `tools/cli/main.py`
with the full surface from `EML_LANG_DESIGN.md` Phase 4.2.

- [ ] `eml-compile <file.eml> --target c|rust|python|llvm|wasm|verilog|vhdl|chisel|lean -o <out>`
- [ ] `--profile-only` (skip codegen; print profile and exit)
- [ ] `--verify` (emit Lean / SMT / CBMC artifacts)
- [ ] `--fpga-sim` (after Verilog emit, run Verilator + compare)
- [ ] `--clock <MHz>`, `--precision <float16|32|64>`, `--max-luts <N>`,
  `--max-dsps <N>`, `--max-brams <KB>` for FPGA targets
- [ ] `--target all` runs every applicable backend and reports a
  summary table
- [ ] Helpful error messages with source-location pointers
- [ ] `eml-compile init` for project scaffolding (creates
  pyproject.toml + main.eml + .vscode/settings.json)
- [ ] Man page generated from argparse

---

## Cross-cutting deliverables

- [ ] Documentation site (probably under `monogate.dev/forge/` once
  public) generated from `docs/` markdown
- [ ] JetBrains plugin (subset of 4.1 — syntax + diagnostics; no
  inline profiler annotations until they stabilize)
- [ ] CI smoke tests for the CLI: every demo target compiles via
  the CLI to every backend
