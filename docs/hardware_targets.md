# Hardware targets — compile to FPGA / ASIC

> Three HDL backends (Verilog, VHDL, Chisel) over five hardware
> targets (Xilinx Artix-7, Lattice iCE40 / ECP5, Intel Cyclone 10,
> SkyWater SKY130 ASIC). The same `.eml` source produces working
> hardware on any of them.

---

## At a glance

| Target | Output                          | Toolchain after compile             |
|--------|---------------------------------|-------------------------------------|
| `verilog` | Synthesizable Verilog (`.v`) | Vivado, yosys, Verilator            |
| `vhdl`    | VHDL-2008 (`.vhd`)           | Vivado, Quartus, GHDL               |
| `chisel`  | Chisel 3 / Scala source      | sbt + chisel3 (lowers to FIRRTL)    |

All three consume the FPGA allocator's `AllocationPlan` so the
emitted HDL is sized for the chosen device.

---

## Picking a hardware target

| Target id              | Family       | LUTs       | DSPs | BRAM (KB) | Toolchain                                      |
|------------------------|--------------|------------|------|-----------|------------------------------------------------|
| `xilinx.artix7`        | `artix7`     | 63 400     | 240  | 4 860     | Vivado (free)                                  |
| `lattice.ice40`        | `ice40up5k`  | 5 280      | 8    | 120       | yosys + nextpnr-ice40 + icepack (open)         |
| `lattice.ecp5`         | `ecp5`       | 84 000     | 156  | 3 744     | yosys + nextpnr-ecp5 + ecppack (open)          |
| `intel.cyclone10`      | `cyclone10lp`| 24 624     | 132  | 594       | Quartus Prime Lite (free)                      |
| `asic.sky130`          | `sky130`     | 200 000\*  | 0    | 0         | OpenLane (yosys + OpenROAD + magic + klayout)  |

\*SKY130's "LUTs" field carries NAND2-equivalent gate count — the
allocator reuses the field name across vendors.

Choose:

- **`xilinx.artix7`** if you need vendor-blessed Vivado flow and a
  well-supported dev board (Digilent Arty A7).
- **`lattice.ice40`** if you want an end-to-end open-source flow on
  the smallest possible board.
- **`lattice.ecp5`** if you've outgrown iCE40 but still want open
  tooling.
- **`intel.cyclone10`** if your shop runs Quartus.
- **`asic.sky130`** for the open path to silicon via Efabless /
  OpenLane.

---

## The `@target(fpga)` annotation

A function destined for hardware needs the annotation:

```eml
@target(fpga, clock_mhz = 100, precision = float32)
fn pid_step(error: Real, integral: Real, prev_error: Real) -> Real
  where chain_order <= 0
{
    Kp * error + Ki * integral + Kd * (error - prev_error)
}
```

- **`clock_mhz`** — target clock frequency (50, 100, 200, …).
  Higher → fewer pipeline stages allowed before timing closure
  fails.
- **`precision`** — `float16` / `float32` / `float64` / `fixed16`
  / `fixed32`. Higher precision means more LUTs/DSPs.
- **`max_luts`, `max_dsps`, `max_brams`** — optional. The
  allocator emits a `CompileError` if your design overruns; better
  than learning at synthesis time.

---

## Allocator output (`--allocate`)

Before emitting HDL, run the allocator to see the resource budget:

```
$ eml-compile autopilot.eml --allocate --fpga-target xilinx.artix7

Allocation plan for autopilot
  Target device: Arty A7-100
  Pipeline depth: 6 stages
  Clock target:   100 MHz
  Throughput:     16.7 Msamples/s

  Resources: 300 LUTs (out of 63,400; 0.5% util)
             6 DSPs    (out of 240;  2.5% util)
             0 KB BRAM (out of 4,860)

  Transcendental units:
    sin    count=4  sharing=shared      precision=32-bit
    exp    count=1  sharing=dedicated   precision=32-bit
```

