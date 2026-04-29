# Medical devices — IEC 62304 paths

> Drug infusion + closed-loop physiologic control with
> Lean-verified safety properties.

---

## Why medical lives in EML-lang

IEC 62304 Class C devices (life-supporting / life-sustaining)
require formal evidence that the control loop respects safety
properties even under input fault. Forge's `@verify(lean, ...)`
blocks emit Lean 4 theorems with `eml_auto`-attempted proofs;
the resulting artifacts are accepted as objective evidence in
the verification phase of the lifecycle.

Pair that with the cross-target equivalence guarantee
(Patent #22) and you have a single source that produces the
device firmware, the test harness, and the safety proof, all
guaranteed identical.

---

## Shipping vertical

`industries/medical/devices/infusion_pump.eml` is the
canonical demo. Imports `stdlib::control::pid` + the
saturation primitives.

The function carries:

- `@target(c, rust)` — the pump runs an MCU, no FPGA needed.
- `@verify(lean, theorem="dose_within_envelope")` — proves
  the commanded dose stays inside the prescribed window
  regardless of sensor input.

```bash
eml-compile industries/medical/devices/infusion_pump.eml \
    --target all -o build/medical/
```

Produces `infusion_pump.c`, `infusion_pump.rs`, and
`infusion_pump.lean`. The Lean output drops into the existing
`monogate-lean` Lake project and can be checked offline as
part of the regulatory submission.

---

## Recommended `where` clauses

For dose control with a hard-stop ceiling:

```eml
fn dose_step(setpoint: Real, measured: Real, integral: Real) -> Real
  where chain_order <= 1,
        domain: setpoint  > 0.0 && setpoint  < MAX_DOSE,
        domain: measured  > 0.0 && measured  < 2.0 * MAX_DOSE,
        precision: 1e-6
{
    saturate(pid(setpoint, measured, integral), 0.0, MAX_DOSE)
}
```

The `domain` constraint plus the `saturate` call gives the
Lean prover enough structure to close
`dose_within_envelope` with `eml_auto` alone — no manual
`sorry`-removal needed.

---

## Equivalence guarantee

Run

```bash
python -m pytest tests/equivalence/test_industry_verticals.py -k medical
```

to verify that the Python reference, the C output, the Rust
output, and (when `lean` is on PATH) the Lean output all
agree on a curated input vector grid covering both the
nominal and the fault cases.

---

## What to look at next

- [`../architecture/profiler.md`](../architecture/profiler.md) —
  what makes the chain-order tag suitable for verification
  evidence.
- `software/verification/lean/LeanBackend.py` — how `@verify`
  blocks become Lean 4 source.
- `lang/spec/stdlib/control.eml` — full list of saturation,
  dead-zone, and rate-limit primitives the verification path
  recognizes.
