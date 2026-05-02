# FPGA guide

How to take an EML kernel from source to FPGA bitstream — including LUT/DSP/latency estimation, precision selection, and the VS Code FPGA status bar.

## The `@target(fpga)` annotation

A function tagged for FPGA tells the hardware allocator (Patent #14) to plan resource usage based on the function's profile (chain order, node count, transcendental count) and the target device's constraints (LUT/DSP/BRAM counts, max frequency).

```eml
module autopilot;

@target(fpga, vendor = "xilinx", device = "artix7", precision = "f32", clock_mhz = 100.0)
@verify
fn step(error: Real, integral: Real) -> Real
    where chain_order <= 0
    requires (-1.0 <= error    && error    <= 1.0)
    requires (-1.0 <= integral && integral <= 1.0)
    ensures  (-1.5 <= result   && result   <= 1.5)
{
    let kp = 1.0;
    let ki = 0.2;
    kp * error + ki * integral
}
```

Annotation parameters:

| Parameter | Values | Default |
|---|---|---|
| `vendor` | `"xilinx"`, `"intel"`, `"lattice"`, `"microsemi"` | `"xilinx"` |
| `device` | vendor-specific (`"artix7"`, `"kintex7"`, `"zynq7000"`, `"cycloneV"`, `"ice40"`, …) | `"artix7"` |
| `precision` | `"f16"`, `"f32"`, `"f64"`, fixed-point e.g. `"q16.16"` | `"f32"` |
| `clock_mhz` | target operating frequency | `100.0` |
| `pipeline` | `true` / `false` — pipeline the datapath | inferred from clock target |
| `share` | `true` / `false` — share ALU resources across function calls | `true` for chain ≥ 2 |

## Estimating resources

```bash
eml-compile autopilot.eml --allocate --fpga-target xilinx.artix7
```

Output:

```
autopilot.eml — FPGA allocation plan
  device:        xilinx.artix7  (LUT 134k, DSP 740, BRAM 365)
  clock target:  100.0 MHz
  precision:     f32

  step:
    LUT estimate:    412   (0.31% of device)
    DSP estimate:    2     (Mul + MAC)
    BRAM estimate:   0
    latency:         3 cycles  (combinational + 2 pipeline stages)
    fmax estimate:   142 MHz   (passes 100 MHz target by 42%)
    chain_order:     0
    transcendentals: 0  (no CORDIC needed)

  TOTAL: 412 LUT, 2 DSP, 0 BRAM
```

For chain-order ≥ 1 functions, the allocator plans CORDIC modules from `hardware/modules/`:

```
  fresnel:
    LUT estimate:    2840   (2.1% of device)
    DSP estimate:    7
    BRAM estimate:   2
    latency:         24 cycles  (CORDIC pipeline)
    chain_order:     2
    transcendentals: pow (2 instances; shared)
```

## Selecting precision

Precision drives both resource cost and numerical accuracy. Forge supports:

| Precision | LUT cost (relative) | Notes |
|---|---|---|
| `f16` (half) | 1× | Cheapest. Watch out for accumulation error in chain ≥ 2. |
| `f32` (single) | ~2.5× | Default. Adequate for most signal-processing kernels. |
| `f64` (double) | ~7× | Use only when the kernel demands it. |
| `q16.16` (fixed) | ~0.5× | Cheapest. Bounded-domain kernels (PID, simple filters). |
| `q24.8`, `q8.24`, etc. | varies | Custom fixed-point formats. |

Forge's chain-order analysis flags drift risk: any chain-order-≥-2 body emits a `WARNING: float32 precision drift risk` comment in the generated HDL. Bumping the precision to f64 (or restructuring the body via the SuperBEST optimizer's identity rewrites) is your knob.

## Generating Verilog/VHDL/Chisel

```bash
eml-compile autopilot.eml --target verilog -o autopilot.v
eml-compile autopilot.eml --target vhdl    -o autopilot.vhd
eml-compile autopilot.eml --target chisel  -o Autopilot.scala
```

Each target gets the same allocator-driven module structure:

- One module/entity per function.
- A separate clock domain per `@target(fpga)` annotation.
- CORDIC modules pulled from `hardware/modules/` for transcendentals.
- Pipeline registers inserted to meet the `clock_mhz` target.
- Per-unit precision (the allocator may use f16 on the multiplier, f32 on the accumulator, etc., per Patent #14).

## Simulating with Verilator

```bash
eml-compile autopilot.eml --target verilog -o autopilot.v --fpga-sim
```

This compiles the Verilog with Verilator, runs the test fixtures from `tests/integration/`, and validates that the hardware path matches the software (C/Rust/Python) reference within the precision bound. The fixture format is a CSV of `(inputs, expected_output)` rows produced by running the software path on a randomized input set.

## VS Code FPGA status bar

With the [Forge VS Code extension](https://marketplace.visualstudio.com/items?itemName=monogate.eml-lang) installed, opening any `.eml` file with at least one `@target(fpga)` function activates the FPGA status bar:

```
[FPGA: xilinx.artix7]  step: 412 LUT, 2 DSP, 3 cyc @ 142 MHz
```

Click it to switch the active device — the estimates re-compute live. The LSP queries the allocator on every save, so the numbers stay current as you edit.

## End-to-end example: autopilot for Artix-7

The kernel in `industries/aerospace/flight_control/autopilot.eml` is a complete safety-critical autopilot stage:

1. **Source** — single `.eml` with three functions: `inner_loop` (chain 0), `outer_loop` (chain 1, uses `arctan`), `step` (composes them).
2. **Profile** — `eml-compile autopilot.eml --profile-only` reports chain orders 0, 1, 1.
3. **Allocate** — `eml-compile autopilot.eml --allocate --fpga-target xilinx.artix7` plans 1.4k LUT, 8 DSP, 1 BRAM, latency 19 cycles at 100 MHz.
4. **Generate** — `--target verilog` emits the module hierarchy.
5. **Simulate** — `--fpga-sim` runs Verilator against the C reference and confirms ULP-level agreement.
6. **Verify** — `--target lean` produces the safety theorem; the bundled MachLib lemmas discharge it without `sorry`.
7. **Synthesize** — drop the Verilog into Vivado, set the constraints from `hardware/targets/xilinx/artix7.xdc`, run synthesis. Resource usage matches the allocator estimate within ±5%.

## Vendor-specific notes

### Xilinx (Vivado)
- Constraint files live in `hardware/targets/xilinx/<device>.xdc`.
- DSP48E1 inference is automatic for f32 multiply-accumulate.
- BRAM-18 inference for `requires (lo <= x && x <= hi)` lookup tables (when SuperBEST chooses the LUT-replacement family).

### Intel (Quartus)
- Constraint files live in `hardware/targets/intel/<device>.sdc`.
- DSP block inference uses Stratix/Cyclone variant-specific synthesis attributes.

### Lattice (Yosys + nextpnr)
- Open-source flow; Forge emits Yosys-friendly Verilog (no proprietary primitives).
- iCE40 / ECP5 device files in `hardware/targets/lattice/`.

### Microsemi
- SmartFusion2 / IGLOO2 support; `vhdl` is the recommended target for Libero SoC.

---

For the full FPGA allocator algorithm and the per-unit precision selection (Patent #14), see `hardware/allocator/README.md` and `patents/014_fpga_allocator.md`.

Back to [backends](backends.md) for non-hardware targets, or [verify guide](verify-guide.md) for the formal-verification path.