The **sharing decision** is Patent #14 in operational form. When a
transcendental kind appears more than twice in the design, the
allocator instantiates a single shared unit with arbiter logic
rather than duplicating the macro. When it appears once or twice,
the allocator dedicates a unit per call site for lower latency.

If your design exceeds the device budget the allocator emits a
`CompileError` instead of producing unsynthesizable HDL:

```
allocator error: design exceeds budget for Arty A7-100
  estimated 5,200 LUTs (max 63,400)         [ok]
  estimated   320 DSPs (max 240)            [OVER by 33%]
suggestion: reduce trig sharing or pick a larger device.
```

---

## Verilog backend (`--target verilog`)

```
$ eml-compile autopilot.eml --target verilog -o autopilot.v
$ verilator --lint-only autopilot.v
```

The Verilog backend emits one parametric module per `@target(fpga)`
function:

```verilog
// Pipeline: pid_step
// Chain order: 0     Cost class: p0-d4-w0-c0
// EML depth:   1     Width: 32 bits
module pid_step_pipeline #(
    parameter WIDTH = 32
) (
    input  wire             clk,
    input  wire             rst,
    input  wire             valid_in,
    input  wire signed [WIDTH-1:0] error,
    input  wire signed [WIDTH-1:0] integral,
    input  wire signed [WIDTH-1:0] prev_error,
    output reg              valid_out,
    output reg signed [WIDTH-1:0] result
);
    // ... wire declarations + assigns ...
    always @(posedge clk) begin
        if (rst) begin
            valid_out <= 1'b0;
            result    <= '0;
        end else begin
            valid_out <= valid_in;
            result    <= _final_wire;
        end
    end
endmodule
```

**Pipeline shape**: one stage per EML AST node. Standard
`valid_in` / `valid_out` handshake. Registered output (one cycle
latency) — the body itself is combinational.

Transcendental ops become instantiations of `eml_<op>` modules
from `hardware/modules/transcendental/` (CORDIC variants by
default; allocator can swap for polynomial / LUT alternatives).

### Vivado flow

```
$ vivado -mode batch -source synth.tcl
```

Where `synth.tcl` references your generated `autopilot.v` and the
target's constraints file:

```tcl
read_verilog autopilot.v
read_xdc hardware/targets/xilinx/constraints/arty_a7.xdc
synth_design -top autopilot_step_pipeline -part xc7a100tcsg324-1
```

### yosys flow (Lattice iCE40)

```
$ yosys -p "read_verilog autopilot.v; \
            synth_ice40 -json autopilot.json"
$ nextpnr-ice40 --up5k --package sg48 \
    --pcf hardware/targets/lattice/constraints/icebreaker.pcf \
    --json autopilot.json --asc autopilot.asc
$ icepack autopilot.asc autopilot.bin
```

End-to-end open toolchain. Boards: iCEBreaker, Fomu, TinyFPGA-BX.

---

## VHDL backend (`--target vhdl`)

```
$ eml-compile autopilot.eml --target vhdl -o autopilot.vhd
$ ghdl --syntax autopilot.vhd
```

Same shape as the Verilog backend, VHDL-2008 syntax:

```vhdl
library IEEE;
use IEEE.std_logic_1164.all;
use IEEE.numeric_std.all;

entity pid_step_pipeline is
    generic ( WIDTH : integer := 32 );
    port (
        clk       : in  std_logic;
        rst       : in  std_logic;
        valid_in  : in  std_logic;
        error     : in  signed(WIDTH-1 downto 0);
        integral  : in  signed(WIDTH-1 downto 0);
        prev_error: in  signed(WIDTH-1 downto 0);
        valid_out : out std_logic;
        result    : out signed(WIDTH-1 downto 0)
    );
end entity pid_step_pipeline;

architecture rtl of pid_step_pipeline is
    signal s_w1 : signed(WIDTH-1 downto 0);
    -- ...
begin
    process(clk) begin
        if rising_edge(clk) then
            -- registered output
        end if;
    end process;
end architecture rtl;
```

