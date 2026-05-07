# Verified circuit proofs (Phase E4)

The `.lean` files in this directory are the **closed** form of the
proof obligations the Lean backend (`--target lean`) emits for the
`@verify(lean, ...)` annotations on the corresponding `.eml`
circuit files.

| Proof file              | Source EML                 | Theorems closed |
|-------------------------|----------------------------|-----------------|
| `rc_filter.lean`        | `examples/rc_filter.eml`        | 5/5 |
| `voltage_divider.lean`  | `examples/voltage_divider.eml`  | 3/3 |

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

## What is NOT yet proven

The user's E4 brief asked for two harder properties not closed
here:

  * **RC monotonic decay** — `dV_out/dt < 0` (or, in the charging
    convention used in the EML file, `dV_out/dt > 0`). Proving
    this in MachLib requires a derivative axiom we don't yet
    have for `exp`. Slated for E4.5.
  * **Voltage-divider power dissipation bound** — needs squared
    quantities; the EML files don't yet declare the relevant
    function. Add when needed.

Both are honest gaps — flagged here rather than papered over with
a fresh `sorry`.
