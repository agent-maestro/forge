# Phase 2 — Software Backends

**Goal:** every example compiles to working C, with Lean
verification artifacts emitted from `@verify` blocks.

## Milestones

- [ ] M2.1: C backend produces standalone `.c` files using `libmonogate.h`
- [ ] M2.2: Generated C compiles with `gcc -O2` and matches Python reference within tolerance
- [ ] M2.3: Rust backend (subset of M2.1)
- [ ] M2.4: Python backend (reuses eml-cost Tool 5 transpiler)
- [ ] M2.5: LLVM IR backend (portable foundation)
- [ ] M2.6: WASM backend (browser-deployable)
- [ ] M2.7: Lean backend: `@verify { ... }` block emits a `.lean` file with theorem template
- [ ] M2.8: SMT backend: Z3 constraint check for domain + precision clauses
- [ ] M2.9: CBMC backend: bounded model check on generated C
- [ ] M2.10: Each backend has integration tests in `tests/integration/`

## Out of scope (defer to Phase 3)

- Hardware backends
- FPGA simulation
