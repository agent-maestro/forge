"""Xilinx Artix-7 (Arty A7-100) target -- FPGA allocator inputs.

Numbers from Xilinx UG471 + the Arty A7 product brief. The Arty A7-100
is the Digilent dev board that's the canonical first-class target
for monogate-forge demos.

Conservative LUT/DSP/BRAM costs per transcendental unit are
educated estimates -- a real synthesis run would refine them.
"""

from __future__ import annotations


# Device identification
NAME    = "Arty A7-100"
VENDOR  = "xilinx"
FAMILY  = "artix7"
PART    = "xc7a100tcsg324-1"

# Resource budget (per Digilent / Xilinx product brief)
LUTS         = 63_400
DSPS         = 240
BRAM_KB      = 4_860     # Block RAM, kilobytes
MAX_FREQ_MHZ = 100       # Conservative; the part is good to 450 in spots

# Constraint file (pin assignments + timing)
CONSTRAINTS_FILE = "constraints/arty_a7.xdc"


# Per-transcendental-unit resource cost. Each entry maps an
# (operator, sharing strategy) pair to (LUTs, DSPs, BRAM_KB) for
# that unit at the default precision (f32). f64 doubles LUT cost
# and bumps DSPs by 50%; f16 halves both.
PER_UNIT_COST: dict[tuple[str, str], tuple[int, int, int]] = {
    ("exp",  "dedicated"): (1200, 4, 0),
    ("exp",  "shared"):    (1500, 5, 0),
    ("ln",   "dedicated"): (1000, 3, 0),
    ("ln",   "shared"):    (1300, 4, 0),
    ("sin",  "dedicated"): (1400, 4, 0),
    ("sin",  "shared"):    (1700, 5, 0),
    ("cos",  "dedicated"): (1400, 4, 0),
    ("cos",  "shared"):    (1700, 5, 0),
    ("tan",  "dedicated"): (1500, 4, 0),
    ("tan",  "shared"):    (1800, 5, 0),
    ("sqrt", "dedicated"): (800,  3, 0),
    ("sqrt", "shared"):    (1000, 4, 0),
}

# MAC unit cost (one DSP slice + a small amount of LUT glue).
MAC_LUTS_PER_UNIT = 50
MAC_DSPS_PER_UNIT = 1


def precision_multiplier(precision_bits: int) -> tuple[float, float]:
    """Return (lut_multiplier, dsp_multiplier) for the chosen
    precision. Defaults assume f32 baseline."""
    if precision_bits >= 64:
        return (2.0, 1.5)
    if precision_bits >= 32:
        return (1.0, 1.0)
    return (0.5, 0.5)


def as_dict() -> dict:
    """Serialize the target spec as a plain dict for the allocator."""
    return {
        "name": NAME,
        "vendor": VENDOR,
        "family": FAMILY,
        "part": PART,
        "luts": LUTS,
        "dsps": DSPS,
        "bram_kb": BRAM_KB,
        "max_freq_mhz": MAX_FREQ_MHZ,
        "constraints_file": CONSTRAINTS_FILE,
    }
