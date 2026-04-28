# EML-lang — Type System

**Status:** SCAFFOLD

---

## Overview

EML-lang's type system has three layers, each enforced statically:

1. **Numeric type** (`f64`, `f32`, `f16`, `bf16`, `fixed<W,F>`, `int`,
   `bool`)
2. **Chain-order constraint** (Pfaffian complexity bound)
3. **Domain + precision constraints** (input restrictions, output
   tolerance)

---

## See also

- `chain_order_types.md` — chain-order inference rules
- `domain_types.md` — domain restrictions (e.g. `x > 0` for ln)
- `precision_types.md` — precision requirements + bound checking

---

## Inference

The compiler infers the chain order of every expression from the
operators it uses, propagating bounds upward. A function's
declared `where chain_order <= N` clause is a CONTRACT — the
type checker rejects any body whose inferred bound exceeds `N`.

The same applies to domain + precision: an `arrhenius` function
declared `domain: T > 0` cannot be invoked in a context that
permits `T <= 0` without an explicit guard.

---

## Errors

Type errors carry full context — the offending expression, the
inferred bound, the declared bound, and a one-line suggestion
on how to fix.

```
error[E001]: chain_order bound exceeded
   --> sigmoid.eml:6:5
    |
  6 |     1.0 / (1.0 + exp(-x))
    |     ^^^^^^^^^^^^^^^^^^^^^ inferred chain_order = 2,
    |                           but declared <= 1
    |
   = note: exp contributes chain_order 1; nesting in division
           lifts the expression to 2.
   = help: relax the constraint to `where chain_order <= 2`,
           or replace exp with a chain-0 polynomial approximation.
```
