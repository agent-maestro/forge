# Phase 2 — Software Compiler Backend

**Duration:** ~4 sessions (months 2-4)
**Reference:** `lang/spec/EML_LANG_DESIGN.md` Phase 2 section

**Goal:** every example compiles to working C, Rust, LLVM IR,
Python, with Lean verification artifacts emitted from `@verify`
blocks. All backends share the same SuperBEST optimizer.

---

## 2.1 C backend via libmonogate (1 session)

**Deliverable:** `software/backends/c_backend.py` produces
standalone `.c` files using `libmonogate.h`.

- [ ] `CBackend.compile(program)` returns full C source
- [ ] Per-function profile comment (chain order, cost class, FPGA estimate)
- [ ] Operator dispatch via `mg_eml`, `mg_eal`, `mg_exl`, etc.
  (one inline call per EML node)
- [ ] SuperBEST routing decides which 23-family operator to emit
- [ ] Generated C compiles with `gcc -O2 -Wall -Werror` cleanly
- [ ] Output matches eml-cost Python reference within 1e-12 on
  all 10 demo examples

## 2.2 Rust backend (1 session)

**Deliverable:** `software/backends/rust_backend.py` produces
Rust source consuming the `monogate-sys` crate.

- [ ] `RustBackend.compile(program)` returns Rust source
- [ ] Per-function profile comment (same shape as C backend)
- [ ] `f64` arithmetic; `monogate-sys` provides `mg_eml` etc.
- [ ] Generated Rust passes `cargo clippy -D warnings`
- [ ] Output matches Python reference within 1e-12

## 2.3 LLVM IR backend (1 session)

**Deliverable:** `software/backends/llvm_backend.py` emits portable
LLVM IR. Each EML operator becomes an LLVM intrinsic or function
call; LLVM's own optimizer runs after ours.

- [ ] `LLVMBackend.compile(program)` returns LLVM IR text
- [ ] Compiles via `llc` to x86, ARM, RISC-V, WASM targets
- [ ] Cross-platform smoke test: x86 + ARM + WASM (in Node)
- [ ] Output matches Python reference within 1e-12

## 2.4 Lean verification backend (1 session)

**Deliverable:** `software/verification/lean/LeanBackend.py` emits
Lean 4 theorem files for `@verify` blocks.

- [ ] `LeanBackend.compile(func)` for any function with a
  `@verify(lean, theorem=...)` annotation
- [ ] Theorem statement built from `requires` + function name +
  `ensures` clauses
- [ ] Auto-attempt the proof using `eml_auto` tactic (from
  `monogate-lean/MonogateEML/Tactics.lean`)
- [ ] Falls back to `sorry` with a TODO comment if `eml_auto`
  doesn't close
- [ ] Generated `.lean` files type-check inside the
  `monogate-lean` Lake project

---

## Cross-cutting deliverables

- [ ] Python backend (reuses the eml-cost Tool 5 transpiler — no
  new code required, just wire to the same AST)
- [ ] All 4 backends share `lang/optimizer/` (SuperBEST routing,
  fusion patterns, CSE, constant folding)
- [ ] Integration tests: every backend compiles every demo and
  matches the others within tolerance
- [ ] CI matrix: `tests/integration/test_{c,rust,llvm,python,lean}_output.py`

---

## Out of scope (defer to Phase 3)

- Hardware backends (Verilog / VHDL / Chisel)
- FPGA simulation
