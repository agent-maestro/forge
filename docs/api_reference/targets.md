# FPGA / ASIC targets

> Target shape lives in `hardware/targets/<vendor>/<part>.py`.
> Every target exposes the same fields, so the allocator is
> agnostic to vendor.

---

## Live targets

| Target               | Family       | LUTs    | DSPs | BRAM (KB) | Max MHz | Toolchain                                     |
|----------------------|--------------|---------|------|-----------|---------|-----------------------------------------------|
| `xilinx.artix7`      | `artix7`     | 63 400  | 240  | 4 860     | 100     | Vivado                                        |
| `lattice.ice40`      | `ice40up5k`  | 5 280   | 8    | 120       | 50      | yosys + nextpnr-ice40 + icepack               |
| `lattice.ecp5`       | `ecp5`       | 84 000  | 156  | 3 744     | 200     | yosys + nextpnr-ecp5 + ecppack                |
| `intel.cyclone10`    | `cyclone10lp`| 24 624  | 132  | 594       | 100     | Quartus Prime Lite                            |
| `asic.sky130`        | `sky130`     | 200 000 | 0    | 0         | 100     | OpenLane (yosys + OpenROAD + magic + klayout) |

LUT counts on `asic.sky130` are NAND2-equivalent gate counts —
SkyWater 130nm doesn't have fixed-function LUTs, so the
allocator's same field is reinterpreted.

---

## Each target module exposes

```python
NAME              # Display name
VENDOR            # "xilinx" / "lattice" / "intel" / "skywater"
FAMILY            # "artix7" / "ice40up5k" / ...
PART              # Vendor-specific part number
LUTS              # int -- max LUTs (or NAND2-eq gates for ASIC)
DSPS              # int -- max DSP slices
BRAM_KB           # int -- max block RAM in kilobytes
MAX_FREQ_MHZ      # int -- conservative timing closure ceiling
CONSTRAINTS_FILE  # str -- relative path to pin/timing constraints

PER_UNIT_COST     # dict[(op, sharing) -> (luts, dsps, bram_kb)]
MAC_LUTS_PER_UNIT # int
MAC_DSPS_PER_UNIT # int

def precision_multiplier(precision_bits) -> (lut_mult, dsp_mult): ...
def as_dict() -> dict: ...
```

The allocator reads `as_dict()` and the cost table; the
hardware backends use `as_dict()` only for the file-header
comment.

---

## Adding a new target

1. Create `hardware/targets/<vendor>/<part>.py` matching the
   `xilinx.artix7` shape.
2. Add a constraints file under
   `hardware/targets/<vendor>/constraints/` if your toolchain
   needs one (XDC for Vivado, PCF for nextpnr, LPF for ECP5,
   QSF for Quartus, TCL for OpenLane).
3. Register the target string in
   `hardware/allocator/targets.py` (the resolver that maps
   `--fpga-target=<vendor>.<part>` strings to module objects).
4. Add a parametrize entry to
   `hardware/targets/tests/test_targets.py`.
5. (Optional) Add a smoke benchmark to
   `tools/benchmarks/vertical_baseline.json` for the new
   target.

---

## Why these particular targets?

- **Xilinx Artix-7** is the canonical Digilent Arty A7 dev
  board and our first-class demo target. Vivado is closed but
  free, and this part has enough resources to fit every
  industry vertical without sweating.
- **Lattice iCE40 UltraPlus 5K** is the open-toolchain canonical
  — yosys + nextpnr-ice40 + icepack drives the smallest
  resource footprint, which matters in CI: builds finish in
  seconds.
- **Lattice ECP5** is the mid-range open target; same toolchain
  as iCE40 but order-of-magnitude bigger.
- **Intel Cyclone 10 LP** covers the Quartus Prime Lite path —
  closed but free, popular in education.
- **SkyWater SKY130** is the "free path to silicon" via
  OpenLane / Efabless. Same EML source becomes synthesized
  ASIC artifacts; the cost field carries gate-equivalent
  counts.

A future target would slot in identically — the allocator and
backends do not bake any vendor-specific knowledge above the
target-module layer.
