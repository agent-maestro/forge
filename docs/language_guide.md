# Language Guide — write your first `.eml`

> A 20-minute tour of EML-lang, end to end. By the end you'll have
> written, profiled, and compiled your own pipeline to C, Python, and
> Verilog from one source.

---

## What an `.eml` file looks like

```eml
// hello.eml -- the smallest legal program.

module hello;

@target(c, rust, python)
fn add(x: f64, y: f64) -> f64
  where chain_order <= 0
{
    x + y
}
```

That's a complete, compilable EML-lang program. Six lines, three
ideas:

1. `module hello;` — every file declares its module.
2. `@target(c, rust, python)` — annotation. Tells the compiler this
   function is meant to be emitted to those backends.
3. `fn add(...) -> f64 where chain_order <= 0 { x + y }` — function
   declaration with a **chain-order constraint**. The compiler
   infers the actual chain order and refuses to compile if it
   exceeds 0.

Save it as `hello.eml` and profile it:

```
$ eml-compile hello.eml --profile-only
# Module: hello  (1 fn, 0 const, 0 type)

  add
    status: ok    chain_order: 0    cost_class: p0-d2-w0-c0
    fpga: 2 MAC, 0 exp, 0 ln, 0 trig (4 cy @ 32-bit)
```

`chain_order: 0` matches the `<= 0` constraint — the build passes.

---

## Anatomy of an `.eml` file

```eml
// 1. Module declaration (required).
module my_module;

// 2. Imports (optional).
use stdlib::math::{lerp, hypot2};
use stdlib::control;
use local::helpers;          // sibling .eml file in same directory

// 3. Type aliases (optional).
type StableSignal = Real where chain_order <= 2;

// 4. Module constants (optional).
const PI: f64 = 3.14159265358979323846;
const MAX_GAIN: f64 = 100.0;

// 5. Annotations on functions (optional).
@target(fpga, clock_mhz = 100)
@verify(lean, theorem = "my_function_safe")

// 6. Function declaration (one or more).
fn my_function(x: Real, y: Real) -> StableSignal
  where chain_order <= 2,
        domain: x > 0.0,
        precision: 1e-9
    requires (y >= 0.0)
    ensures  (result < MAX_GAIN)
{
    let z = hypot2(x, y);
    let scaled = lerp(0.0, MAX_GAIN, z / 100.0);
    clamp(scaled, 0.0, MAX_GAIN)
}
```

The eight elements you'll use most:

- **`module name;`** — the file's identity.
- **`use stdlib::path;`** — pull in pre-verified library functions.
- **`type Alias = ...`** — define constrained numeric types.
- **`const NAME: TYPE = ...;`** — module-level constants.
- **`@target(...)`** — emit to specific backends.
- **`@verify(lean, theorem = "...")`** — emit a Lean theorem.
- **`where chain_order <= N`** — Pfaffian-depth constraint.
- **`requires` / `ensures`** — preconditions / postconditions.

---

## Types you can declare

```eml
type ChainZeroSignal     = Real where chain_order <= 0;
type StableSignal        = Real where chain_order <= 2;
type BoundedAngle        = Real where domain: -3.14159 < x < 3.14159;
type PreciseSignal       = Real where precision: 1e-12;
```

A type alias bundles a refinement constraint with the underlying
numeric type. Anywhere the alias is used as a return or parameter
type, the constraint flows into the type checker.

The numeric primitives are `f64`, `f32`, `f16`, `bf16`, `Real` (alias
for `f64`), and the integer family (`u8` … `u64`, `i8` … `i64`,
`bool`). For typical control + signal work you want `Real` (gives
you the best optimizer + verification support).

---

## Annotations

| Annotation                              | Effect |
|-----------------------------------------|--------|
| `@target(c)`, `@target(rust)`, `@target(python)`, `@target(llvm)`, `@target(wasm)` | The function compiles to these software backends. |
| `@target(fpga, clock_mhz = N)`          | The FPGA allocator runs on this function. |
| `@target(fpga, precision = float32)`    | Force a specific FPGA precision. |
| `@verify(lean, theorem = "name")`       | Emit a Lean 4 theorem to verify the contract. |
| `@verify(smt, ...)`                     | Reserved for SMT / CBMC backends (Phase 2.5). |

If a function has no `@target`, it still compiles — `eml-compile
file.eml --target X` works regardless. The annotations just make
`--target all` smarter about which functions to include for which
backend.

---

## The `where` clauses

Three kinds:

```eml
fn safe_filter(x: Real) -> Real
  where chain_order <= 1,                // Pfaffian-depth bound
        domain: -1.0 < x && x < 1.0,     // input domain restriction
        precision: 1e-6                  // ULP guarantee at output
{
    sin(x)
}
```

- **`chain_order <= N`** — refuses to compile if the inferred
  chain order exceeds N. Catches a wide class of fp16 drift bugs.
