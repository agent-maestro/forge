# geospatial — Geospatial / Navigation vertical

> Industry vertical scaffold. GPS receivers, map projections,
> coordinate transforms, satellite-orbit propagators, and
> terrain interpolators all run trig + log on FPGAs and ASICs
> at receiver scale. Forge compiles the same `.eml` source to
> verified C, Rust, Verilog, VHDL, Chisel, LLVM, and a paired
> Lean theorem.

**Certification target:** DO-178C (airborne navigation), MIL-STD-882E
(safety; defence + missile-guidance systems), ICAO Annex 11
(air-traffic services).

**Typical chain orders:**

  - GPS signal processing (code correlation): chain 0–1
  - Map projection (Mercator = ln(tan(...))): chain 3
  - Coordinate transforms (ECEF↔LLA, trig-heavy): chain 2
  - Terrain modelling (interpolation + trig): chain 2
  - Satellite-orbit prediction (Kepler iteration): chain 1–2

## Why geospatial belongs in EML-lang

Two payoff cases drive the vertical:

  1. **Receiver silicon.** Every cellphone, automotive
     navigation chip, and IoT-tracker SoC ships a GNSS receiver
     that runs the same trig kernels on dedicated hardware.
     Forge's pitch: emit those kernels from a verified spec
     instead of hand-written Verilog.

  2. **Mission-critical guidance.** When a missile uses a
     coordinate transform, its precision matters. Today the
     transforms ship as MATLAB / C reference + an opaque HDL
     translation. Forge collapses both into one source with a
     Lean theorem attached.

## Status

Stub. The `mercator_projection.eml` example below is illustrative;
the full vertical (ECEF↔LLA pipeline, GPS L1 C/A correlator,
Kalman INS+GNSS fuser) is on the roadmap.

## Scaffold

```
industries/geospatial/
  README.md
  mercator_projection.eml      ← illustrative single-point projection
  certification/                ← (planned) DO-178C, MIL-STD-882E
  receivers/                    ← (planned) GPS L1 C/A, GLONASS, Galileo
  transforms/                   ← (planned) ECEF↔LLA, Helmert, datum shifts
  fusion/                       ← (planned) Kalman INS+GNSS
```

## Cross-references

- The defense vertical's `defense/navigation/ins.eml` is the
  inertial half of the fusion story; the geospatial vertical
  ships the GNSS half once that lands.
- The aerospace vertical's autopilot consumes the same coordinate
  frames; sharing primitives across both eliminates desk-vs-cert
  drift.
