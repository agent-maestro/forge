# Architecture — Monogate Forge

> The stack at a glance: source `.eml` → parser → profiler →
> optimizer → backend. One AST, nine targets, every target
> regression-gated.

---

## The big picture

```
   .eml source
       │
       ▼
   ┌─────────┐    ┌──────────┐    ┌──────────────┐
   │  Lexer  │ →  │  Parser  │ →  │   Profiler   │
   │ (hand)  │    │ (hand RD │    │ (Pfaffian +  │
   └─────────┘    │  parser) │    │  dynamics)   │
                  └──────────┘    └──────┬───────┘
                                         │
                                         ▼
                                ┌────────────────┐
                                │   Optimizer    │
                                │  (5 passes)    │
                                └────────┬───────┘
                                         │
              ┌──────┬───────┬───────┬───┴───┬────────┬───────┐
              ▼      ▼       ▼       ▼       ▼        ▼       ▼
            C    Rust   Python   LLVM    Verilog   VHDL   Chisel
                                  │                              ▲
                                  ▼                              │
                                wasm32                         FIRRTL
                                                                 │
                                                                 ▼
                                                              Lean 4
```

Every layer is a Python module with a single public entry
point. Every layer is independently testable.

---

## Layers

### Lexer + Parser — `lang/parser/`

Hand-rolled recursive descent. The grammar lives in
`lang/spec/grammar/eml_lang.g4` for documentation, but the
compiled parser is straight Python — no codegen step. Source
locations (line + column) are attached to every AST node so
every downstream error message points at a file:line:col.

### Profiler — `lang/profiler/`

Walks the AST, builds a SymPy expression for every function
that fits the arithmetic subset, and computes:

- **chain_order** — Pfaffian depth of the function (how
  deeply nested the transcendentals are).
- **cost_class** — `eml-cost.analyze` family classification.
- **dynamics** — count of oscillatory + decaying components.
- **fpga_estimate** — MAC/exp/ln/trig unit demand + latency.
- **fp16_drift_risk** — heuristic stability tag.

Functions with iterative bodies (`mut`, `while`) get tagged
`status="complex_body"` and bypass the SymPy path.

### Optimizer — `lang/optimizer/`

Five passes run in this order on the parsed module:

1. **`inline_calls`** — substitute eligible same-module
   `CALL`s (single-expression bodies, no recursion).
2. **`constant_folding`** — fold pure-literal sub-trees,
   algebraic identities, builtin transcendentals on
   literal args.
3. **`apply_cse`** — hoist duplicate sub-trees into
   `let _cse_N =`.
4. **`superbest_module`** — run `eml_cost.recommend_form`
   on each function, rewrite to the canonical form when
   `digits_saved > 0.5`.
5. **`shake_imports`** — drop imported functions no local
   function reaches via `CALL`.

Every backend takes `optimize=True` by default and runs the
pipeline before lowering. Pass `optimize=False` to bypass.

### Backends — `software/backends/` + `hardware/hdl_gen/`

| Backend       | File                               | Output           | Status |
|---------------|------------------------------------|------------------|--------|
| C             | `software/backends/c_backend.py`   | `.c` source      | live   |
| Rust          | `software/backends/rust_backend.py`| `.rs` source     | live   |
| Python        | `software/backends/python_backend.py` | `.py` source  | live   |
| LLVM IR       | `software/backends/llvm_backend.py`| IR text          | live   |
| WebAssembly   | `software/backends/wasm_backend.py`| wasm32 bytecode  | live (toolchain-gated) |
| Verilog       | `hardware/hdl_gen/verilog_backend.py` | `.v` source   | live   |
| VHDL          | `hardware/hdl_gen/vhdl_backend.py` | `.vhd` source    | live   |
| Chisel        | `hardware/hdl_gen/chisel_backend.py` | Scala/FIRRTL   | live   |
| Lean 4        | `software/verification/lean/LeanBackend.py` | `.lean` | live   |

The hardware backends consume an `AllocationPlan` from the
FPGA allocator (Patent #14, `hardware/allocator/`) so the
emitted HDL is sized for the target device.

### CLI — `tools/cli/main.py`

`eml-compile` is the front door. Subcommands:

- `eml-compile <file.eml>`            — parse + profile, print summary
- `eml-compile <file.eml> --target X` — compile to target X
- `eml-compile <file.eml> --allocate` — run FPGA allocator
- `eml-compile <file.eml> --explain`  — per-function optimizer diff
- `eml-compile <file.eml> --fmt`      — canonical formatter
- `eml-compile init <dir>`            — scaffold a new project
- `eml-compile manpage`               — print roff(7) man page

---

## Equivalence guarantees

Patent #22 (dual-target compilation) is enforced
operationally by `tools/equivalence/cross_target_check()`.
For every stdlib function and every industry vertical, the
test suite runs the same input vectors through Python, C,
Rust, and Lean (when toolchains are available) and asserts
agreement within 1e-12.

When a toolchain is missing (no `gcc`, no `cargo`, no
`verilator`), that target is reported as `available=False`
rather than failing the run — partial coverage is preferred
over no coverage.

---

## See also

- [`profiler.md`](profiler.md) — Pfaffian profiling deep-dive.
- [`optimizer_pipeline.md`](optimizer_pipeline.md) — 5-pass
  pipeline detail.
- [`../api_reference/cli.md`](../api_reference/cli.md) — full
  CLI surface.
- [`../api_reference/backends.md`](../api_reference/backends.md)
  — backend module reference.