- **`domain: <expr>`** — caller must respect the domain at call
  time. The Lean prover uses these as hypotheses when discharging
  `requires`.
- **`precision: <ulp>`** — target ULP budget. The optimizer's
  SuperBEST pass picks canonical forms with sufficient precision.

---

## `requires` / `ensures`

```eml
fn divide_safe(numerator: Real, denominator: Real) -> Real
    requires (denominator != 0.0)
    requires (abs(numerator) < 1.0e6)
    ensures  (abs(result) < 1.0e6)
{
    numerator / denominator
}
```

These are the function's **safety contract**. The Lean backend
emits a theorem of the form `∀ inputs : requires → ensures(body)`.
When the contract is closeable by the `eml_auto` tactic, the
generated `.lean` file checks clean inside `monogate-lean`'s Lake
project. When it isn't, the theorem ships with `sorry` and you
finish the proof by hand.

See [`verification_guide.md`](verification_guide.md) for the full
flow.

---

## Imports + selective use

```eml
// Whole-module import.
use stdlib::math;
use stdlib::control;

// Selective import.
use stdlib::math::{lerp, hypot2};

// Aliased import.
use stdlib::math::{lerp as interp};

// Local sibling file (same directory as this .eml).
use local::helpers;
```

The loader resolves imports by file path. The tree-shaker drops
imported functions nothing local actually calls — the emitted
artifact is proportional to what you used, not to the size of the
imported library.

The full stdlib lives in `lang/spec/stdlib/`:

- `math.eml` — lerp, smoothstep, log_b, exp2, hypot, atan2_pos_x, …
- `ml.eml` — sigmoid, swish, gelu, relu, leaky_relu, …
- `control.eml` — pid, pid_anti_windup, lpf1, hpf1, kalman1d, …
- `signal.eml` — biquad_step, fir3 / fir5, wave_*, box_muller, …
- `linalg.eml` — vec3_*, quat_*, mat3_*
- `constants.eml` — PI, E, GRAVITY, BOLTZMANN, …

---

## Using `forge.blocks`

If your pipeline is mostly canonical building blocks (sigmoid, PID,
biquad, Park transform, FFT butterfly, …) you can skip writing
EML source entirely. The `forge.blocks` Python package ships 34
pre-verified blocks where the parse + profile + FPGA allocation
have already happened at import time — compile time drops to
milliseconds.

```python
from forge.blocks.polynomial   import linear, quadratic
from forge.blocks.exponential  import sigmoid_block
from forge.blocks.transform    import park, dq0
from forge.blocks.control      import pid, kalman_1d
from software.backends.c_backend import CBackend

# Each block carries its pre-computed AST + chain order + cost class.
print(park.chain_order)         # -> 2
print(park.fpga_allocation)     # -> {'luts': 1700, 'dsps': 5, ...}

# Compose blocks: chain order = max(...) is enforced at compose time.
pipeline = linear >> sigmoid_block
print(pipeline.chain_order)     # -> max(0, 1) = 1

# Backends consume composed blocks like any module.
src = CBackend().compile(pipeline.to_module())
```

See [`forge/blocks/README.md`](../forge/blocks/README.md) for the
full block catalogue.

---

## `extern fn` — opaque external primitives

When a function's implementation lives outside EML-lang's reach
(a vendor library, a hand-written hot path, a hardware primitive),
declare it with `extern fn`:

```eml
module ecdsa;

extern fn montgomery_ladder_p256_x(
    scalar: ConstantTime,
    point_x: ConstantTime,
) -> ConstantTime;

@verify(lean, theorem = "ecdsa_scalar_mul_correct")
fn scalar_mul_x(scalar: ConstantTime, point_x: ConstantTime)
    -> ConstantTime
{
    montgomery_ladder_p256_x(scalar, point_x)
}
```

