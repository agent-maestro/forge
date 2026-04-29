# Verification Guide — `@verify(lean)` end-to-end

> Forge emits machine-checkable Lean 4 theorems from `.eml` source.
> The same `requires` / `ensures` clauses that the type checker
> reads at compile time become the theorem's hypothesis and goal.
> Discharged proofs ship as DO-178C / IEC 62304 / ISO 26262
> objective evidence.

---

## What `@verify(lean)` does

```eml
@verify(lean, theorem = "elevator_command_within_limits")
fn autopilot_step(pitch_setpoint: Real,
                  pitch_measured: Real,
                  pitch_integral: Real) -> Real
    requires (abs(pitch_setpoint) < 1.5708)   // ±π/2
    requires (abs(pitch_measured) < 1.5708)
    requires (abs(pitch_integral) < INTEGRAL_LIMIT)
    ensures  (abs(result) < ELEVATOR_MAX)
{
    let pitch_error = pitch_setpoint - pitch_measured;
    let rate_target = rate_controller(
        pitch_error, pitch_integral, pitch_measured,
    );
    clamp(Kr * rate_target, ELEVATOR_MIN, ELEVATOR_MAX)
}
```

When you run `eml-compile --target lean`, the compiler:

1. Lowers the `requires` clauses into a Lean `∀` hypothesis.
2. Lowers the function body into a Lean term-mode definition.
3. Emits a theorem of the form:

   ```lean
   theorem elevator_command_within_limits :
     ∀ (pitch_setpoint pitch_measured pitch_integral : ℝ),
       abs pitch_setpoint < 1.5708 →
       abs pitch_measured < 1.5708 →
       abs pitch_integral < INTEGRAL_LIMIT →
       abs (autopilot_step pitch_setpoint pitch_measured
                            pitch_integral) < ELEVATOR_MAX :=
   by eml_auto
   ```

4. The proof script `by eml_auto` invokes the EML-aware tactic
   from `monogate-lean/MonogateEML/Tactics.lean`. If the tactic
   closes the goal, the theorem checks clean inside the upstream
   `monogate-lean` Lake project. If it doesn't, the file ships
   with `sorry` and a TODO comment.

---

## The pieces

### `requires` clauses

These are the **preconditions** the theorem assumes. The type
checker also reads them — when `safe_caller` calls
`autopilot_step`, the type checker proves the `requires` from
`safe_caller`'s context.

```eml
fn autopilot_step(...) -> Real
    requires (abs(pitch_setpoint) < 1.5708)
    requires (denominator != 0.0)
    requires (input_count > 0)
{
    ...
}
```

Multiple `requires` clauses chain as logical `∧`. The Lean theorem
chains them as nested implications.

### `ensures` clauses

The **postcondition** — a property of the function's output. The
keyword `result` refers to the function's return value.

```eml
ensures  (abs(result) < ELEVATOR_MAX)
ensures  (result.0 + result.1 == 0.0)        // tuple-return
ensures  (result >= 0.0)
```

Tuple-returning functions can refer to `result.0`, `result.1`,
etc. for individual elements.

### `where domain:` clauses

These are **type-level** preconditions — they apply at every call
site, not just when the function is called from a verified caller.

```eml
fn safe_filter(x: Real) -> Real
  where chain_order <= 1,
        domain: -1.0 < x && x < 1.0
{
    sin(x)
}
```

A `domain` clause is stricter than a `requires` clause. The
profiler uses domain clauses to bound transcendental inputs (e.g.
to prove `tan(x)` stays away from the π/2 pole).

---

## The `eml_auto` tactic

Lives in `monogate-lean/MonogateEML/Tactics.lean`. It composes:

- **`norm_num`** — numerical normalization and rational arithmetic.
- **`linarith` / `nlinarith`** — linear / nonlinear arithmetic
  over ordered fields.
- **`positivity`** — proves `0 < expr` / `0 ≤ expr` for a wide
  class of expressions.
