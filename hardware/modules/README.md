# Hardware Module Library

Synthesizable HDL building blocks the FPGA backend stitches together.
Every module here:

- Has a software reference (in `software/runtime/c/` or `lang/spec/stdlib/`)
- Has a parametric `WIDTH` / `FRAC` / `PIPELINE_STAGES` signature
- Has Verilator + Icarus simulation tests
- Compares to the software reference within declared tolerance

## Categories

| Subdir | Contents |
|--------|----------|
| `eml_operators/` | EML, EAL, EXL, EDL, EPL primitives — the canonical 5 |
| `transcendental/` | exp, ln, sin/cos, sqrt — CORDIC + poly + LUT variants |
| `arithmetic/` | fp / fixed-point add, mul, div, MAC |
| `pipeline/` | Generic pipeline stage, arbiter, FIFO |

## Picking implementation per target

The FPGA allocator (`hardware/allocator/`) chooses which variant
of each transcendental to instantiate based on:

- Available LUT / DSP / BRAM budget
- Target frequency
- Required precision (declared in the source `.eml` `precision` clause)

CORDIC is dense in LUTs; polynomial uses DSPs; LUT-based uses BRAM.
The allocator picks the right balance per-unit.

## Adding a module

1. Write the `.v` file with consistent parameter names
2. Add a Python wrapper in `hardware/hdl_gen/` if it should be
   reachable from the compiler
3. Add a test in `tests/integration/` comparing to the software ref
4. Document the module here