Extern declarations:

  - Have **no body** — just the signature, terminated by `;`.
  - Carry **no `requires` / `ensures` / `where` clauses** (the body
    is opaque, so there's nothing to constrain).
  - Are emitted as forward declarations by every backend:
    - C: `extern double montgomery_ladder_p256_x(double, double);`
    - Rust: `extern "C" { pub fn montgomery_ladder_p256_x(...) -> f64; }`
    - Lean: `opaque montgomery_ladder_p256_x : ℝ → ℝ → ℝ`
  - Are treated as leaf nodes by the profiler / inliner / tree-shaker.

Every industry vertical that wraps a vendor primitive (crypto,
high-performance signal processing, FPGA IP cores) uses this.

---

## libmonogate — the C / Rust runtime

Every `.eml` file that compiles to C or Rust links against the
**libmonogate runtime** (`software/runtime/c/libmonogate.h` and
the `monogate-sys` Cargo crate). It exposes the 9 EML-family
operators, standard math wrappers, ML activations, growth
dynamics, and **SuperBEST routing variants** (Patent #01) that
the compiler dispatches to when the optimizer detects drift risk:

| Symbol             | Purpose                                                  |
|--------------------|----------------------------------------------------------|
| `mg_eml(x, y)`     | The universal EML primitive: `exp(x) - log(y)`           |
| `mg_exp` / `mg_ln` | Standard math, drop-in for libm                          |
| `mg_sigmoid`       | `1 / (1 + exp(-x))`                                      |
| `mg_softplus`      | `log(1 + exp(x))`                                        |
| `mg_logistic`      | `K / (1 + exp(-r*(t-x0)))`                               |
| `mg_gompertz`      | `K * exp(-exp(-r*(t-x0)))`                               |
| `mg_tanh_route`    | Padé near zero / sign at saturation / exp form middle    |
| `mg_sigmoid_route` | Overflow-safe on the negative tail                       |
| `mg_softplus_route`| Saturates to `x` for x>20, `exp(x)` for x<-20            |
| `mg_safe_div`      | NaN-free saturating division                             |

You don't normally call these directly — the C backend emits them
automatically. But you can write `mg_*` calls by hand if you want
the routing variant on a specific node. The Lean correspondence
lives in [`MonogateEML/Runtime.lean`](https://github.com/agent-maestro/monogate-lean/blob/master/MonogateEML/Runtime.lean).

---

## `ml_routing` — opt-in pattern rewriter

When the optimizer marks a function `drift_risk = HIGH`, the
**ml_routing** pass (off by default) recognizes canonical activation
patterns and rewrites them to direct libmonogate runtime calls:

  - `1.0 / (1.0 + exp(-x))` → `mg_sigmoid_route(x)`
  - `ln(1.0 + exp(x))` → `mg_softplus_route(x)`

Enable when targeting C or Rust on a known-drifty workload:

```python
from lang.optimizer import optimize_module
mod = optimize_module(mod, ml_routing=True)
```

The pass is opt-in because the runtime symbols are libmonogate-specific —
the C / Rust backends resolve them naturally; the Python / LLVM-via-llc /
WASM-via-llc backends would need the runtime linked at the host level.
The drift-aware `NodeKind.TANH` dispatch (always-on) handles the
naive-tanh case independently.

---

## Common patterns

### A controller with state

```eml
fn pid_step(error: Real, integral: Real, prev_error: Real) -> Real
  where chain_order <= 0
{
    let derivative = error - prev_error;
    Kp * error + Ki * integral + Kd * derivative
}
```

State is passed in by the caller. The function itself is pure —
that's why it lands at chain_order 0.

### A safety wrapper

```eml
fn safe_command(raw: Real) -> Real
  where chain_order <= 0
    requires (abs(raw) < 1.0e6)
    ensures  (abs(result) <= 0.349)   // ±20° in radians
{
    clamp(raw, -0.349, 0.349)
}
```

The `clamp` is the only operation; the postcondition follows
trivially. `eml_auto` closes this inside Lean.

### A multi-target FPGA pipeline

```eml
@target(fpga, clock_mhz = 100, precision = float32)
@verify(lean, theorem = "pipeline_bounded")
fn pipeline(x: Real, theta: Real) -> Real
  where chain_order <= 2
{
    let envelope = exp(-x * 5.0);
    let carrier  = sin(theta);
    envelope * carrier
}
```

The FPGA allocator picks LUT/DSP/BRAM resources for this on the
target you pass via `--fpga-target`.

---

## Numbers + invariants

When you write `2.0 * x` the compiler folds the literal into the
optimizer's constant-folding pass. The emitted C reads
`2.0 * x` (the optimizer keeps human-readable form when it can).

Float literals carry full f64 precision. The Verilog backend
re-encodes them as Q-format fixed-point at the configured WIDTH /
FRAC; the C and Python backends keep them as-is.

Boolean literals are `true` / `false`; they emit as `1` / `0` in C
because C99's `_Bool` complicates header dependencies and we
prefer plain `int`.

---

## Where to look next

- [`software_targets.md`](software_targets.md) — compile to C, Rust,
  Python, LLVM IR, WebAssembly.
- [`hardware_targets.md`](hardware_targets.md) — compile to Verilog,
  VHDL, Chisel; pick a target FPGA / ASIC.
- [`verification_guide.md`](verification_guide.md) — `@verify(lean,
  ...)` blocks end-to-end.
- [`architecture/overview.md`](architecture/overview.md) — the
  pipeline diagram + every layer.
- [`api_reference/cli.md`](api_reference/cli.md) — every flag of the
  `eml-compile` CLI.
- `lang/spec/grammar/examples/` — 10 short demos, all working.
- `industries/<vertical>/*.eml` — 11 production-shape verticals.
