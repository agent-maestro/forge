# Automotive — powertrain + ADAS

> Forge Pro vertical. ISO 26262 ASIL-D-aligned kernels for
> field-oriented motor control, battery management, ABS / ESC,
> ACC, AEB, and the rest of the safety-critical drive stack.

---

## What automotive needs from a compiler

Modern vehicles run hundreds of small math kernels at
millisecond cadence: motor commutation, brake-by-wire, traction
limits, regen-braking maps, sensor fusion. Each one needs
bounded outputs, deterministic timing, and a paper trail when
the regulator asks. Forge delivers:

- **ASIL-D-grade contracts** — `requires` / `ensures` clauses
  become Lean theorem evidence the certifier can machine-check.
- **Powertrain-aware FPGA profile** — the allocator knows what
  Park-Clarke + PI looks like in DSP slices and produces a
  cycle-exact estimate per ECU clock domain.
- **Cross-target equivalence** — emit C for an MCU AUTOSAR
  partition, Verilog for the FOC FPGA accelerator, and Lean for
  the safety-case file, all from the same source. Patent #22's
  equivalence harness asserts agreement to 1e-12.

---

## What ships in the Pro tier

The automotive pack covers the math that runs at millisecond
cadence on every modern vehicle. Typical chain orders run 0–2
(controllers are chain 0; trig-laden transforms like Park /
Clarke lift to chain 1–2). Every kernel ships with:

- A `@verify(lean)` contract proving torque / current / brake
  bounds.
- An `@target(fpga, ...)` profile sized for typical automotive
  ECUs.
- The full backend matrix (C, Rust, Verilog, VHDL, Chisel, AUTOSAR
  C, Lean), plus an ISO 26262 cert template.

Coverage areas include:

- Field-oriented motor control (Park-Clarke, inverse, PI inner
  loop, SVPWM)
- Battery state-of-charge + state-of-health estimators
- ABS / ESC slip controllers + torque vectoring
- ADAS: ACC, AEB, lane keeping (steering polynomial fits)
- Energy management (regen / friction split, brake blending)

---

## Working with the kernels

Open a kernel and the LSP surfaces:

- Chain order + cost class above every fn header
- FPGA + DSP estimate in the status bar
- Lean proof status next to `@verify` annotations
- AUTOSAR `arxml` skeleton in the right pane (Pro feature)

Compile any kernel to every backend in one command:

```
eml-compile <kernel>.eml --target all -o build/
```

The AUTOSAR C lands ready for ECU integration; the Verilog
drops into the FOC accelerator's RTL slot.

---

## Get access

The automotive kernel pack ships with **Forge Pro**. Visit
<https://monogateforge.com/get-started> for the full library.

Free tier covers the compiler and 12 software backends — write
your own automotive `.eml` from scratch and compile to C / Rust
/ Lean today. The pre-verified safety-critical library is the
proprietary product.
