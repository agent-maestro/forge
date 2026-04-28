# Phase 3 — Hardware Backends

**Goal:** Compile any example to synthesizable Verilog, simulate
via Verilator, and verify the hardware output matches the
software reference within declared tolerance.

## Milestones

- [ ] M3.1: FPGA allocator produces a per-unit assignment plan from the AST + cost class
- [ ] M3.2: Verilog backend emits parametric modules from the assignment plan
- [ ] M3.3: Hardware module library covers EML, EAL, EXL, EDL, EPL primitives
- [ ] M3.4: CORDIC + polynomial + LUT variants of `exp` / `ln` / `sin` / `cos` / `sqrt`
- [ ] M3.5: Pipeline scheduler inserts FIFOs / arbiters between shared units
- [ ] M3.6: Verilator integration runs on every PR (CI)
- [ ] M3.7: At least one Xilinx target (`artix7.py`) end-to-end
- [ ] M3.8: At least one Lattice target (`ice40.py`) using yosys + nextpnr (open toolchain)
- [ ] M3.9: VHDL backend (subset of M3.2)
- [ ] M3.10: Chisel backend (parameterized; emits FIRRTL)

## Out of scope (defer to v1.0)

- ASIC tape-out support
- Power estimation
- Place-and-route closure feedback to allocator
