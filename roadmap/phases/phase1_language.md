# Phase 1 — Language Design + Parser

**Duration:** ~3 sessions (months 1-2)
**Reference:** `lang/spec/EML_LANG_DESIGN.md` Phase 1 section

**Goal:** end-to-end parse + profile + type-check of every
example in `lang/spec/grammar/examples/`, with chain-order types
enforced and FPGA estimates emitted.

**Status:** SHIPPED 2026-04-28 (commits `1df5090` parser +
`0099bdd` profiler). Pipeline closes end-to-end on all 11 demo
files; 66 tests passing.

---

## 1.1 Grammar definition (SHIPPED)

**Deliverable:** ANTLR4 grammar at `lang/spec/grammar/eml_lang.g4`
covering all syntax in `EML_LANG_DESIGN.md`.

- [x] Top-level: `program`, `typeDecl`, `constDecl`, `functionDecl`
- [x] Annotations: `@target(...)`, `@verify(...)`
- [x] Type expressions with `chain_order` constraints
- [x] `requires` / `ensures` clauses
- [x] Expression grammar with proper precedence (unary, * /, + -, comparison)
- [x] Built-in functions (exp, ln, sin, cos, tan, sqrt, pow, eml, abs, clamp, asin/acos/atan, sinh/cosh/tanh)
- [x] String / number / identifier tokens
- [x] Comments (line `//` + block `/* */`)
- [x] Grammar shipped as documentation; **hand-rolled recursive-descent**
  was used for the parser instead of ANTLR codegen (faster, no codegen
  step, easier to debug).

## 1.2 Parser implementation (SHIPPED commit `1df5090`)

**Deliverable:** Python parser at `lang/parser/parser.py` producing
typed ASTs from any well-formed `.eml` source.

- [x] `NodeKind` enum + `ASTNode` dataclass per `EML_LANG_DESIGN.md` 1.2
- [x] `EMLFunction` dataclass with `name`, `params`, `return_type`,
  `return_constraint`, `body`, `annotations`, `requires`, `ensures`
- [x] `parse_function`, `parse_expr`, `parse_constant` recursive-descent
- [x] Source location tracking (line + column) on every node
- [x] Full error messages with file:line:col on syntax errors
- [x] All 10 demo `.eml` files parse without error
- [x] Bonus: `motor_control.eml` (the comprehensive demo) also parses
- [x] 43 tests covering lexer + parser

## 1.3 Profiler integration (SHIPPED commit `0099bdd`)

**Deliverable:** Automatic profiling of every parsed function via
`lang/profiler/profiler.py`. Powered by `eml-cost.analyze` +
`eml-cost.analyze_dynamics`.

- [x] `Profiler.profile_function(func)` populates `func.profile`
  with `chain_order`, `cost_class`, `eml_depth`, `dynamics`,
  `node_count`, `stability_warnings`, `fp16_drift_risk`,
  `fpga_estimate`
- [x] AST → SymPy round-trip for analyzer consumption
  (`lang/profiler/ast_to_sympy.py`)
- [x] Type checker (`lang/parser/type_checker.py`) consumes
  populated profile to enforce chain-order constraints
- [x] FPGA resource estimate (exp/ln/trig/MAC unit counts +
  latency cycles + bit width) per Patent #14
- [x] 21 profiler tests + 43 parser/lexer tests = 66 total
  (above the 80% target on `lang/parser/` + `lang/profiler/`)
- [x] All 11 demo files parse + profile without crash; functions
  with mutation/while correctly land in `complex_body` status

---

## Out of scope (defer to Phase 2)

- Code generation (any target)
- Verification artifact emission

---

## Risk register

- **Grammar ambiguities surface late** if examples don't span enough
  syntax — keep adding examples as features land.
- **Chain-order inference for `pow(a, b)`** (general b) is subtle;
  may need a special case in the type checker (currently +1 if `b`
  is non-constant; 0 if `b` is integer literal).
- **AST → SymPy round-trip** must preserve operator identity so the
  cost analyzer sees the same canonical tree the parser produced.
  Test against the 10 demo examples + the master corpus.
