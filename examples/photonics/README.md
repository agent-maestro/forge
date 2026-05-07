# Verified Photonic Computing — P1: Component Library

Phase 1 of the verified-photonic-computing roadmap. Eight
fundamental photonic components, each as a single `.eml` source
that compiles to C / Python / Lean from one description, with
all `@verify(lean, ...)` obligations closed against MachLib.

## Components shipped (8 / 8)

| File                                    | Equation                                                  | Chain | Obligations |
|-----------------------------------------|-----------------------------------------------------------|-------|-------------|
| `components/waveguide.eml`              | `I(z) = I₀ exp(−2αz)`                                     | 1     | 2 |
| `components/amplifier.eml`              | `G(z) = exp(g·z)`                                         | 1     | 2 |
| `components/photodetector.eml`          | `I_ph = R · P_optical`                                    | 0     | 2 |
| `components/modulator.eml`              | `Δn = ½ n³ r_eff E`                                       | 0     | 2 |
| `components/phase_shifter.eml`          | `Δφ = 2π Δn L / λ`                                        | 0     | 2 |
| `components/directional_coupler.eml`    | `P_cross = sin²(κL); P_bar = cos²(κL)`                    | 1     | 3 |
| `components/mach_zehnder.eml`           | `I_through = I_in cos²(Δφ/2); I_drop = I_in sin²(Δφ/2)`   | 1     | 3 |
| `components/ring_resonator.eml`         | `T(δ) = 1 / (1 + F sin²(δ/2))`                            | 1     | 3 |
| **Total**                               |                                                           |       | **19** |

## Properties proven

- **Boundary conditions** — every component has at least one
  closed proof of its calibration / "off" state (waveguide
  intensity at `z = 0`, modulator `Δn` at zero applied field,
  amplifier gain at `z = 0`, MZI through at zero phase, …).
- **Energy conservation** — for two-port components that conserve
  power (directional coupler, MZI), the proof closes by direct
  application of `MachLib.pythagorean : sin²x + cos²x = 1`. The
  EML kernels are written so the body is byte-equal to the LHS
  of the axiom; the proof is one tactic.
- **Positivity invariants** — every "process parameter is positive"
  claim used by the calibration loop in P3 (loss coefficient,
  pump strength, Pockels coefficient, length, FSR, ...) is
  closed.
- **Linearity at zero** — for every linear component (photodetector,
  modulator, phase shifter), the input → output map evaluated at
  zero input returns zero output.

## Reproducibility

```bash
# Compile any component to any backend.
cd ~/monogate/forge
python -m tools.cli.main examples/photonics/components/mach_zehnder.eml \
    --target lean -o /tmp/mzi.lean

# Verify a closed proof against MachLib.
cp examples/proofs/photonics/mach_zehnder.lean \
    ~/monogate/machlib/foundations/MachLib/Discovered/photonics/
cd ~/monogate/machlib/foundations
lake build MachLib.Discovered.photonics.mach_zehnder
```

All 8 closed proofs build green via:

```bash
for f in waveguide amplifier photodetector modulator phase_shifter \
         directional_coupler mach_zehnder ring_resonator; do
  lake build MachLib.Discovered.photonics.${f}
done
```

## What this proves

> The photonic computing stack has chain-order ≤ 1 throughout.
> Every component admits a closed Lean proof of its key invariants
> against the same MachLib axiom set we use for electronic,
> magnonic, ferronic, and quantum-amplitude carriers. The
> verification fabric is substrate-independent — proofs port
> across carriers without re-derivation.

The energy-conservation proofs in `directional_coupler.lean` and
`mach_zehnder.lean` are **byte-identical**: same Pythagorean
witness expression, same `exact pythagorean theta` proof. Two
different photonic structures, one mathematical certificate.

## Next phases (not in this commit)

- **P2 — Photonic neural network.** Compose components into an
  N×N MZI mesh implementing a unitary matrix via the Reck
  decomposition. Microring weight banks for the diagonal. Full
  matrix-multiply as one optical pass.
- **P3 — Manufacturing tolerance analysis.** Per-component
  tolerance models, error propagation through the mesh, the
  closed-loop calibration controller (with convergence proof).
- **P4 — Photonic-electronic co-design.** One `.eml` file ↦ both
  the optical layout AND the electronic controller, with a Lean
  proof covering both domains.
- **P5 — Interactive demos.** `1op.io/waves/photon` — drag-the-
  phase Mach-Zehnder, drag-the-wavelength ring resonator, animate
  a photonic-attention head.
- **P6 — Verified inference.** Photonic transformer simulator
  with proof certificate per inference.

This README is updated as each phase lands.
