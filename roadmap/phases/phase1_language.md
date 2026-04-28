# Phase 1 — Language Design + Parser

**Duration:** ~3 sessions (months 1-2)
**Reference:** `lang/spec/EML_LANG_DESIGN.md` Phase 1 section

**Goal:** end-to-end parse + profile + type-check of every
example in `lang/spec/grammar/examples/`, with chain-order types
enforced and FPGA estimates emitted.

---

## 1.1 Grammar definition (1 session)

**Deliverable:** ANTLR4 grammar at `lang/spec/grammar/eml_lang.g4`
covering all syntax in `EML_LANG_DESIGN.md`.

- [ ] Top-level: `program`, `typeDecl`, `constDecl`, `functionDecl`
- [ ] Annotations: `@target(...)`, `@verify(...)`
- [ ] Type expressions with `chain_order` constraints
- [ ] `requires` / `ensures` clauses
- [ ] Expression grammar with proper precedence (unary, * /, + -, comparison)
- [ ] Built-in functions (exp, ln, sin, cos, tan, sqrt, pow, eml, abs, clamp, asin/acos/atan, sinh/cosh/tanh)
- [ ] String / number / identifier tokens
- [ ] Comments (line `//` + block `/* */`)
- [ ] ANTLR generates parser stubs that compile without warnings

## 1.2 Parser implementation (1 session)

**Deliverable:** Python parser at `lang/parser/parser.py` producing
typed ASTs from any well-formed `.eml` source.

- [ ] `NodeKind` enum + `ASTNode` dataclass per `EML_LANG_DESIGN.md` 1.2
- [ ] `EMLFunction` dataclass with `name`, `params`, `return_type`,
  `return_constraint`, `body`, `annotations`, `requires`, `ensures`
- [ ] `parse_function`, `parse_expr`, `parse_constant` recursive-descent
- [ ] Source location tracking (line + column) on every node
- [ ] Full error messages with file:line:col on syntax errors
- [ ] All 10 demo `.eml` files parse without error

## 1.3 Profiler integration (1 session)

**Deliverable:** Automatic profiling of every parsed function via
`lang/profiler/profiler.py`. Powered by `eml-cost.analyze` +
`eml-cost.analyze_dynamics`.

- [ ] `Profiler.profile_function(func)` populates `func.profile`
  with `chain_order`, `cost_class`, `eml_depth`, `dynamics`,
  `node_count`, `stability_warnings`, `fp16_drift_risk`,
  `fpga_estimate`
- [ ] AST → SymPy round-trip for analyzer consumption
- [ ] `Profiler.type_check_chain(func)` returns list of type errors
  for chain-order constraint violations
- [ ] FPGA resource estimate (exp/ln/trig/MAC unit counts +
  latency cycles + bit width) per Patent #14
- [ ] Test coverage ≥ 80% on `lang/parser/` and `lang/profiler/`
- [ ] Integration test: parse + profile + type-check all 10 examples

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
