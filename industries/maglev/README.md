# maglev

> Industry vertical scaffold. Single-coil magnetic levitation
> stack — physics, controller, and sensor in three files.

**Certification target:** none yet (hobby-scale plant). The
controller's bounded-output proof is the path to IEC 61508 SIL-2
once the gain-tuning study is done.
**Typical chain orders:** 0 (rational physics + PID) and 1 (the
filtered sensor path). No transcendentals on the hot loop.

## Files

| file              | role                                          |
|-------------------|-----------------------------------------------|
| `levitation.eml`  | F = k I² / z² lift model + envelope invariant |
| `controller.eml`  | PID gap controller with anti-windup           |
| `sensor.eml`      | Hall-voltage → gap conversion + biquad filter |

## Block diagram

```
   gap_target ──┐
                ▼
              ┌───┐                ┌──────────┐
              │ - │ ── error ────> │ controller│
              └───┘                │  (PID)   │
                ▲                  └────┬─────┘
                │                       │
         gap_measured                   │ command (current)
                │                       │
                │                       ▼
              ┌────┐                ┌────────────┐
              │ Hall│ <── V_H ─────│ levitation │
              │  +  │              │ (plant)    │
              │filter│             └────────────┘
              └─────┘                    ▲
                                         │
                                       gravity
```

## @verify obligations

| theorem (Lean)                          | claim                              |
|-----------------------------------------|------------------------------------|
| `magnetic_lift_force_nonnegative`       | F(I, z) ≥ 0 in the operating band  |
| `levitation_envelope_lifts_with_margin` | F(I_min, z_max) > 1.10 · m·g       |
| `maglev_command_within_coil_limits`     | 0 ≤ pid_command ≤ I_MAX            |
| `maglev_integrator_bounded`             | \|integral\| ≤ I_LIMIT             |
| `hall_to_gap_monotone`                  | z(V_H) ↘ in V_H over the band      |
| `filtered_gap_within_envelope`          | filtered z ∈ [Z_MIN, Z_MAX]        |

## Running

```bash
# format-check the whole vertical
python tools/cli/main.py industries/maglev/levitation.eml --target python
python tools/cli/main.py industries/maglev/controller.eml --target python
python tools/cli/main.py industries/maglev/sensor.eml     --target python

# compile to every backend (Free + Pro tier you hold a license for)
python tools/cli/main.py industries/maglev/levitation.eml --target all
```

## Hardware notes

The reference plant is hobby-scale: a 1 g target object on a
small solenoid driven from a 12 V supply. Coil current is sensed
by a series shunt, gap is sensed by a single Hall-effect sensor
mounted on the pole face. The PID gains in `controller.eml` are
tuned for this plant; retune for your hardware before flying.

## Sibling verticals

`manufacturing/process_control/plc_setpoint.eml` shares the same
PID-anti-windup primitive but targets PLC-rate (20 Hz) actuator
clamping. The maglev controller runs three orders of magnitude
faster and tracks an open-loop unstable plant.
