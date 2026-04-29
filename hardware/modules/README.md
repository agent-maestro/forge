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
| `transcendental/` | exp, ln, sin/cos/tan, sqrt, sinh/cosh/tanh, asin/acos/atan |
| `arithmetic/` | fp / fixed-point add, mul, div, MAC |
| `pipeline/` | Generic pipeline stage, arbiter, FIFO |

### Transcendental library (12 modules, all SCAFFOLD)

| Module | Approach (scaffold) | Safe input range |
|--------|---------------------|------------------|
| `eml_exp` | 4-term Taylor | `|x| <= 1` |
| `eml_ln` | 4-term Taylor on `1+u` | `x in [0.5, 1.5]` |
| `eml_sin` | 3-term Taylor | `|x| <= pi/2` |
| `eml_cos` | 4-term Taylor | `|x| <= pi/2` |
| `eml_tan` | 4-term Taylor | `|x| <= pi/4` |
| `eml_sqrt` | 3-step Newton-Raphson | `x in [0.25, 4]` |
| `eml_sinh` | 3-term Taylor | `|x| <= 1` |
| `eml_cosh` | 4-term Taylor | `|x| <= 1` |
| `eml_tanh` | 4-term Taylor | `|x| <= 1` |
| `eml_asin` | 4-term Taylor | `|x| <= 0.5` |
| `eml_acos` | `pi/2 - asin(x)` | `|x| <= 0.5` |
| `eml_atan` | 4-term Taylor | `|x| <= 1` |

All twelve share the same `WIDTH` / `FRAC` / `PIPELINE_STAGES` parameter
set and the same `(clk, rst, in_valid, x_in) -> (out_valid, result)`
port shape. Caller responsibility:

- **Range reduction** outside the safe band (e.g. `exp(x) = 2^k * exp(r)`)
- **Q-format scaling** (default Q16.16 from `hardware/hdl_gen/qformat.py`)
- **Swapping** the Taylor scaffold for CORDIC / LUT / Padé per the
  FPGA allocator's choice (Patent #14)

Structural tests in `transcendental/tests/test_transcendental_modules.py`
verify the interface; Verilator-lint runs automatically when verilator
is on PATH.

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
