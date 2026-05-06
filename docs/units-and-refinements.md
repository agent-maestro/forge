# Units and refinement types

A focused guide to EML's two type-level safety nets:

- **Units** (Phase A/B): every numeric value carries a dimension
  (`Hz`, `m/s^2`, `kg`, …) and the type checker rejects programs
  that mix incompatible quantities.
- **Refinement types** (Phase C/D): every numeric value can carry
  a value-level predicate (`Real{x | 0.0 <= x && x <= 1.0}`) that
  the compiler propagates to runtime guards on codegen targets and
  to theorem hypotheses on formal-verification targets.

Together they catch "the docs say 0–1, but the API doesn't" bugs
at compile time, before a single line of generated code runs.

## Why

> *On 23 September 1999 the Mars Climate Orbiter disintegrated
> in the Martian atmosphere because one team's flight-software
> emitted thrust impulse in pound-seconds and the other team's
> trajectory module read it as newton-seconds. A 4.45× unit
> mismatch slipped through every review and every test because
> the type system was `double` on both sides.*

EML's units catch the Mars Climate Orbiter bug at parse time:
`thrust_impulse: Real[N*s]` cannot be assigned to a parameter
typed `Real[lbf*s]` without an explicit conversion. Refinements
extend the same idea to value bounds: `up_hold: Real{u | 0.0 <= u
&& u <= 1.0}` puts the bound *in the type*, where the compiler
sees it on every backend rather than burying it in a `requires`
clause.

## Unit declarations

```eml
unit Hz = 1/s;
unit g  = 1e-3 * kg;
unit hp = 745.7 * W;
```

The right-hand side is an expression over the seven SI base units
(`s`, `m`, `kg`, `A`, `K`, `mol`, `cd`) plus the standard
derived units (`Hz`, `N`, `Pa`, `J`, `W`, `V`, `C`, `Ω`, …)
already known to the unit table. The compiler resolves the
declaration to a base-unit signature and a scale factor.

### Bracketed unit annotations

Anywhere a type appears (parameter, return type, type alias,
constant) you can attach a unit:

```eml
const SAMPLE_RATE: Real[Hz] = 48000.0;

fn audio_pole(f: Real[Hz], fs: Real[Hz]) -> Real
    where chain_order <= 1
{
    exp(-3.14159265358979 * f / fs)
}
```

The unit checker (Phase B) runs *before* the optimizer and walks
every binop / call / assign / return. `f / fs` produces
`Real[1]` (dimensionless); multiplying by `Real[s]` would surface
as `UnitTypeError` at the call site.

## Refinement syntax

A refinement type is `BaseType{binder | predicate}`:

```eml
fn clamp01(x: Real{p | 0.0 <= p && p <= 1.0}) -> Real { x }
```

The binder (`p` here) names the value being constrained. Inside
the predicate you can use:

| Operator/builtin | Allowed |
|---|---|
| Arithmetic: `+ - * / %` | yes |
| Comparison: `== != < <= > >=` | yes |
| Boolean: `&& \|\| !` | yes |
| `abs(x)`, `min(a, b)`, `max(a, b)` | yes |
| Module-level constants | yes |
| Function parameters (cross-param refs) | yes — but recorded as a deferred Lean obligation |
| Transcendentals (`exp`, `sin`, …) | **no** — would require an SMT solver |

The predicate sub-language is deliberately decidable so that the
auto-splicer and Lean lowering can stay sound without an SMT
backend.

### Combined form: unit + refinement

```eml
type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};

fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0}) -> Real
    where chain_order <= 1
    requires (fs > f)
{
    exp(-3.14159265358979 * f / fs)
}
```

Order of suffixes is fixed: `BaseType[unit]{binder | pred}`.
Aliases that carry both fields propagate them onto every parameter
that names the alias.

### Return refinements

```eml
fn rod_sensitivity(wavelength_nm: Real{w | 300.0 <= w && w <= 800.0})
    -> Real{r | 0.0 <= r && r <= 1.0}
    where chain_order <= 1
{
    exp(-((wavelength_nm - 498.0) * (wavelength_nm - 498.0)) / (2.0 * 50.0 * 50.0))
}
```

The return refinement uses any binder you want — only the
predicate body matters. On Lean targets, the return refinement
becomes the theorem's *conclusion* (instead of a hypothesis).

## Auto-splicer behavior

`requires` and `ensures` clauses still work — refinements never
deprecate them. But when a clause references exactly one parameter
(or `result` for `ensures`), the auto-splicer can fold it into
the parameter's refinement.

```bash
eml-compile my_kernel.eml --strict-refinements --target lean
```

With `--strict-refinements` enabled:

- `requires (abs(error) <= 100.0)` on parameter `error` → folded
  into `error: Real{e | abs(e) <= 100.0}`.
- `ensures (0.0 <= result && result <= 1.0)` → folded into the
  return refinement `Real{r | 0.0 <= r && r <= 1.0}`.
- `requires (rate * dt < vol * sqrt(dt))` → **stays as-is**
  (multi-variable; touches `rate`, `dt`, `vol`).

With `--strict-refinements` **OFF** (the default), the splicer is
a no-op: output is byte-identical to pre-Phase-C compilations.
Use this flag to migrate kernels gradually without churning unrelated
backends.

The auto-splicer surfaces in `--explain` output: each folded
clause shows up as a `[refinement-splicer] <fn>: ...` note.

## Per-backend lowering

