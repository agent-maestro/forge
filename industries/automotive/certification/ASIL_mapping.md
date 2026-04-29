# ASIL ↔ Chain Order Mapping

> Practical rule-of-thumb for choosing the `where chain_order <= N`
> bound on safety-critical functions, indexed by ASIL.
>
> The mapping is a defensible default, not a regulatory rule.
> It's grounded in the E-193 numerical-stability data
> (`monogate-research/exploration/E193_numerical_stability/`)
> which empirically links chain order to fp16/fp32 drift rates.
> Higher chain order → more drift → more risk per ISO 26262 §6.

---

## The mapping

| ASIL | Recommended `where chain_order <= N` | Rationale |
|------|--------------------------------------|-----------|
| QM   | no constraint                        | No safety effect; performance trumps stability |
| A    | `<= 4`                               | Light injury; transcendental nesting allowed but loud-warns at fp16 |
| B    | `<= 3`                               | Moderate injury; one transcendental layer + arithmetic |
| C    | `<= 2`                               | Severe injury; trig OR exp/log permitted, no nesting |
| D    | `<= 1`                               | Catastrophic; pure polynomial + at most one exp/log layer |

**`<= 0`** (pure polynomial) is the safest setting; if your
control law fits at chain order 0, you've ruled out an entire
category of numerical-stability hazards by construction.

---

## Why this mapping?

Three independent reasons all point in the same direction:

1. **Numerical stability** (E-193). At fp16, observed worst-case
   relative error rises ~0.34 digits per chain-order unit. The
   `chain_order <= 2` bound at ASIL-C corresponds to ~0.7 digits
   of fp16 drift — well within the 4-digit safety margin most
   automotive control loops carry.

2. **Verification difficulty.** Lean proofs of `requires →
   ensures` get linearly harder per chain-order layer. ASIL-D
   programs are simple enough that `eml_auto` typically closes
   the proof; ASIL-A programs may need manual proof finishing.

3. **FPGA resource cost** (Patent #14). Chain order 0 needs only
   MAC units; chain 1 adds an exp/ln; chain 2 adds a trig; chain
   ≥ 3 forces fp64. Tight ASIL-D programs literally use less
   silicon, so they're cheaper to ship in safety-critical ECUs
   that can't afford the larger inverter-side FPGA.

---

## Worked examples

| Function | Chain order | Recommended ASIL |
|----------|-------------|------------------|
| Pure PID (Kp\*err + Ki\*int + Kd\*deriv) | 0 | up to ASIL-D |
| Linear field-oriented control (Park transform skipped) | 0 | up to ASIL-D |
| Park transform (sin + cos) | 2 | ASIL-C |
| FOC with gravity feed-forward (cos in compensation) | 2 | ASIL-C |
| Sigmoid throttle map (1/(1+exp(-x))) | 1 | ASIL-D |
| Damped oscillator detector (exp \* cos) | 3 | ASIL-B |
| Tan-based steering geometry (atan in trajectory plan) | 2 | ASIL-C |
| Bessel-FM acoustic alarm synthesis | 4 | ASIL-A or QM |

For an EV powertrain stack, you typically end up with:
ASIL-D for the PI current loops (chain 0); ASIL-C for the FOC
Park/Clarke pipeline (chain 2 due to the rotor-angle trig); ASIL-A
or QM for the diagnostic / telemetry paths (no safety claim).

---

## How to enforce in CI

Add a single line to `tests/industry/test_<vertical>.py`:

```python
def test_powertrain_meets_asil_c():
    mod = parse_file("powertrain/foc_d_axis.eml")
    Profiler().profile_module(mod)
    safety_critical_fns = [
        f for f in mod.functions
        if any(a.kind == "verify" for a in f.annotations)
    ]
    for fn in safety_critical_fns:
        assert fn.profile["chain_order"] <= 2, (
            f"{fn.name}: chain_order {fn.profile['chain_order']} "
            f"exceeds ASIL-C bound (2)"
        )
```

The CI test fails before merge if anyone introduces a
chain-order regression. Cheap insurance against accidentally
shipping a fp16-unstable control law.
