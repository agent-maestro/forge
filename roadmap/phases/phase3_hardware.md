# Phase 3 — Hardware Compiler Backend

**Duration:** ~4 sessions (months 4-6)
**Reference:** `lang/spec/EML_LANG_DESIGN.md` Phase 3 section
**Blackwell-enabled:** CUDA-accelerated Verilator simulation

**Goal:** Compile any example to synthesizable Verilog. Verilator
simulates the design. Hardware output matches the software
reference within declared tolerance.

---

## 3.1 FPGA resource allocator (1 session) — Patent #14

**Deliverable:** `hardware/allocator/allocator.py` produces a
per-unit allocation plan from the program's aggregate Pfaffian
profile + user constraints (`clock_mhz`, `precision`,
`max_luts`, `max_dsps`, `max_brams`).

- [ ] Aggregate profile across all `@target(fpga)` functions
- [ ] Count exp / ln / trig instances; pick `dedicated` vs `shared`
  strategy based on count (≤ 2 → dedicated; > 2 → time-multiplex)
- [ ] Per-function precision selection: chain ≥ 3 → f64, chain
  ≥ 1 → f32, chain 0 → f16
- [ ] Pipeline depth = max EML depth across `@target` functions
- [ ] LUT estimate vs `max_luts` budget; emit `CompileError` if over
- [ ] DSP / BRAM estimates with the same gate
- [ ] Throughput estimate: `clock_mhz / pipeline_depth Msamples/s`

## 3.2 Verilog code generator (2 sessions)

**Deliverable:** `hardware/hdl_gen/verilog_backend.py` emits
parametric Verilog modules from the AST + allocation plan.

- [ ] Top-level module per `@target(fpga)` function
- [ ] Pipeline stages: one stage per EML node
- [ ] Standard valid/ready handshake on inputs and outputs
- [ ] Transcendental units: instantiate `eml_exp`, `eml_ln`,
  `eml_sin`, `eml_cos`, `eml_sqrt` from `hardware/modules/transcendental/`
  (CORDIC variant by default; allocator can swap to polynomial / LUT)
- [ ] Generated Verilog lints clean with `verilator --lint-only`
- [ ] Generated Verilog synthesizes in Vivado for an Arty A7 target
  (smoke test, no runtime check yet)

### CORDIC + polynomial + LUT module library (0.5 session)

- [ ] `cordic_exp.v`, `cordic_ln.v`, `cordic_sincos.v`, `cordic_sqrt.v`
  — parametric WIDTH / FRAC / ITERATIONS
- [ ] `poly_exp.v`, `poly_ln.v` — DSP-heavy alternatives
- [ ] `lut_exp.v`, `lut_ln.v` — BRAM-heavy alternatives
- [ ] Each variant has a Verilator testbench in
  `hardware/simulation/tests/`

## 3.3 Simulation + verification (1 session)

**Deliverable:** `hardware/simulation/verilator_sim.py` runs the
generated Verilog against the C reference and reports max error +
bits-of-precision lost.

- [ ] Verilator integration (build + run + readback)
- [ ] Software reference via the C backend (ctypes call to
  generated `.c` compiled to a shared lib)
- [ ] Test-vector generation: 100 random inputs per function +
  50 boundary inputs (zero, ±1, ±large)
- [ ] Comparator returns max abs error, max rel error, bits lost
- [ ] CI runs Verilator simulation on every PR touching
  `hardware/` or `lang/`
- [ ] CUDA-accelerated simulation (Blackwell-gated): replace
  Verilator with a CUDA-resident simulator for batch runs of
  the same testbench across 10K+ vectors

---

## Cross-cutting deliverables

- [ ] At least one Xilinx target (`hardware/targets/xilinx/artix7.py`)
  end-to-end: compile → synthesize → bitstream
- [ ] At least one Lattice target (`hardware/targets/lattice/ice40.py`)
  using yosys + nextpnr (open toolchain — no vendor licenses)
- [ ] VHDL backend (subset of M3.2 — same modules, different syntax)
- [ ] Chisel backend (parameterized; emits FIRRTL)

---

## Out of scope (defer to v1.0)

- ASIC tape-out support
- Power estimation (per-unit dynamic power)
- Place-and-route closure feedback into the allocator
