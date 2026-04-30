# Industry verticals — production-shape EML examples

Fifteen verticals across seven domains. Each `<vertical>/<subdomain>/`
directory ships a working `.eml` source and a `build/` subdirectory
containing **pre-generated artifacts** for every backend that
applies — so you can read the C, Rust, Python, LLVM IR, WebAssembly
IR, Verilog, VHDL, Chisel, and Lean output of a real industry
example without installing the toolchain.

---

## What's here

| Domain          | File                                                              | Demonstrates |
|-----------------|-------------------------------------------------------------------|--------------|
| Aerospace       | `aerospace/flight_control/autopilot.eml`                          | DO-178C-style elevator-command pipeline with `@verify(lean)` |
| Audio (DSP)     | `audio/dsp/biquad_lowpass.eml`                                    | Direct-Form-I biquad filter |
| Audio (synth)   | `audio/synthesis/additive_voice.eml`                              | **Patent #14** — 4-sin shared / 1-exp dedicated FPGA allocation |
| Automotive      | `automotive/powertrain/motor_foc.eml` + `three_phase.eml`         | Field-oriented control + Park/Clarke transforms |
| Defense         | `defense/navigation/ins.eml`                                      | Inertial navigation step |
| Energy          | `energy/renewable/mppt.eml`                                       | Maximum-power-point tracking |
| Finance         | `finance/pricing/black_scholes.eml` + `heston.eml` + `sabr.eml`   | SR 11-7 / FRTB — Black-Scholes call/put + Heston + SABR |
| Finance (Greeks)| `finance/greeks/{delta,gamma,vega,theta}.eml`                     | First-order option sensitivities + put-call parity |
| Finance (Risk)  | `finance/risk/{var_monte_carlo,cva,stress_test}.eml`              | Parametric VaR cell, CVA bucket, FRTB curvature shocks |
| Manufacturing   | `manufacturing/process_control/plc_setpoint.eml`                  | Setpoint controller with anti-windup |
| Medical         | `medical/devices/infusion_pump.eml`                               | IEC 62304-aligned dose envelope (Lean-verified) |
| ML inference    | `ml/inference/binary_classifier.eml`                              | **Patent #01** — `sigmoid_alt` rewrites to canonical form, +1.08 digits |
| Radar           | `radar/cfar_threshold.eml`                                        | Stub — single-cell CA-CFAR detection threshold |
| Robotics        | `robotics/kinematics/arm_6dof.eml`                                | 6-DOF forward kinematics |
| Scientific      | `scientific/physics/schrodinger_step.eml`                         | Single time-step of the time-evolution operator |
| Semiconductor   | `semiconductor/shockley_diode.eml`                                | Stub — ideal-diode I-V curve for SPICE-class device models |
| Telecom         | `telecom/pulse_compression.eml`                                   | Stub — single-tap chirped matched filter |

---

## What's in `build/`

Each vertical's `build/` directory contains the output of running:

```bash
eml-compile <vertical>.eml --target all
```

For a vertical with a `@target(fpga)` annotation, you get **9
artifacts**:

```
autopilot.c          # C99 (libmonogate.h)
autopilot.rs         # Rust (monogate-sys crate)
autopilot.py         # Python (math.* only)
autopilot.ll         # LLVM IR
autopilot.wasm.ll    # LLVM IR with wasm32 triple (or .wasm bytecode if llc/clang on PATH)
autopilot.v          # Synthesizable Verilog
autopilot.vhd        # VHDL-2008
Autopilot.scala      # Chisel 3 / FIRRTL
autopilot.lean       # Lean 4 theorem (when @verify(lean) is present)
```

For a non-FPGA module (e.g. `three_phase.eml`, a sibling helper),
you get the 5 software backends plus Lean — the 3 HDL backends
skip cleanly.

---

## Why pre-generated artifacts ship in the tree

Three reasons:

1. **Cold-read clarity.** A reader skimming the repo can see what
   the compiler produces without running it. The `.c` and the `.v`
   tell the same story in two languages — that's the cross-target
   equivalence (Patent #22) made physically inspectable.
2. **Diff-able truth.** When the compiler changes, the diff to
   these files surfaces in PR review. If a refactor accidentally
   changes the emitted Verilog, the change is visible.
3. **Investor / regulator audit.** The DO-178C, IEC 62304, ISO
   26262 cert paths rely on the generated `.lean` being a stable
   artifact. Committing it makes the evidence chain
   reproducible.

---

## Regenerating

```bash
# One vertical
python tools/cli/main.py industries/aerospace/flight_control/autopilot.eml \
    --target all -o industries/aerospace/flight_control/build/

# Every vertical (CI uses this)
for f in industries/**/*.eml; do
    dir=$(dirname "$f")
    python tools/cli/main.py "$f" --target all -o "$dir/build/"
done
```

When the parser, profiler, optimizer, or any backend changes, run
the bulk regeneration and commit the diff. CI verifies the
artifacts match what the current compiler would emit, so the
evidence chain stays honest.

---

## See also

- [`../docs/getting_started.md`](../docs/getting_started.md) —
  10-minute end-to-end tour.
- [`../docs/industry_guides/`](../docs/industry_guides/) —
  per-domain narrative + `where`-clause patterns.
- [`../docs/hardware_targets.md`](../docs/hardware_targets.md) —
  picking an FPGA target, allocator output, Verilator simulation.
- [`../docs/verification_guide.md`](../docs/verification_guide.md)
  — `@verify(lean)` end-to-end + DO-178C / IEC 62304 evidence.
