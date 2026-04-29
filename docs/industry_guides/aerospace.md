# Aerospace — flight control + avionics

> The shipping example: an autopilot loop in 30 lines of
> EML-lang that compiles to C, Rust, Lean, and Verilog
> from one source.

---

## Why aerospace lives in EML-lang

Flight-critical loops live or die on three things: numerical
stability, certifiability, and cross-target equivalence. Forge
gives you all three from a single source:

- **Stability** — the Pfaffian profiler tags every function
  with a chain order; the type checker enforces a `where
  chain_order <= N` clause that fails the build if your math
  drifts. No need to wait for SIL testing to learn that a
  refactor broke fp16 robustness.
- **Certifiability** — `@verify(lean, theorem=...)` blocks
  emit Lean 4 theorem statements with `eml_auto`-attempted
  proofs. The same `requires` / `ensures` clauses become
  DO-178C objective evidence.
- **Equivalence** — Patent #22's `cross_target_check` runs
  the same vectors through Python, C, Rust, and Lean and
  asserts agreement to 1e-12. The Verilog backend's CORDIC
  cores are bit-equivalent within 3 LSBs of Q16.16.

---

## Shipping vertical

`industries/aerospace/flight_control/autopilot.eml` is the
canonical demo. The full surface:

- One `@target(fpga, clock_mhz=100, precision=float32)`
  function — the autopilot inner loop.
- One `@verify(lean, theorem="autopilot_command_within_limits")`
  block — proves the output respects the actuator limits.
- Imports `stdlib::control::pid` for the PID core; the
  outer wrapper handles antiwindup + slew limiting.
- Compiles to all four primary targets in one shot.

```bash
eml-compile industries/aerospace/flight_control/autopilot.eml \
    --target all -o build/aerospace/
```

Produces `autopilot.c`, `autopilot.rs`, `autopilot.lean`, and
`autopilot.v` in the output directory.

---

## Recommended `where` clauses

For typical 3-axis flight control, the inner loop should
satisfy:

```eml
fn pitch_step(...) -> Real
  where chain_order <= 1,
        domain: pitch_setpoint  > -1.5708 && pitch_setpoint  < 1.5708,
        domain: pitch_measured  > -1.5708 && pitch_measured  < 1.5708,
        precision: 1e-6
{
    // body
}
```

`chain_order <= 1` keeps the function inside the SuperBEST
"safe" band — multiplications and additions of bounded
trigonometric outputs. The domain clauses give the type
checker enough information to prove the `tan` / `asin` calls
stay away from their poles.

---

## FPGA target choice

For DO-178C-aligned flight control, the canonical target is
`xilinx.artix7` — Vivado's flow is what most certification
authorities are familiar with. The allocator takes the
`@target(fpga, clock_mhz=100, ...)` annotation and budgets:

- ~500 LUTs per autopilot loop (PID + slew + saturation).
- 4–8 DSPs per axis depending on attitude representation
  (Euler vs quaternion).
- 0 BRAM — the whole loop is combinational + a single
  registered output.

```bash
eml-compile autopilot.eml --allocate --fpga-target xilinx.artix7
```

prints the per-unit decision and the LUT/DSP budget.

---

## What to look at next

- [`../architecture/profiler.md`](../architecture/profiler.md) —
  how the chain-order tag is computed.
- [`../api_reference/cli.md`](../api_reference/cli.md) — full
  CLI reference for the `--allocate`, `--explain`, and
  `--target all` flags shown above.
- `industries/defense/navigation/ins.eml` — inertial
  navigation example using `stdlib::linalg` + `stdlib::signal`.
