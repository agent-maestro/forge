# Phase 1 — Language

**Goal:** end-to-end parse + type-check of every example in
`lang/spec/grammar/examples/`, with chain-order types enforced.

## Milestones

- [ ] M1.1: ANTLR4 grammar generator wired into `lang/parser/`
- [ ] M1.2: AST node definitions stable (versioned in `lang/parser/ast_nodes.py`)
- [ ] M1.3: Lexer + parser for all 10 demo examples
- [ ] M1.4: Type checker enforces `chain_order <= N` clauses
- [ ] M1.5: Profiler integration: every parsed function emits a Pfaffian profile via `eml-cost.analyze`
- [ ] M1.6: Domain + precision constraint inference
- [ ] M1.7: Test coverage ≥ 80% on `lang/parser/` and `lang/profiler/`

## Out of scope (defer to Phase 2)

- Code generation
- Verification artifact emission

## Risk register

- Grammar ambiguities surface late if examples don't span
  enough of the syntax — keep adding examples as features land.
- Chain-order inference for `pow(a, b)` (general b) is subtle;
  may need a special case in the type checker.
