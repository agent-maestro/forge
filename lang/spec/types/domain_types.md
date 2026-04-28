# Domain Types

**Status:** SCAFFOLD

Domain restrictions on function inputs (e.g. `domain: x > 0`)
are first-class type constraints. The compiler:

- Statically checks call sites against declared input domains
- Inserts runtime guards when the call-site domain cannot be
  proven to satisfy the callee's declaration
- Threads domain bounds through verification artifacts
  (Lean theorem hypotheses; SMT preconditions)

## Common domain predicates

| Predicate | Meaning | Typical use |
|-----------|---------|-------------|
| `x > 0` | Positive reals | `ln`, `sqrt`, `pow(x, b)` for non-int b |
| `x >= 0` | Non-negative reals | `sqrt` (allowing zero) |
| `lo <= x <= hi` | Bounded interval | Most physical sensors |
| `abs(x) < 1` | Open unit interval | `asin`, `acos`, `atanh` |
| `x != 0` | Non-zero | `1/x` |

## Inference

The checker propagates domain constraints through arithmetic:
- `x > 0 && y > 0 ⟹ x + y > 0`
- `x > 0 && y > 0 ⟹ x * y > 0`
- `x in [0, pi/2] ⟹ sin(x) in [0, 1]`

When the propagation can't prove the callee's domain, the
compiler emits a guard. With `--strict`, missing proofs become
errors instead.
