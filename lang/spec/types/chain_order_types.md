# Chain-order Types

**Patent reference:** #21 (chain-order types)
**Underlying theory:** Khovanskii (1991) Pfaffian functions; the
chain-order additivity rule (Patent #15) for composite expressions.

---

## Inference rules

For an expression `e`, write `co(e)` for its inferred chain order.

| Construct | Rule |
|-----------|------|
| Constant | `co(c) = 0` |
| Variable | `co(x) = 0` |
| `a + b`, `a - b`, `a * b`, `a / b` | `max(co(a), co(b))` |
| `exp(a)` | `1 + co(a)` |
| `ln(a)` | `1 + co(a)` (with `domain: a > 0`) |
| `sin(a)`, `cos(a)` | `2 + co(a)` (real path; complex Euler) |
| `tan(a)` | `2 + co(a)` |
| `sinh(a)`, `cosh(a)`, `tanh(a)` | `1 + co(a)` (just exp combinations) |
| `sqrt(a)` | `1 + co(a)` |
| `pow(a, n)` (integer n) | `co(a)` |
| `pow(a, b)` (general b) | `1 + max(co(a), co(b))` |
| `erf(a)` | `2 + co(a)` (T_erf tower) |
| `J_0(a)` | `3 + co(a)` (T_J tower) |
| `Ai(a)` | `3 + co(a)` (T_Ai tower) |
| `Gamma(a)` | `2 + co(a)` (T_Gamma tower) |
| `LambertW(a)` | `2 + co(a)` (T_W tower) |

---

## Why the bounds matter

The chain order bounds:
- **Number of zeros** on a closed bounded interval (Khovanskii)
- **Numerical stability** in fp16/fp32 evaluation (per E-193 results)
- **FPGA resource cost** when allocated to transcendental units
- **Verification difficulty** when emitting Lean theorems

A function declared `where chain_order <= 2` can be guaranteed to
have a finite zero count, can be allocated a single shared
transcendental unit on FPGA, and can be verified by induction on
chain depth.

---

## Composition: the additivity rule

For an expression containing PNE-primitive occurrences, the
EFFECTIVE chain order over the whole AST is the SUM of the
chain orders of each occurrence (Patent #15). This is what
gives chain-order types their compositional meaning.

Reference data: `monogate-research/exploration/9th-tower-promotion-2026-04-27/`
verified the additivity rule on 25/25 single-primitive + composite
PNE expressions.

---

## When the type checker yells at you

```
error[E001]: chain_order bound exceeded
```

This means your function's body is more complex than the
contract permits. Three fixes:

1. **Relax the bound.** If the function genuinely needs higher
   chain order (e.g. you're using sin nested in exp), bump the
   declared bound. Cost: harder to verify, more FPGA resources.

2. **Replace a transcendental with a polynomial.** If precision
   permits, substitute `exp(x)` near the origin with its Taylor
   series (chain order 0). Cost: precision degrades.

3. **Restrict the domain.** Many high-chain-order expressions
   reduce to lower-chain-order forms within specific domains
   (e.g. `tan` on `(-pi/4, pi/4)` is well-approximated by
   `x + x^3/3`). Cost: input domain shrinks.

---

## See also

- `monogate-research/data/lean.md` for the formal chain-order
  definition in Lean
- `monogate-research/exploration/E201_extended_atlas/independence_table.json`
  for the full 10-tower census with chain orders
