# Hardware Targets

Each target file declares device-specific resource budgets and
constraint hooks the FPGA allocator (`hardware/allocator/`)
consumes.

## Currently supported (planned)

### Xilinx
- `artix7.py` — Arty A7-35 / A7-100 (Digilent dev boards)
- `kintex7.py` — Kintex-7
- `ultrascale.py` — UltraScale+ family
- `zynq.py` — Zynq SoC (ARM + FPGA)

### Intel (Altera)
- `cyclone5.py` — Cyclone V (DE10-Nano dev board)
- `stratix10.py` — Stratix 10

### Lattice (open-source friendly)
- `ecp5.py` — ECP5 (yosys + nextpnr support)
- `ice40.py` — iCE40 (smallest, fully open toolchain)

### ASIC (open PDK)
- `sky130.py` — SkyWater 130nm (OpenROAD flow)
- `gf180.py` — GlobalFoundries 180nm (open PDK)
- `tsmc28.py` — TSMC 28nm (commercial flow)

## What a target file declares

```python
TARGET = {
    "name": "Arty A7-100",
    "vendor": "xilinx",
    "family": "artix7",
    "luts": 63400,
    "dsps": 240,
    "bram_kb": 4860,
    "max_freq_mhz": 100,
    "default_constraints": "constraints/arty_a7.xdc",
}
```

The allocator reads these to pick LUT/DSP/BRAM budgets per
hardware module.

## Adding a target

1. Create `<vendor>/<board>.py` with the dict above
2. Add the constraint file to `<vendor>/constraints/`
3. Add a smoke test in `tests/integration/` that compiles
   `lang/spec/grammar/examples/pid_basic.eml` to your target
4. Document in `roadmap/phases/phase3_hardware.md`