Transcendentals become `entity work.eml_<op>` instances; bodies
live in `hardware/modules/transcendental_vhd/`.

### Quartus flow (Intel Cyclone 10)

```
$ quartus_map --read_settings_files=on autopilot.qpf
$ quartus_fit autopilot.qpf
$ quartus_asm autopilot.qpf
```

The generated `.vhd` plugs into Quartus Prime Lite without
modification.

---

## Chisel backend (`--target chisel`)

```
$ eml-compile autopilot.eml --target chisel -o Autopilot.scala
```

Chisel 3 / Scala source consuming `chisel3._`:

```scala
package monogate.gen

import chisel3._
import chisel3.util._

class PidStepPipeline(width: Int = 32) extends Module {
  val io = IO(new Bundle {
    val validIn   = Input(Bool())
    val error     = Input(SInt(width.W))
    val integral  = Input(SInt(width.W))
    val prevError = Input(SInt(width.W))
    val validOut  = Output(Bool())
    val result    = Output(SInt(width.W))
  })

  // ... combinational body ...

  io.validOut := RegNext(io.validIn, init = false.B)
  io.result   := RegNext(_final_wire, init = 0.S(width.W))
}
```

Function-name → class-name conversion: snake_case → CamelCase +
`Pipeline` suffix.

### sbt flow

```
$ sbt "runMain monogate.gen.PidStepPipeline --target-dir build"
```

Chisel 3 lowers your Scala module to **FIRRTL** (the IR), then
through `firtool` to Verilog. The Verilog goes through the same
vendor flow as `--target verilog` produces directly. Chisel is the
preferred path for SiFive / Chipyard / Rocket toolchains.

---

## Verilator simulation

If you have `verilator` on PATH, the harness can drive the emitted
Verilog against the C reference and report bit-exact agreement:

```
$ pytest hardware/simulation/tests/ -v
```

The harness:

1. Compiles the Verilog with `verilator --cc`.
2. Compiles the C reference with `gcc -O2`.
3. Generates 100 random + 50 boundary input vectors.
4. Runs both and reports `max_abs_err`, `max_rel_err`,
   `bits_lost`.

Patent #22 demonstration: every vector matches within 3 LSBs of
the configured Q-format (Q16.16 by default). When the agreement
breaks, the harness names the input that caused divergence and
the bit position of the first mismatch.

---

## Adding a new hardware target

1. Create `hardware/targets/<vendor>/<part>.py` matching the
   `xilinx.artix7` shape (`NAME`, `VENDOR`, `FAMILY`, `LUTS`,
   `DSPS`, `BRAM_KB`, `MAX_FREQ_MHZ`, `PER_UNIT_COST`,
   `precision_multiplier()`, `as_dict()`).
2. Drop a constraints file under
   `hardware/targets/<vendor>/constraints/`.
3. Register the `<vendor>.<part>` string in
   `hardware/allocator/targets.py`.
4. Add a parametrize entry to
   `hardware/targets/tests/test_targets.py`.

The allocator + every backend pick up the new target without
further modification.

See [`api_reference/targets.md`](api_reference/targets.md) for the
full target-module reference.

---

## Where to look next

- [`software_targets.md`](software_targets.md) — C, Rust, Python,
  LLVM, WASM.
- [`verification_guide.md`](verification_guide.md) — `@verify(lean)`
  for the safety-critical verticals.
- [`industry_guides/aerospace.md`](industry_guides/aerospace.md) —
  full DO-178C-aligned FPGA walk-through.
- [`industry_guides/automotive.md`](industry_guides/automotive.md)
  — FOC motor control, FPGA-deployed.
- [`api_reference/targets.md`](api_reference/targets.md) — every
  per-target field documented.
- `hardware/allocator/allocator.py` — Patent #14 allocator
  source.