- **`field_simp`** — algebraic simplification.
- **`Real.{sin_le_one, neg_one_le_sin, exp_pos, …}`** — standard
  bounds from Mathlib.
- **EML-specific lemmas** — `eml_clamp_bounded`,
  `eml_chain_order_zero_polynomial`, `eml_pid_linear_in_gains`,
  etc.

For functions whose `ensures` is a clamp + a polynomial body,
`eml_auto` closes the goal in seconds. For deeper proofs you write
the proof yourself; the generated theorem statement is the contract
your hand-written proof must discharge.

---

## End-to-end flow

```
$ eml-compile autopilot.eml --target lean -o Autopilot.lean
wrote Autopilot.lean (1,237 bytes, 39 lines)

$ cp Autopilot.lean ../monogate-lean/MonogateEML/Autopilot.lean

$ cd ../monogate-lean

$ lake build MonogateEML.Autopilot
[1/1] Building MonogateEML.Autopilot
   ✓ MonogateEML.Autopilot

$ lake env lean MonogateEML.Autopilot.lean --print-axioms
elevator_command_within_limits depends on:
  - propext
  - Quot.sound
  - Classical.choice
```

The `--print-axioms` step is the gold standard — those three are
the standard Lean axioms, and nothing else (no `sorry`, no
`unsafe`) shows up. That's the artifact you submit as DO-178C
verification evidence.

---

## When `eml_auto` doesn't close

The generated `.lean` ships with `sorry` and a TODO comment:

```lean
theorem elevator_command_within_limits :
  ∀ (pitch_setpoint pitch_measured pitch_integral : ℝ),
    abs pitch_setpoint < 1.5708 →
    abs pitch_measured < 1.5708 →
    abs pitch_integral < INTEGRAL_LIMIT →
    abs (autopilot_step ...) < ELEVATOR_MAX :=
by
  -- TODO(eml_auto): tactic could not close this goal automatically.
  --   Likely cause: a non-linear coupling between rate_controller
  --   and the saturator that nlinarith can't unfold. Try unfolding
  --   rate_controller, then `nlinarith [Real.sin_le_one]`.
  sorry
```

You finish the proof by hand. The *statement* is still machine-
generated — you only fill in the proof script. When you push the
finished proof, the next `eml-compile` run won't overwrite your
work because the backend names the output file by the theorem name
and skips emitting if the existing file's theorem statement
matches.

When you build a recurring proof pattern by hand, fold it back
into `eml_auto` — see `monogate-lean/MonogateEML/Tactics.lean` for
the existing rule list. Adding a rule means future regenerations
close automatically.

---

## DO-178C / IEC 62304 / ISO 26262 evidence

The **theorem + axiom-list pair** is the artifact regulators care
about:

```
File:        MonogateEML/Autopilot.lean
Theorem:     elevator_command_within_limits
Status:      verified
Axioms used: propext, Quot.sound, Classical.choice
Hash:        sha256:1a2b3c4d...
Build date:  2026-04-29T15:32:18Z
Lake build:  ✓
```

For DO-178C Level A, that's "objective evidence of compliance with
the design assurance requirement." For IEC 62304 Class C
(life-supporting), it satisfies the verification phase of the
software development process. For ISO 26262 ASIL-D, it's a
Methods Group 5 artifact (formal verification of detailed design).

The verticals in `industries/<vertical>/` ship with a per-vertical
cert template that wires the theorem evidence into the regulator's
expected document layout.

---

## Worked example — clamping a control output

```eml
const MAX_TORQUE: f64 = 100.0;
const MIN_TORQUE: f64 = -100.0;

@verify(lean, theorem = "torque_within_envelope")
fn safe_torque(raw: Real) -> Real
  where chain_order <= 0
    requires (raw > -1.0e6)
    requires (raw <  1.0e6)
    ensures  (result >= MIN_TORQUE)
    ensures  (result <= MAX_TORQUE)
{
    clamp(raw, MIN_TORQUE, MAX_TORQUE)
}
```

