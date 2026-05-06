# EML language reference

Complete reference for the EML language. Open this while you're coding.

## Table of contents

1. [Modules and imports](#modules-and-imports)
2. [Types](#types)
3. [Constants](#constants)
4. [Functions](#functions)
5. [Statements and expressions](#statements-and-expressions)
6. [Builtin functions](#builtin-functions)
7. [Chain-order constraints](#chain-order-constraints)
8. [Contracts (`requires` / `ensures`)](#contracts)
9. [Annotations (`@verify`, `@target`)](#annotations)
10. [Standard library modules](#standard-library-modules)
11. [Reserved keywords](#reserved-keywords)

---

## Modules and imports

Every `.eml` file starts with a `module` declaration. The name namespaces emitted code (Lean theorems, C struct names, Java class names).

```eml
module my_kernel;
```

Bring stdlib modules into scope with `use`:

```eml
use stdlib::math;
use stdlib::signal;
use stdlib::control;
```

Functions and constants from the imported module are then callable unqualified.

## Types

Three primitive types:

| Type | Width | Notes |
|---|---|---|
| `Real` | f64 | Default arithmetic type. Backends may narrow (HLSL → f32, Metal `half` for `f16`). |
| `Int` | i64 | Integer arithmetic. |
| `Bool` | 1 bit | `true` / `false`. |

Width-explicit aliases (used when targeting hardware or shaders):

| Alias | Lowering |
|---|---|
| `f64` | double-precision float |
| `f32` | single-precision float |
| `f16` | half-precision (Metal `half`, HLSL `float`, others fallback to f32) |
| `i32` / `i64` / `u8` / `u16` / `u32` / `u64` | fixed-width integers |
| `bool` | same as `Bool` |

Tuple return types are written as `(T1, T2, ...)`:

```eml
fn polar_to_xy(r: Real, theta: Real) -> (Real, Real)
    where chain_order <= 1
{
    (r * cos(theta), r * sin(theta))
}
```

Backends that lack tuple returns (C, HLSL, Metal, Java) auto-emit a result struct.

### Unit-bracketed types: `Real[unit]`

Any type can carry a dimensional **unit annotation** in square
brackets:

```eml
unit Hz = 1/s;

const SAMPLE_RATE: Real[Hz] = 48000.0;

fn audio_pole(f: Real[Hz], fs: Real[Hz]) -> Real
    where chain_order <= 1
{
    exp(-3.14159265358979 * f / fs)
}
```

The unit checker (Phase B) walks every binop / call / assignment /
return *before* the optimizer runs and rejects programs that mix
dimensions:

```eml
let bad = SAMPLE_RATE + 9.81;   // Real[Hz] + Real[m/s^2] -- UnitTypeError
```

Numeric literals coerce freely: `48000.0` becomes `Real[Hz]` when
the context requires a frequency. Division by a same-dimensioned
value produces `Real[1]` (dimensionless). Unit declarations are
expressions over the seven SI base units (`s`, `m`, `kg`, `A`,
`K`, `mol`, `cd`) plus the standard derived units already
known to the unit table.

### Refinement types: `Real{x | P(x)}`

A **refinement type** attaches a value-level predicate to any
base type:

```eml
fn lerp(a: Real, b: Real, t: Real{p | 0.0 <= p && p <= 1.0}) -> Real
    where chain_order <= 0
{
    a + (b - a) * t
}
```

The binder (`p` here) names the value the predicate constrains.
Inside the predicate body you can use:

- arithmetic (`+ - * / %`)
- comparison (`== != < <= > >=`)
- boolean combinators (`&& || !`)
- the builtins `abs(x)`, `min(a, b)`, `max(a, b)`
- module-level constants

You **cannot** call transcendentals (`exp`, `sin`, `ln`, `sqrt`,
…) from a predicate — the sub-language is deliberately decidable
so that the auto-splicer and Lean lowering can stay sound without
an SMT solver. Constraints involving transcendentals belong in a
`requires` clause.

Return positions can also carry a refinement:

```eml
fn rod_sensitivity(wavelength_nm: Real{w | 300.0 <= w && w <= 800.0})
    -> Real{r | 0.0 <= r && r <= 1.0}
    where chain_order <= 1
{
    exp(-((wavelength_nm - 498.0) * (wavelength_nm - 498.0)) / (2.0 * 50.0 * 50.0))
}
```

On a Lean target the parameter refinement becomes a hypothesis
`(h_wavelength_nm : ...)` and the return refinement becomes the
theorem's conclusion. On every codegen target the refinement
lowers to a runtime guard (`assert`, `require`, `precondition`,
…); see [verify-guide.md](verify-guide.md#what-backends-respect-contracts)
for the per-backend table.

### Combined: `Real[unit]{binder | predicate}`

A type can carry both a unit and a refinement. The order is
fixed:

```eml
type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};

fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0}) -> Real
    where chain_order <= 1
    requires (fs > f)
{
    exp(-3.14159265358979 * f / fs)
}
```

Type aliases that carry a unit and/or a refinement propagate both
fields onto every parameter that names the alias. See
[units-and-refinements.md](units-and-refinements.md) for a focused
guide to the unit + refinement system.

## Constants

```eml
const PI: Real = 3.141592653589793;
const KP: Real = 1.0;
const MAX_ITERATIONS: Int = 100;
```

Constants are file-scope and immutable. They emit as `static const` in C, `pub const` in Rust, `public static final` in Java, `constant` in Metal, `static const` in HLSL, etc.

## Functions

```eml
fn name(param: Type, ...) -> ReturnType
    where chain_order <= N
    requires (precondition)
    ensures  (postcondition)
{
    // body
}
```

A function body is a sequence of `let` bindings followed by a final expression that produces the return value. Forge emits with aggressive inlining hints (`inline`, `@inline(always)`, `#[inline(always)]`) on every backend.

### `extern fn`

Declares an FFI stub — useful for naming math you don't want Forge to lower (e.g., when you'll plug in a vendor library):

```eml
extern fn vendor_sqrt(x: Real) -> Real;
```

The `extern` body is compiled away; callers see the symbol as a forward declaration in the emitted output.

### Tuple destructuring

```eml
let (x, y) = polar_to_xy(r, theta);
```

## Statements and expressions

### `let`

```eml
let name = expression;
let typed: Real = expression;  // explicit type optional
```

Bindings are immutable. Re-binding the same name shadows the previous binding.

### `if` / `else`

```eml
if x > 0.0 {
    sqrt(x)
} else {
    0.0
}
```

`if` is an expression — both branches must have the same type. There is no statement-level `if`.

### Operators

| Category | Operators |
|---|---|
| Arithmetic | `+ - * / %` (modulo on integers only) |
| Comparison | `== != < <= > >=` |
| Logical | `&& \|\| !` |
| Bitwise (Int only) | `& \| ^ ~ << >>` |

Operator precedence follows C; parenthesize if in doubt.

### Comments

```eml
// single line
/// doc comment — kept in emitted output, becomes javadoc / rustdoc / etc.
```

## Builtin functions

All builtins are defined in `stdlib::math` but available without `use` in any function.

### Real → Real

| Builtin | Notes |
|---|---|
| `exp(x)` | natural exponential |
| `ln(x)` | natural log (also `log(x)` for compatibility) |
| `log2(x)` | base-2 log |
| `log10(x)` | base-10 log |
| `sqrt(x)` | square root |
| `cbrt(x)` | cube root |
| `abs(x)` | absolute value |
| `floor(x)` / `ceil(x)` / `round(x)` / `trunc(x)` | rounding |
| `sin(x)` / `cos(x)` / `tan(x)` | trig (radians) |
| `arcsin(x)` / `arccos(x)` / `arctan(x)` | inverse trig |
| `sinh(x)` / `cosh(x)` / `tanh(x)` | hyperbolic |
| `arcsinh(x)` / `arccosh(x)` / `arctanh(x)` | inverse hyperbolic |
| `exp10(x)` / `expm1(x)` / `log1p(x)` | numerically-stable variants |

### Real × Real → Real

| Builtin | Notes |
|---|---|
| `pow(b, e)` | b raised to e |
| `atan2(y, x)` | quadrant-aware arctan |
| `hypot(x, y)` | √(x² + y²), overflow-safe |
| `fmod(x, y)` | floating-point remainder |
| `min(a, b)` / `max(a, b)` | extrema |
| `eml(x, y)` | the EML primitive: `exp(x*ln(y))` — defined as a primitive so the cost analyzer treats it correctly. |

### Real × Real × Real → Real

| Builtin | Notes |
|---|---|
| `clamp(x, lo, hi)` | `max(lo, min(x, hi))` |
| `lerp(a, b, t)` | linear interpolation |
| `fma(a, b, c)` | fused multiply-add |
| `step(edge, x)` / `smoothstep(lo, hi, x)` | shader-style step functions |

The compiler analyzes each call site to compute the function's chain order. Callers that violate `where chain_order <= N` fail to compile.

## Chain-order constraints

EML's defining feature. Every expression has a **chain order** — the maximum nesting depth of transcendental functions (exp, ln, trig, …) in its evaluation tree. Polynomials are chain order 0; `sin(x)` is 1; `exp(sin(x))` is 2.

Declare a constraint on your function:

```eml
fn safe_pid(e: Real) -> Real
    where chain_order <= 0
{
    // body MUST be polynomial; calling sin/exp/etc. fails to compile
    KP * e
}
```

Use cases:

- **Hardware paths** — `where chain_order <= 0` guarantees zero CORDIC units in the FPGA build.
- **Stability bounds** — chain order ≥ 2 triggers a precision-drift warning on every backend.
- **Domain budgeting** — proven Pfaffian classes have known closed-form cost upper bounds.

If you don't add a `where` clause, the compiler still profiles the function and reports the chain order — it just doesn't enforce a bound.

## Contracts

### `requires`

Precondition. Lowered to:

- **Rust**: `debug_assert!(expr);`
- **C**: `assert(expr);`
- **Python**: `assert expr, "..."`
- **Java**: `if (!(expr)) throw new IllegalArgumentException(...);`
- **Swift**: `precondition(expr, "...")`
- **Lean**: a hypothesis on the generated theorem

```eml
fn divide(a: Real, b: Real) -> Real
    where chain_order <= 0
    requires (b != 0.0)
{
    a / b
}
```

### `ensures`

Postcondition. The compiler emits a doc-comment on every backend (`/// - forge.ensures: ...`), and the Lean output adds it to the theorem statement.

```eml
fn norm(x: Real) -> Real
    where chain_order <= 1
    ensures (0.0 <= result && result <= 1.0)
{
    1.0 / (1.0 + exp(-x))
}
```

`result` is the implicit name of the return value inside `ensures` clauses.

## Annotations

### `@verify`

Marks a function as safety-critical: the Lean backend generates a `theorem name_correct` instead of just an axiom, and the audit bundle includes it.

```eml
@verify
fn pid_bounded(error: Real) -> Real
    where chain_order <= 0
    requires (-1.0 <= error && error <= 1.0)
    ensures  (-1.5 <= result && result <= 1.5)
{
    KP * error
}
```

See [verify guide](verify-guide.md) for full details.

### `@target(fpga)`

Marks a function for FPGA synthesis. The hardware allocator (Patent #14) reads the chain-order and node-count profile and produces a per-function LUT/DSP/latency plan.

```eml
@target(fpga, vendor = "xilinx", device = "artix7", precision = "f32")
fn step(error: Real) -> Real
    where chain_order <= 0
{
    KP * error
}
```

In VS Code with the LSP, the FPGA status bar shows the live estimate. See [fpga guide](fpga-guide.md).

## Standard library modules

Bring with `use stdlib::<name>;`.

### `stdlib::math`

Mathematical constants (`PI`, `E`, `TAU`, `SQRT_2`, …) and the builtins listed above.

### `stdlib::signal`

DSP primitives: biquad filters, FIR/IIR step functions, FFT butterfly, windowing functions (Hann, Hamming, Blackman).

### `stdlib::control`

Control-system blocks: PID variants, lead-lag compensator, Kalman update, complementary filter, Park/Clarke transforms.

### `stdlib::linalg`

2D / 3D vector and matrix ops: dot, cross, norm, 3×3 matrix-vector multiply, 2×2 inverse.

### `stdlib::ml`

ML kernels: sigmoid, tanh, ReLU, GELU, softmax (1D), MSE, cross-entropy.

### `stdlib::constants`

Physical and engineering constants: `SPEED_OF_LIGHT`, `BOLTZMANN`, `STEFAN_BOLTZMANN`, …

## Reserved keywords

```
fn  let  const  if  else  return  true  false
module  use  extern  where  requires  ensures
chain_order  domain  precision  result
Real  Int  Bool  f16  f32  f64  i8  i16  i32  i64  u8  u16  u32  u64  bool
```

Identifiers that collide with backend keywords (e.g., `class` in Java, `kernel` in Metal) are auto-renamed to `name_` on emission. You don't need to worry about collisions when writing EML.

---

For the formal grammar, see `lang/spec/grammar/EmlLang.g4` in the repo.

For semantic details and the cost-conjecture model, see [monogate.dev/learn/eml/intro](https://monogate.dev/learn/eml/intro). For a deeper dive into chain orders, contracts, and the `@target` / `@verify` annotations in real engineering kernels, work through the [Engineering course](https://monogate.dev/learn/eml/engineering).
