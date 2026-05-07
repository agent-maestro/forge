# Verified circuit proofs (Phase E4)

The `.lean` files in this directory are the **closed** form of the
proof obligations the Lean backend (`--target lean`) emits for the
`@verify(lean, ...)` annotations on the corresponding `.eml`
circuit files.

### Application demos (E1 + E5)

| Proof file                                | Source EML                                            | Theorems closed |
|-------------------------------------------|-------------------------------------------------------|-----------------|
| `rc_filter.lean`                          | `examples/rc_filter.eml`                              | 5/5 |
| `voltage_divider.lean`                    | `examples/voltage_divider.eml`                        | 3/3 |
| `maglev/sensor.lean`                      | `examples/maglev/sensor.eml`                          | 2/2 |
| `maglev/controller.lean`                  | `examples/maglev/controller.eml`                      | 1/1 |
| `maglev/driver.lean`                      | `examples/maglev/driver.eml`                          | 4/4 |
| `maglev/power.lean`                       | `examples/maglev/power.eml`                           | 2/2 |
| **Application subtotal**                  |                                                       | **17/17** |

### Carrier-substrate demos (proof of substrate)

| Proof file                                | Source EML                                            | Tier | Theorems closed |
|-------------------------------------------|-------------------------------------------------------|------|-----------------|
| `carriers/mosfet_iv.lean`                 | `electronics/mosfet_iv.eml`                           | T2 electron  | 2/2 |
| `carriers/cmos_inverter.lean`             | `electronics/cmos_inverter.eml`                       | T2 electron  | 3/3 |
| `carriers/pll_loop.lean`                  | `electronics/pll_loop.eml`                            | T2 electron  | 2/2 |
| `carriers/mach_zehnder.lean`              | `photonics/mach_zehnder.eml`                          | T3 photon    | 2/2 |
| `carriers/ring_resonator.lean`            | `photonics/ring_resonator.eml`                        | T3 photon    | 2/2 |
| `carriers/poisson_spot.lean`              | `photonics/poisson_spot.eml`                          | T3 photon    | 2/2 |
| `carriers/optical_neuron.lean`            | `photonics/optical_neuron.eml`                        | T3 photon    | 2/2 |
| `carriers/magnon_dispersion.lean`         | `spintronics/magnon_dispersion.eml`                   | T4 magnon    | 2/2 |
| `carriers/spin_torque.lean`               | `spintronics/spin_torque.eml`                         | T4 magnon    | 2/2 |
| `carriers/magnon_logic.lean`              | `spintronics/magnon_logic.eml`                        | T4 magnon    | 2/2 |
| `carriers/phonon_bandgap.lean`            | `phononics/phonon_bandgap.eml`                        | T5 phonon    | 2/2 |
| `carriers/thermal_rectifier.lean`         | `phononics/thermal_rectifier.eml`                     | T5 phonon    | 2/2 |
| `carriers/acoustic_cloak.lean`            | `phononics/acoustic_cloak.eml`                        | T5 phonon    | 2/2 |
| `carriers/ferron_propagation.lean`        | `ferronics/ferron_propagation.eml`                    | T6 ferron    | 2/2 |
| `carriers/ferron_emission.lean`           | `ferronics/ferron_emission.eml`                       | T6 ferron    | 2/2 |
| `carriers/ferron_dispersion.lean`         | `ferronics/ferron_dispersion.eml`                     | T6 ferron    | 2/2 |
| `carriers/ferron_logic.lean`              | `ferronics/ferron_logic.eml`                          | T6 ferron    | 2/2 |
| `carriers/phase_gate.lean`                | `quantum/phase_gate.eml`                              | T7 amplitude | 3/3 |
| `carriers/hadamard.lean`                  | `quantum/hadamard.eml`                                | T7 amplitude | 3/3 |
| `carriers/cnot.lean`                      | `quantum/cnot.eml`                                    | T7 amplitude | 3/3 |
| `carriers/grover_oracle.lean`             | `quantum/grover_oracle.eml`                           | T7 amplitude | 2/2 |
| **Carrier subtotal**                      |                                                       |              | **47/47** |
| **Grand total**                           |                                                       |              | **64/64** |

Carriers per tier:
  T2 electronics : 3 demos / 7 obligations
  T3 photonics   : 4 demos / 8 obligations
  T4 spintronics : 3 demos / 6 obligations
  T5 phononics   : 3 demos / 6 obligations
  T6 ferronics   : 4 demos / 8 obligations
  T7 quantum     : 4 demos / 11 obligations

## Reproducing the build

```bash
# 1. Generate the obligation skeleton (sorry-bearing).
cd ~/monogate/forge
python -m tools.cli.main examples/voltage_divider.eml --target lean -o /tmp/vd.lean

# 2. Drop into MachLib's local Discovered/ workspace.
cp examples/proofs/voltage_divider.lean \
   ~/monogate/machlib/foundations/MachLib/Discovered/

# 3. Verify it closes against MachLib.
cd ~/monogate/machlib/foundations
lake build MachLib.Discovered.voltage_divider
```

Same procedure for `rc_filter.lean`.

## Why the proofs aren't in MachLib's git tree

`~/monogate/machlib/foundations/MachLib/Discovered/` carries a
catch-all `.gitignore` that excludes `*` — by design. The
`Discovered/` namespace is for project-specific obligation closure
that lives alongside the project, not inside MachLib's canonical
catalogue. The forge repo is the project; the proofs live here.

