# Verify guide

Walking through `@verify`, contracts, the Lean output, and how to discharge `sorry` placeholders.

## Why verify?

Forge generates a Lean 4 file alongside every other target. With contracts, that file is not just a translation — it is a **theorem statement** that, if proven, gives you a machine-checked guarantee that your kernel satisfies its specification.

This is the difference between "we tested it on 10 million inputs" and "we proved it for all real inputs in the precondition domain."

## Writing a verifiable kernel

Start with a function that has clear pre- and post-conditions. A bounded PID controller is the canonical example.

```eml
module bounded_pid;

const KP: Real = 1.0;
const KI: Real = 0.2;
const KD: Real = 0.3;

@verify
fn pid_bounded(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
    requires (-1.0 <= error      && error      <= 1.0)
    requires (-1.0 <= integral   && integral   <= 1.0)
    requires (-1.0 <= derivative && derivative <= 1.0)
    ensures  (-1.5 <= result && result <= 1.5)
{
    KP * error + KI * integral + KD * derivative
}
```

Anatomy:

- **`@verify`** marks this function for strict verification: the Lean output gets a full `theorem pid_bounded_correct : ...` statement instead of just an axiom.
- **`requires`** clauses define the precondition. Together they constrain `(error, integral, derivative) ∈ [-1, 1]³`.
- **`ensures`** says: under those preconditions, the return value lies in `[-1.5, 1.5]`. Why 1.5? Because `1.0 + 0.2 + 0.3 = 1.5` is the worst case when all three inputs are at their bounds and the same sign.

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

For a complete safety-critical example with a working Lean proof, see `industries/aerospace/flight_control/autothrottle.eml` and the corresponding `industries/aerospace/flight_control/autothrottle.lean`. The kernel is a DO-178C-style autothrottle controller with:

- Three `requires` clauses bounding throttle, airspeed, and target.
- Two `ensures` clauses bounding the output and the integral state.
- A chain-order-0 body that `eml_auto` discharges automatically.

`lake build` on the bundled Lean project completes in under 30 seconds with no `sorry`.

---

Next: [FPGA guide](fpga-guide.md) for the hardware path, or back to [language reference](language-reference.md) for the contract syntax in detail.
