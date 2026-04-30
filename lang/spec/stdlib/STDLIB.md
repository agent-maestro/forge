# EML-lang Standard Library

The stdlib is a set of `.eml` modules that ship with Forge.
Every backend can compile them. They serve double duty as
canonical implementations and as documentation for what is
idiomatic in EML-lang.

## Module index

| Module | File | Functions | Constants |
|--------|------|----------:|----------:|
| `math`     | `math.eml`     | 15 |  4 |
| `ml`       | `ml.eml`       | 13 |  0 |
| `control`  | `control.eml`  | 12 |  0 |
| `signal`   | `signal.eml`   | 11 |  3 |
| `linalg`   | `linalg.eml`   | 13 |  0 |
| `constants`| `constants.eml`| 0  | 16 |

## Function index

### `math` — composite math primitives

The base transcendentals (`exp`, `ln`, `sin`, `cos`, `tan`, `sqrt`,
`pow`, `abs`, `clamp`, `asin`, `acos`, `atan`, `sinh`, `cosh`,
`tanh`) are language **builtins**, not stdlib functions — the
parser dispatches them straight to dedicated AST nodes. The
math module only adds composites built on top of those.

| Function | Chain order | Notes |
|----------|------------:|-------|
| `lerp(a, b, t)`               | 0 | Linear interpolation |
| `smoothstep(t)`               | 0 | `3t^2 - 2t^3` |
| `sq(x)` / `cube(x)`           | 0 | Power shortcuts |
| `sign01(x)`                   | 0 | Clamp to `[-1, 1]` |
| `log_b(x, b)`                 | 2 | `ln(x)/ln(b)` (two lns compose) |
| `log2(x)` / `log10(x)`        | 1 | Hard-coded `LN2`/`LN10` |
| `exp2(x)` / `exp10(x)`        | 1 | Mirror of log2/log10 |
| `hypot2(x,y)` / `hypot3(x,y,z)` | 1 | Euclidean distance |
| `atan2_pos_x(y,x)`            | 2 | Single-quadrant scaffold |
| `radians(deg)` / `degrees(rad)` | 0 | Unit conversion |

### `ml` — neural-network activation primitives

Split out of `math` in 2026-04 so ML code can `use stdlib::ml;`
without pulling in the rest of the math module.

| Function | Chain order | Notes |
|----------|------------:|-------|
| `sigmoid(x)`                  | 1 | `1 / (1 + exp(-x))` |
| `sigmoid_alt(x)`              | 2 | `tanh(x/2)/2 + 1/2` -- SuperBEST rewrites to canonical |
| `softplus(x)`                 | 2 | `ln(1 + exp(x))` |
| `swish(x)`                    | 1 | `x * sigmoid(x)` |
| `gelu(x)`                     | 1 | tanh-based BERT/GPT form |
| `relu(x)` / `leaky_relu(x, alpha)` | 0 | clamp-based |
| `elu(x, alpha)`               | 1 | Exponential linear unit |
| `selu(x)`                     | 1 | Scaled ELU; self-normalizing |
| `mish(x)`                     | 3 | `x * tanh(softplus(x))` |
| `hard_sigmoid(x)` / `hard_tanh(x)` | 0 | Piecewise-linear, FPGA-cheap |
| `hard_swish(x)`               | 0 | Mobile-inference swish approximation |

### `control` — PID, filters, saturation, slew

| Function | Chain order | Notes |
|----------|------------:|-------|
| `pid` / `pid_anti_windup`     | 0 | Plain + saturation-clamped |
| `pid_integrate`               | 0 | Trapezoid step for integral |
| `lpf1` / `hpf1`               | 0 | 1st-order low/high pass |
| `complementary`               | 0 | Sensor-fusion blend |
| `saturate(x, limit)`          | 0 | Symmetric clamp |
| `dead_zone(x, threshold)`     | 0 | `x - clamp(x, ±t)` |
| `rate_limit` / `slew`         | 0 | Step / time-rate limiting |
| `kalman1d_update` / `_predict`| 0 | 1-D Kalman, returns `(est, P)` |

### `signal` — DSP primitives

| Function | Chain order | Notes |
|----------|------------:|-------|
| `wave_sine` / `wave_cosine`    | 2 | Single-harmonic |
| `wave_triangle`                | 6 | 3-term Fourier sum |
| `biquad_step`                  | 0 | Direct-Form-I coeffs |
| `biquad_state_update`          | 0 | History buffer shift |
| `fir3` / `fir5`                | 0 | Small fixed FIR |
| `box_muller(u1, u2)`           | 4 | Single Gaussian sample |
| `box_muller_pair`              | 4 | Both Gaussian samples |
| `linear_to_db` / `db_to_linear`| 1 | dB conversions |

### `linalg` — small fixed-size linear algebra

Every vector / matrix is passed component-by-component, every
multi-output result is returned as a tuple.

| Function | Chain order | Notes |
|----------|------------:|-------|
| `vec3_dot` / `vec3_norm_sq`    | 0 | Pure dot products |
| `vec3_norm`                    | 1 | sqrt of norm-sq |
| `vec3_cross` / `vec3_scale`    | 0 | Tuple return |
| `vec3_normalize`               | 1 | Tuple return |
| `quat_mul` / `quat_conj`       | 0 | Tuple return |
| `quat_norm_sq`                 | 0 | Pure dot |
| `quat_normalize`               | 1 | Tuple return |
| `mat3_det` / `mat3_trace`      | 0 | Hand-expanded 3x3 |
| `mat3_vec3`                    | 0 | Matrix * vector |

### `constants` — physical + mathematical

`PI`, `E`, `PHI`, `GAMMA`, `c`, `h`, `hbar`, `k_B`, `G`, `e_C`,
`N_A`, `R_gas`, `eps0`, `mu0`, `m_e`, `m_p`. CODATA-2018 values
where applicable.

## Stability guarantee

Stdlib modules are NOT under the same "no breaking changes" rule
as the language spec. Functions can be deprecated, signatures can
evolve. But:

- Every change to a stdlib function MUST update the matching test
- Every backend MUST agree on every stdlib function's output
  (verified by `tests/stdlib/`)
- Stability bumps trigger a CHANGELOG entry

Tests live in `tests/stdlib/test_stdlib.py` and verify:

1. Every `.eml` file parses
2. Every function profiles cleanly (no `error` status)
3. Every declared `chain_order <= N` holds against the
   profiler's inference
4. Every function compiles to C (and to Rust when stable)