Compile + verify:

```
$ eml-compile safe_torque.eml --target lean -o SafeTorque.lean
$ cp SafeTorque.lean ../monogate-lean/MonogateEML/SafeTorque.lean
$ cd ../monogate-lean
$ lake build MonogateEML.SafeTorque
[1/1] Building MonogateEML.SafeTorque
   ✓ MonogateEML.SafeTorque
```

The theorem closes via `eml_auto` — the proof reduces to the
`clamp` lemma in `Tactics.lean`. Submit the file as evidence.

---

## Reading the generated `.lean`

A typical output:

```lean
-- Generated by EML-lang Lean backend.
-- Source module: safe_torque
-- Theorem:       torque_within_envelope

import MonogateEML.Tactics

namespace MonogateEML

def safe_torque (raw : ℝ) : ℝ :=
  max MIN_TORQUE (min MAX_TORQUE raw)

theorem torque_within_envelope :
  ∀ (raw : ℝ),
    raw > -1.0e6 →
    raw <  1.0e6 →
    safe_torque raw ≥ MIN_TORQUE ∧
    safe_torque raw ≤ MAX_TORQUE :=
by
  intro raw _ _
  unfold safe_torque
  refine ⟨?_, ?_⟩
  · exact le_max_left _ _
  · exact min_le_left _ _

end MonogateEML
```

The `def` block is the function body lowered to Lean. The
`theorem` block is your contract. The `by` block is the proof —
generated automatically when `eml_auto` closes, hand-written when
it doesn't.

---

## Common patterns

### "Output bounded by a polynomial of inputs"

```eml
ensures (abs(result) <= 2.0 * abs(input_a) + 3.0 * abs(input_b))
```

`eml_auto` handles linear bounds. Nonlinear (squared, exp, sin)
bounds usually need a hand-written proof unless they fall into
known canonical forms (`sin ≤ 1`, `exp > 0`, etc.).

### "Output is a convex combination of inputs"

```eml
ensures (min_input <= result && result <= max_input)
```

Trivial for `lerp`-style bodies; `eml_auto` closes immediately.

### "Output preserves a quadratic invariant"

```eml
// Park preserves d² + q² = α² + β²
ensures (result.0 * result.0 + result.1 * result.1 ==
         alpha * alpha + beta * beta)
```

`ring_nf` plus `Real.sin_sq_add_cos_sq` closes this. `eml_auto`
recognizes the Park / Clarke / quaternion patterns and routes
accordingly.

---

## Verification status of pre-verified blocks

`forge.blocks` ships 34 blocks; many carry a `lean_theorem` field
with the literal Lean statement. Verification status:

```python
from forge.blocks import list_blocks
for b in list_blocks():
    has_theorem = bool(b.lean_theorem)
    print(f"{b.name:25s}  lean: {'YES' if has_theorem else 'no'}")
```

Whether each theorem is currently closed inside the
`monogate-lean` Lake project is tracked separately — the policy is
"ship the statement here, ship the proof in Lean." Don't claim a
theorem is verified on a public surface until the user has
personally `lake build`-checked it.

See [`forge/blocks/README.md`](../forge/blocks/README.md) for the
full block list.

---

## Where to look next

- [`language_guide.md`](language_guide.md) — `requires` / `ensures`
  / `where` syntax basics.
- [`industry_guides/aerospace.md`](industry_guides/aerospace.md) —
  worked DO-178C example.
- [`industry_guides/medical.md`](industry_guides/medical.md) —
  IEC 62304-aligned infusion-pump verification.
- [`api_reference/backends.md#leanbackend`](api_reference/backends.md)
  — Lean backend module reference.
- `monogate-lean/MonogateEML/Tactics.lean` — the `eml_auto` rule
  set and existing EML lemmas.
- `software/verification/lean/LeanBackend.py` — backend source.
