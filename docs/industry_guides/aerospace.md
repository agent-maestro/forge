# Aerospace — flight control + avionics

> Forge Pro vertical. DO-178C-aligned kernels for inner-loop
> attitude control, autothrottle, INS, navigation, and weapon
> engagement. Every kernel is profiled, FPGA-allocated, and
> ships with a Lean 4 proof artifact.

---

## What aerospace needs from a compiler

Flight-critical loops live or die on three things: numerical
stability, certifiability, and cross-target equivalence. Forge
delivers all three from a single source:

- **Stability** — the Pfaffian profiler tags every function with
  a chain order; the type checker enforces a `where chain_order
  <= N` clause that fails the build if your math drifts. No need
  to wait for SIL testing to learn that a refactor broke fp16
  robustness.
- **Certifiability** — `@verify(lean, theorem=...)` blocks emit
  Lean 4 theorem statements with `eml_auto`-attempted proofs.
  The same `requires` / `ensures` clauses become DO-178C
  objective evidence.
- **Equivalence** — patent #22's `cross_target_check` runs the
  same vectors through Python, C, Rust, and Lean and asserts
  agreement to 1e-12. The Verilog backend's CORDIC cores are
  bit-equivalent within 3 LSBs of Q16.16.

---

## What ships in the Pro tier

The aerospace pack covers the textbook flight-control surface
plus the navigation primitives that wrap around it. Typical
chain orders run 0–2 (PID inner loops are chain 0; gravity /
trig compensation lifts to chain 2). Every kernel ships with:

- A `@verify(lean)` contract proving actuator-saturation safety
  or input-domain monotonicity.
- An `@target(fpga, ...)` profile sized for hobby (Artix-7) and
  production (Kintex/Versal) devices.
- A C / Rust / Verilog / VHDL / Chisel quad emitted by
  `eml-compile --target all`, plus the matching Lean 4 theorem
  artifact.
- A DO-178C cert template that wires the theorem evidence into
  the regulator's expected document layout.

Coverage areas include:

- Inner-loop attitude control (pitch, roll, yaw rate)
- Autothrottle and engine-thrust scheduling
- Inertial navigation step + alignment
- Air-data sensors (pitot airspeed, baro altitude)
- Navigation primitives (great-circle bearing, Mercator)
- Guidance + targeting (proportional navigation, terminal homing)

---

## Working with the kernels

Open a kernel from the Pro pack and the LSP shows you, in real
time:

- Chain order on hover for every function
- FPGA cost estimate (LUT / DSP / cycles) in the status bar
- Lean theorem name + proof status above each `@verify` block
- Cross-target equivalence pass/fail in the bottom panel after
  every save

Compile any kernel to all 32 backends in one command:

```
eml-compile <kernel>.eml --target all -o build/
```

The C, Rust, Verilog, and Lean artifacts land side by side. The
Lean theorem builds in seconds; the Verilog drops into Vivado
and synthesizes to within ±5% of the allocator's estimate.

---

## Get access

The aerospace kernel pack ships with **Forge Pro**. Visit
<https://monogateforge.com/get-started> for the full library.

Free tier covers the compiler, the LSP, the cost analyzer, and
12 software backends — more than enough to write your own
aerospace `.eml` from scratch and compile it to C, Rust, Python,
Lean, and the rest. The pre-verified library is the moat.
