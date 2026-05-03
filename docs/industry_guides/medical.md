# Medical devices — IEC 62304 paths

> Forge Pro vertical. IEC 62304 software safety class C and
> FDA 510(k) Class II / III aligned kernels for drug infusion,
> closed-loop physiologic control, defibrillator energy delivery,
> and pharmacokinetic modelling.

---

## What medical needs from a compiler

A drug-delivery rate, a defibrillator joule, a ventilator's
pressure target — every one of these is a math kernel running
inside a regulated device. The kernel has to provably stay
inside its safe envelope, the device file has to show why, and
the compile artifact has to come from a documented build chain.
Forge delivers:

- **Bounded-output contracts** — `requires` / `ensures` clauses
  become Lean theorems proving the kernel never escapes its
  patient-safe range.
- **Predictable runtime** — chain orders are fixed at compile
  time; no allocator surprises on the device.
- **Audit-ready outputs** — C for the device firmware, Lean for
  the safety case, equivalence harness output for the V&V binder.

---

## What ships in the Pro tier

The medical pack covers the math that touches a patient. Typical
chain orders run 0–1 (most controllers are chain 0; PK / drug
absorption models lift to chain 1). Every kernel ships with:

- A `@verify(lean)` contract proving the output stays inside the
  device-safe range under all input combinations.
- An `@target(fpga, ...)` profile for hardware-accelerated
  kernels (defibrillator pulse shaping, ECG threshold detection).
- The full backend matrix (C, Rust, Lean), plus an IEC 62304
  cert template wired to the V&V evidence layout.

Coverage areas include:

- IV infusion-pump rate controller + air-in-line guards
- Defibrillator biphasic energy + dose calculation
- One- and two-compartment pharmacokinetic models
- Closed-loop physiologic control (insulin pump, ventilator)
- Dose-response curves + drug clearance

---

## Working with the kernels

Open a kernel and the LSP surfaces:

- Chain order + cost class above every fn header
- Lean proof status next to every `@verify` annotation
- IEC 62304 risk class on the kernel header (Pro feature)
- V&V evidence trail in the right pane (Pro feature)

Compile any kernel to every backend in one command:

```
eml-compile <kernel>.eml --target all -o build/
```

The C lands ready for embedding in firmware; the Lean theorem
goes straight into the safety-case binder.

---

## Get access

The medical kernel pack ships with **Forge Pro**. Visit
<https://monogateforge.com/get-started> for the full library.

Free tier covers the compiler and 12 software backends — write
your own medical `.eml` from scratch and compile to C / Rust
/ Lean today. The pre-verified life-supporting library is the
proprietary product.
