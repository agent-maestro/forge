# Verify guide

Walking through `@verify`, refinement types, `requires` / `ensures`
contracts, the Lean output, and how to discharge `sorry` placeholders.

## Why verify?

Forge generates a Lean 4 file alongside every other target. With
contracts, that file is not just a translation — it is a **theorem
statement** that, if proven, gives you a machine-checked guarantee
that your kernel satisfies its specification.

This is the difference between "we tested it on 10 million inputs"
and "we proved it for all real inputs in the precondition domain."

## Two contract forms

Forge supports two ways to express a contract:

1. **Refinement types** (Phase C, *primary form*). Single-variable
   bounds belong on the parameter or return type:

   ```eml
   fn lerp(a: Real, b: Real, t: Real{p | 0.0 <= p && p <= 1.0}) -> Real { ... }
   ```

2. **`requires` / `ensures` clauses** (still supported). Use these
   for multi-variable invariants and any condition involving
   transcendentals (which the refinement predicate sub-language
   intentionally rejects):

   ```eml
   fn implicit_volatility(rate: Real, dt: Real, vol: Real) -> Real
       requires (rate * dt < vol * sqrt(dt))
   { ... }
   ```

Both forms lower to the same per-backend guard or hypothesis form
(see [Per-backend lowering table](#what-backends-respect-contracts)).
The auto-splicer (behind `--strict-refinements`) folds single-
variable `requires` clauses into refinements automatically — see
[units-and-refinements.md](units-and-refinements.md#auto-splicer-behavior)
for migration tips.

## Writing a verifiable kernel

A bounded PID controller is the canonical example. Phase F migrates
single-variable input bounds to refinement types directly on the
parameters; the multi-variable `ensures` clauses on the output
stay as-is:

```eml
module bounded_pid;

const KP: Real = 1.0;
const KI: Real = 0.2;
const KD: Real = 0.3;

@verify
fn pid_bounded(error:      Real{e | -1.0 <= e && e <= 1.0},
               integral:   Real{i | -1.0 <= i && i <= 1.0},
               derivative: Real{d | -1.0 <= d && d <= 1.0}) -> Real
    where chain_order <= 0
    ensures  (-1.5 <= result && result <= 1.5)
{
    KP * error + KI * integral + KD * derivative
}
```

Anatomy:

- **`@verify`** marks this function for strict verification: the
  Lean output gets a full `theorem pid_bounded_correct : ...`
  statement instead of just an axiom.
- **Refinement types** on each parameter constrain
  `(error, integral, derivative) ∈ [-1, 1]³`. Each refinement
  becomes a hypothesis `(h_error : ...)`, `(h_integral : ...)`,
  `(h_derivative : ...)` on the generated theorem.
- **`ensures`** says: under those preconditions, the return value
  lies in `[-1.5, 1.5]`. Why 1.5? Because `1.0 + 0.2 + 0.3 = 1.5`
  is the worst case when all three inputs are at their bounds and
  the same sign.

The pre-Phase-F equivalent — three `requires (-1.0 <= x && x <= 1.0)`
clauses — still works and produces an equivalent theorem. Refinement
types are recommended for new kernels because the contract lives at
the type, where the unit / value bounds belong.

## Compiling to Lean

```bash
eml-compile bounded_pid.eml --target lean -o BoundedPid.lean
```

Output (abridged):

```lean
import MachLib

namespace BoundedPid

def KP : Float := 1.0
def KI : Float := 0.2
def KD : Float := 0.3

def pid_bounded (error : Float) (integral : Float) (derivative : Float) : Float :=
  KP * error + KI * integral + KD * derivative

theorem pid_bounded_correct
    (error integral derivative : Float)
    (h_e : -1.0 ≤ error ∧ error ≤ 1.0)
    (h_i : -1.0 ≤ integral ∧ integral ≤ 1.0)
    (h_d : -1.0 ≤ derivative ∧ derivative ≤ 1.0) :
    -1.5 ≤ pid_bounded error integral derivative ∧
    pid_bounded error integral derivative ≤ 1.5 := by
  unfold pid_bounded
  -- Forge inserts a tactic skeleton; for chain_order=0 this is
  -- typically `eml_auto` from MachLib.Tactics, which handles
  -- linear-arithmetic bounds via `linarith` + `nlinarith`.
  eml_auto
```

## Checking the proof

You need a Lean project that depends on MachLib. Forge ships scaffolding via:

```bash
eml-compile bounded_pid.eml --target solidity --audit-bundle
```

…which builds a complete bundle including a Lean snapshot. For standalone checking:

1. Set up a `lakefile.lean` that requires `MachLib`:

   ```lean
   require MachLib from git "https://github.com/agent-maestro/machlib" @ "main"
   ```

2. Drop `BoundedPid.lean` into the project and run:

   ```bash
   lake build
   ```

If Lean accepts it without `sorry`, you have a machine-checked proof that `pid_bounded` is bounded by [-1.5, 1.5] on its specified domain.

## How `sorry` works

For non-trivial proofs (anything with chain order ≥ 2, or `ensures` clauses involving transcendentals), Forge emits a `sorry` placeholder where the proof would go:

```lean
theorem complex_kernel_correct ...
    : <postcondition> := by
  unfold complex_kernel
  sorry  -- TODO: discharge using MachLib.Discovered.<lemma>
```

You then either:
- Replace `sorry` by hand using Lean tactics (`linarith`, `nlinarith`, `simp`, `ring`, `field_simp`, `interval_cases`, `decide`, …).
- Find a matching lemma in MachLib (`MachLib.Discovered.*` namespace) and apply it.
- Use the `eml_auto` tactic from `MachLib.Tactics`, which tries the common chains automatically.
- Submit the kernel to MachLib upstream — if it is broadly useful, the lemma gets discovered and the `sorry` is replaced repo-wide.

## MachLib integration

[MachLib](https://machlib.org) is the formal library of mathematical kernels with Lean proofs. Forge knows about it via the `--machlib-root` flag (default: `../machlib`):

```bash
eml-compile my_kernel.eml --target lean --machlib-root /path/to/machlib
```

When MachLib has a lemma matching your kernel's shape, Forge inserts a direct `apply MachLib.Discovered.<lemma>` instead of a `sorry`. The `--audit-bundle` mode copies every referenced Lean theorem into the bundle so auditors can verify the proof without the upstream repo.

## What backends respect contracts

| Target | `requires` becomes | `ensures` becomes |
|---|---|---|
| C | `assert(...)` | doc comment |
| C++ | `assert(...)` | doc comment |
| Rust | `debug_assert!(...)` | doc comment |
| Python | `assert ..., "..."` | doc comment |
| Java | `if (!(...)) throw new IllegalArgumentException(...)` | doc comment |
| Kotlin | `require(...)` | doc comment |
| Swift | `precondition(...)` | doc comment |
| C# | `Debug.Assert(...)` | XML doc comment |
| MATLAB | `assert(...)` | comment |
| Lean | hypothesis | conclusion of theorem |
| Coq | `Hypothesis` | `Theorem` goal |
| Isabelle/HOL | `assumes` | `shows` |
| Solidity | `require(...)` | NatSpec |
| Verilog/VHDL | assertion macro | comment |
| HLSL/Metal/GLSL/WGSL | comment | comment |

`ensures` is post-condition; firing one mid-execution is rarely useful, so we keep them as documentation in non-formal targets. The proof targets (Lean, Coq, Isabelle) are where `ensures` actually does work.

## Common pitfalls

**1. Floating-point reasoning is hard.** A bound like `result ≤ 1.5` over `Float` may fail to prove if the underlying arithmetic isn't ULP-clean. For chain-order-0 polynomial bodies, `linarith` over rationals usually works; for transcendentals, you'll need `MachLib.Discovered` lemmas.

**2. Domain restrictions matter.** `requires (x > 0.0)` for `ln(x)` is mandatory. Without it, the Lean output won't even type-check (Lean's `Real.log 0 = 0` convention will silently break your bound).

**3. `chain_order` must match the body.** If you write `where chain_order <= 0` but call `sin(x)`, Forge fails the compile. This is intentional — the type system enforces the verification budget.

## End-to-end example

For a complete public example with a working Lean proof, see `examples/pid_controller.eml`. The kernel is a textbook PID controller with:

- **Refinement types** on the three input parameters
  (`abs(error) <= 100.0`, etc.). The generated theorem carries
  three named hypotheses `h_error`, `h_integral`, `h_derivative`.
- Two `ensures` clauses bounding the output to `[OUT_MIN, OUT_MAX]`.
- A chain-order-0 body that `eml_auto` discharges automatically.

`lake build` on the emitted Lean file completes in seconds with no
`sorry`. For the Phase C demo combining units + refinements, see
`examples/audio_pole_refined.eml`.

Pre-verified domain kernels (DO-178C avionics, ISO 26262 powertrain, IEC 62304 medical, etc.) ship with Forge Pro — see <https://monogateforge.com/get-started>.

---

Continue learning:

- **[Engineering course — Lesson 3: Verification](https://monogate.dev/learn/eml/engineering#lesson-3)** — guided walkthrough of `@verify`, MachLib lemma matching, and discharging `sorry` placeholders against a real avionics kernel.
- [FPGA guide](fpga-guide.md) — pair the verified math with an FPGA synthesis target.
- [Language reference](language-reference.md) — full contract syntax (`requires`, `ensures`, `result`).
- [machlib.org](https://machlib.org) — browse the formal library of mathematical kernels with Lean proofs.