Each backend lowers refinements to its native guard or hypothesis
form. The semantic effect is "the runtime / the proof system
checks `predicate` holds for the bound parameter / return value
before the body runs (or as the theorem's conclusion)".

| Target | Refinement on parameter `x: Real{p \| P(p)}` |
|---|---|
| C | `assert(P(x) && "fn: refinement violated on x: P(x)");` |
| C++ | `assert(P(x) && "fn: refinement violated on x: P(x)");` |
| Rust | `debug_assert!(P(x), "fn: refinement violated on x: P(x)");` |
| Python | `assert P(x), "fn: refinement violated on x: ..."` |
| Java | `if (!(P(x))) throw new IllegalArgumentException("fn: refinement violated on x: ...");` |
| Kotlin | `require(P(x)) { "..." }` |
| C# | `Debug.Assert(P(x), "...");` |
| Swift | `precondition(P(x), "...")` |
| Go | runtime check; `panic` on violation |
| JavaScript | `if (!(P(x))) throw new Error(...)` |
| Luau | `assert(P(x), "...")` |
| GDScript | `assert(P(x), "...")` |
| MATLAB | `assert(P(x), '...')` |
| HLSL | early-return-default + comment |
| GLSL / GLSL ES | early-return-default + comment |
| WGSL | early-return-default + comment |
| Metal | early-return-default + comment |
| LLVM IR | `call void @llvm.assume(...)` |
| WebAssembly | runtime check via host import |
| Verilog / SystemVerilog | `assert property (...)` (when synthesis target supports it; comment otherwise) |
| VHDL | `assert ... severity failure;` |
| Chisel/FIRRTL | `chisel3.assert(...)` |
| Ada/SPARK | `Pre => P(X)` aspect on the subprogram |
| AUTOSAR C | `Det_ReportError(...)` if the `requires` translates to a development-detection check |
| AADL | comment annotation |
| ROS 2 | `RCLCPP_ERROR + return` on violation |
| Lean 4 | `(h_x : P x)` hypothesis on theorem |
| Coq | `Hypothesis h_x : P x.` |
| Isabelle/HOL | `assumes h_x: "P x"` |
| Solidity | `require(P(x), "...");` |

Return refinements lower symmetrically — for codegen targets the
guard runs after computing the result; for formal-verification
targets the predicate becomes the conclusion of the theorem.

## Migration tips

When porting a kernel from `requires` / `ensures` to refinements:

1. **Pick clauses that reference one variable.** Multi-variable
   invariants (`x < y`, `rate * dt < vol`, …) cannot be expressed
   as refinements — keep those as `requires`. The auto-splicer
   bails on them automatically.
2. **Avoid transcendentals in predicates.** `requires (sin(x) <
   0.5)` cannot become a refinement — the predicate sub-language
   is decidable on purpose. Keep transcendental constraints as
   `requires` clauses.
3. **Watch the binder.** Inside `Real{x | P(x)}`, the binder is
   `x`, *not* the parameter name. The compiler alpha-renames at
   the use site, so `Real{p | abs(p) <= 100.0}` on a parameter
   `error` works the same as `Real{error | abs(error) <= 100.0}`.
   Pick whichever name is most readable in the predicate.
4. **`ensures (... result ...)` → return refinement.** A
   single-`result` postcondition like `ensures (0.0 <= result &&
   result <= 1.0)` becomes a return refinement
   `Real{r | 0.0 <= r && r <= 1.0}`. The function body must still
   prove this for the Lean theorem to discharge.
5. **Use type aliases for repeated shapes.** Once the same
   refinement appears on three or more parameters, lift it into a
   `type` declaration:

   ```eml
   type UnitInterval = Real{u | 0.0 <= u && u <= 1.0};

   fn lerp(a: UnitInterval, b: UnitInterval, t: UnitInterval) -> UnitInterval
       where chain_order <= 0
   {
       a + (b - a) * t
   }
   ```
6. **Migrate one kernel at a time.** Compile to every backend
   you target (`--target all`) and diff the emitted code; the
   refinement-violation message tag is the only expected change
   for non-formal targets. Lean output gains
   `(h_<param> : ...)` hypotheses.

## End-to-end example: the Phase C demo

`examples/audio_pole_refined.eml` exercises the full feature set:

```eml
unit Hz = 1/s;

type AudibleFreq = Real[Hz]{f | 20.0 <= f && f <= 22000.0};

fn audio_pole(f: AudibleFreq, fs: Real[Hz]{x | x > 0.0})
    -> Real{r | 0.0 <= r && r < 1.0}
    where chain_order <= 1
    requires (fs > f)
{
    exp(-3.14159265358979 * f / fs)
}
```

This kernel demonstrates:

- a unit declaration (`unit Hz = 1/s;`)
- a type alias combining unit + refinement
- a parameter using the alias
- a parameter with both a unit and a refinement
- a return-position refinement
- a multi-variable `requires` clause that stays as-is

Compile to every target with `eml-compile audio_pole_refined.eml
--target all` and inspect the per-backend guards.

---

## See also

- [`language-reference.md`](language-reference.md) — full syntax
  reference including the predicate sub-language.
- [`verify-guide.md`](verify-guide.md) — refinements as the
  primary contract form for Lean / Coq / Isabelle targets.
- [`examples/audio_pole_refined.eml`](../examples/audio_pole_refined.eml)
  — the canonical Phase C demo.
- [`examples/pid_controller.eml`](../examples/pid_controller.eml)
  — Phase F migration of the textbook PID controller.