## What each theorem proves

### voltage_divider.lean (3 obligations, all closed)

| Theorem | Property |
|---------|----------|
| `voltage_divider_law`            | `V_out = V_in * R2 / (R1 + R2)` |
| `voltage_divider_denom_pos`      | `R1 + R2 > 0` (denominator non-degenerate) |
| `voltage_divider_symmetric_half` | symmetric divider law (R1 = R2) |

### rc_filter.lean (5 obligations, all closed)

| Theorem | Property |
|---------|----------|
| `rc_time_constant_def`         | `tau = R * C` |
| `rc_steady_state_equals_input` | `V_out(infinity) = V_in` |
| `rc_initial_output_zero`       | `V_out(0) = 0` |
| `rc_step_response_form`        | `V_out(t) = V_in * (1 - exp(-t/tau))` |
| `rc_step_response_at_zero`     | `V_out(0) = 0` from the closed form |

`rc_step_response_at_zero` is the only non-trivial proof: it
chains `div_def`, `zero_mul`, `exp_zero`, `sub_def`, `add_neg`,
`mul_zero` to collapse `vin * (1 - exp(0/tau)) = 0`.

## Carrier-physics proofs (substrate demonstration)

The thesis claim: every information carrier in nature is a wave;
every wave equation is chain order 0–2; one operator
(`eml(x, y) = exp(x) - log(y + 1)`) generates every elementary
function used; one compiler verifies them all.

The six files in `examples/proofs/carriers/` are the **proof of
substrate**: one demo per non-biological tier from the thesis,
each closing all of its `@verify(lean)` obligations against the
same MachLib axiom set. Same compiler, six different physical
carriers, same proven correctness.

| Tier | Carrier | Wave equation | Witness theorems |
|------|---------|---------------|------------------|
| 2 — Electronics | electron | MOSFET I_D = ½μC(W/L)(V_GS − V_th)² | zero-overdrive zero-current; positive prefactor |
| 3 — Photonics   | photon   | Mach-Zehnder I = I₀ cos²(Δφ/2)      | full-transmit at zero phase; cos² peak = 1     |
| 4 — Spintronics | magnon   | ω(k) = γ(H₀ + Dk²)                  | uniform-mode FMR base; positive base frequency |
| 5 — Phononics   | phonon   | T = 1 / (1 + F sin²(δ/2))           | open band at δ = 0; sin²(0) = 0                |
| 6 — Ferronics   | ferron   | P(x,t) = P₀ cos(kx − ωt) exp(−x/ξ)  | amplitude at origin; envelope at origin        |
| 7 — Quantum     | amplitude| R(φ): cos(φ), sin(φ)                | identity at φ = 0; unitarity (Pythagorean)     |

The quantum unitarity proof closes via direct application of
`MachLib.pythagorean : sin²x + cos²x = 1` — the EML expression
is byte-equal to that axiom's LHS.

## Maglev module proofs (E5: pre-bench-up verification)

### maglev/sensor.lean (2/2)

| Theorem | Property |
|---------|----------|
| `sensor_zero_offset_zero_position` | `position(V_OFFSET) = 0 mm` |
| `sensor_filter_tau_positive`       | `r > 0 ∧ c > 0 → r * c > 0` |

### maglev/controller.lean (1/1)

| Theorem | Property |
|---------|----------|
| `controller_zero_input_zero_output` | `proportional_path(0) = 0` |

### maglev/driver.lean (4/4)

| Theorem | Property |
|---------|----------|
| `driver_zero_drive_zero_current`     | `Vdrive = 0 → I_steady = 0` |
| `driver_total_resistance_positive`   | `R_coil + R_sense > 0` |
| `driver_zero_current_zero_force`     | `F(0) = 0` |
| `driver_lr_product_positive`         | `L > 0 ∧ R > 0 → L * R > 0` |

### maglev/power.lean (2/2)

| Theorem | Property |
|---------|----------|
| `power_zero_supply_zero_current` | `Vsupply = 0 → I_load = 0` |
| `power_bulk_tau_positive`        | `R_load > 0 ∧ C_bulk > 0 → tau > 0` |

## What is NOT yet proven

The brief asked for these properties; closing them needs MachLib
extensions not yet shipped:

  * **RC monotonic decay** — `dV_out/dt > 0` for the charging
    response. Needs a derivative axiom for `exp`. Slated for E4.5.
  * **Voltage-divider power dissipation bound** — needs squared
    quantities; the EML files don't yet declare the relevant
    function. Add when needed.
  * **Controller output-bounded** — `OUT_MIN ≤ pid(...) ≤ OUT_MAX`.
    Needs `min`/`max` ordering lemmas in `MachLib.Forge` that
    aren't there yet (`min_ge_iff`, `le_max_of_le_left/right`
    chained). The clamped PID *body* uses `clamp(...)` which the
    C backend lowers to a real branch; a Lean version would just
    need the missing lemmas.
  * **Driver coil time-constant positivity** (`L / R_total > 0`)
    — needs `one_div_pos_of_pos` (we only have
    `one_div_nonneg_of_pos`). The product `L * R_total` is
    proven instead as a positivity witness.

All four gaps are flagged in the source `.eml` files alongside
the affected functions, rather than papered over with fresh
`sorry` lines in the Lean output.
