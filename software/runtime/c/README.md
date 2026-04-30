# libmonogate — C runtime for EML-lang

Header-only C99 runtime that the EML-lang C backend
(`software/backends/c_backend.py`) emits calls into.

  - `libmonogate.h` — all operators (inline)
  - `libmonogate.c` — diagnostic table only
  - `tests/test_operators.c` — smoke tests (~50 asserts)

Mirrored verbatim by the Rust runtime in `../rust/` (`monogate-sys` crate).

---

## Operator categories

| Category    | Examples                                       | Count |
|-------------|------------------------------------------------|-------|
| core        | `mg_eml`, `mg_eal`, `mg_exl`, `mg_edl`, `mg_epl`, `mg_lediv`, `mg_elsb`, `mg_elad`, `mg_deml` | 9 |
| math        | `mg_exp`, `mg_ln`, `mg_sin`, `mg_tanh`, `mg_sqrt`, `mg_pow`, `mg_clamp`, … | 17 |
| activation  | `mg_sigmoid`, `mg_softplus`, `mg_relu`         | 3 |
| growth      | `mg_logistic`, `mg_gompertz`                   | 2 |
| arithmetic  | `mg_div`, `mg_safe_div`                        | 2 |
| routing     | `mg_tanh_route`, `mg_sigmoid_route`, `mg_softplus_route`, `mg_log1p_route`, `mg_expm1_route` | 5 |
| f32 mirror  | `mg_*_f32` of every f64 op above              | 16 |

Full catalog with decompositions: `data/operators.json`.

---

## SuperBEST routing (Patent #01)

The `_route` variants pick the canonical form by sub-domain to minimize
precision loss. They cost ~1 extra branch per call vs the naive form;
the C backend emits the routed variant only when the optimizer marks
a node `drift_risk=HIGH`.

### Why routing matters

| Op            | Naive form pitfall                          | Routed fix                                      |
|---------------|---------------------------------------------|-------------------------------------------------|
| `tanh(x)`     | catastrophic cancellation for `|x| < 1e-8`  | Taylor `x` near zero; `sign(x)` for `|x| > 20` |
| `sigmoid(x)`  | `exp(-x)` overflows for `x` very negative   | switch numerator/denominator on sign(x)         |
| `softplus(x)` | same overflow on positive tail              | return `x` for `x > 20`; `exp(x)` for `x < -20` |

`mg_log1p_route` and `mg_expm1_route` forward to libm `log1p`/`expm1`,
which carry their own series expansions for accuracy near zero.

---

## Chain-precision policy (Phase 3)

The hardware backend selects floating-point precision per-function
based on chain order:

| Chain order  | Precision  | Mirror |
|--------------|------------|--------|
| ≥ 3          | f64        | `mg_*` |
| 1–2          | f32        | `mg_*_f32` |
| 0            | f16 (promoted to f32 on host) | `mg_*_f32` |

The `_f32` mirrors exist for software targets that compile against
the same header; FPGA emission uses the explicit width on each
operator instance (CORDIC / poly / LUT module library, Phase 3.2).

---

## Domain-check macros

Inline operators include `MG_REQUIRE_*` macros for debug builds
(`-DMG_DEBUG`). In release builds they vanish to zero overhead.

```c
MG_REQUIRE_POSITIVE(y);   // assert(y > 0.0)
MG_REQUIRE_FINITE(x);     // assert(isfinite(x))
MG_REQUIRE_NONZERO(x);    // assert(x != 0.0)
```

---

## Build + test

```bash
# Build the test binary (any modern gcc / clang / cl / mingw)
cd software/runtime/c/tests
gcc -O2 -Wall -lm test_operators.c ../libmonogate.c -o test_operators
./test_operators

# Or the Rust mirror
cd ../../rust
cargo test
```

The Rust mirror runs in CI; the C tests are run on hosts with a
local C compiler (none on the canonical Windows dev box; the
EML-lang test corpus exercises the runtime indirectly via emitted
build/*.c files).

---

## Versioning

| File                     | Version |
|--------------------------|---------|
| `libmonogate.h`          | 0.1.0   |
| `monogate-sys` (Cargo)   | 0.1.0   |
| `data/operators.json`    | 0.2.0   |

Bump path: any new operator or routing variant → minor bump.
Breaking change to an existing signature → major bump (none yet).

---

## Status

  - ✅ Header-only inline runtime
  - ✅ Rust mirror with parity tests
  - ✅ SuperBEST routing for the 3 most drift-prone ops
  - ✅ f32 mirrors for chain-precision selection
  - ✅ Domain-check macros for debug builds
  - ⬜ Real EML-decomposition trig (`sin` / `cos` via complex Euler) — currently delegates to libm
  - ⬜ Lean correspondence (`monogate-lean/MonogateEML/Runtime.lean`) — declares each `mg_*` as an axiom and proves the algebraic identity vs libm; gates Forge Phase 2.4
  - ⬜ Remaining 14 of 23 family operators — locked upstream, not yet here
