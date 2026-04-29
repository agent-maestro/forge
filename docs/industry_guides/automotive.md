# Automotive — powertrain + ADAS

> Field-oriented motor control compiled bit-equivalent to
> AUTOSAR-style C, FPGA, and Rust from a single source.

---

## Why automotive lives in EML-lang

Powertrain control is a hot loop running at tens of kHz on a
mixed CPU + FPGA topology. The two halves of the loop need to
agree exactly — a bit-different output between the soft loop
and the hard loop is a debugging nightmare.

Forge guarantees that agreement structurally: the same
`.eml` source produces the C running on the MCU and the
Verilog running on the FPGA, with cross-target equivalence
proven by `cross_target_check()` on every PR.

---

## Shipping verticals

| File                                                            | What it does |
|-----------------------------------------------------------------|--------------|
| `industries/automotive/powertrain/motor_foc.eml`                | FOC inner loop (Park + Clarke + PI) |
| `industries/automotive/powertrain/three_phase.eml`              | Park / inverse-Park + Clarke / inverse-Clarke transforms |

`motor_foc.eml` imports `stdlib::control::pid` for the PI
core and `local::three_phase` for the transforms. Total
LOC: ~50.

```bash
eml-compile industries/automotive/powertrain/motor_foc.eml \
    --target all -o build/automotive/
```

Produces `motor_foc.c`, `motor_foc.rs`, `motor_foc.lean` (if
the source has a `@verify` block), and `motor_foc.v`.

---

## Recommended `where` clauses

The Park transform's outputs depend on a `theta` angle; the
inverse Park transform's outputs are bounded by the input
amplitude. For a stator-frame voltage cap:

```eml
fn apply_inverse_park(v_d: Real, v_q: Real, theta: Real)
    -> (Real, Real, Real)
  where chain_order <= 1,
        domain: v_d * v_d + v_q * v_q < 200.0
{
    // body
}
```

The `chain_order <= 1` clause keeps the function inside the
fp32 safe band; the amplitude domain prevents the inverse
Clarke from saturating the SVPWM modulator downstream.

---

## FPGA target choice

For automotive functional-safety ASIL-D loops, the canonical
target today is `xilinx.artix7` (matches the Aurix +
Zynq-7000 flow common in the industry). For lower-cost
variants, `lattice.ecp5` fits a single-axis FOC loop in <30%
of the device.

The allocator's per-unit decision for FOC is typically:

- 6–10 MACs per axis (one per Clarke matrix entry +
  the PI term).
- 2 sin + 2 cos units (shared, since both Park and
  inverse-Park need the same angle pair).
- 0 BRAM.

---

## Common gotchas

- **Per-axis chain-order budget** — running the integrator
  on the rotor frame instead of the stator frame keeps the
  chain order at 1 and avoids the fp16 drift that shows up
  in stator-frame implementations.
- **Antiwindup** — use
  `stdlib::control::pid_anti_windup` rather than rolling your
  own; the canonical form has a cost class the optimizer
  recognizes and the `--explain` report flags drift if you
  inadvertently use the unsafe variant.
- **SuperBEST routing** — `sigmoid_alt` style parameterizations
  trigger the SuperBEST pass automatically; the rewrite saves
  a measurable amount of fp32 precision in the gain
  scheduler.
