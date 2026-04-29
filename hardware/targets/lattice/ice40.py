"""Lattice iCE40 UltraPlus 5K target -- open-toolchain FPGA target.

Numbers from the Lattice iCE40 UltraPlus 5K datasheet (FPGA-DS-02008
v1.4) and the iCEstick / iCEBreaker product briefs. Synthesis goes
through the open `yosys` + place-and-route through `nextpnr-ice40`
+ bitstream via `icepack` -- no vendor licenses needed, which makes
this the canonical CI / hobbyist target.

Conservative LUT/DSP/BRAM costs per transcendental unit are educated
estimates -- a real synthesis run would refine them.
"""

from __future__ import annotations


# Device identification
NAME    = "iCE40 UltraPlus 5K"
VENDOR  = "lattice"
FAMILY  = "ice40up5k"
PART    = "iCE40UP5K-SG48I"

# Resource budget (per Lattice FPGA-DS-02008).
LUTS         = 5_280       # 5,280 LUT4
DSPS         = 8           # 16x16 multiplier blocks
BRAM_KB      = 120         # 30 x 4 Kb EBR + SPRAM (SPRAM is separate)
MAX_FREQ_MHZ = 50          # Practical ceiling for transcendental pipelines

# Constraint file (pin assignments + timing)
CONSTRAINTS_FILE = "constraints/icebreaker.pcf"


# iCE40 has only 8 multipliers, so transcendentals cost more LUT
# glue per unit than on Artix-7. Bias the allocator toward shared
# strategies by inflating dedicated cost.
PER_UNIT_COST: dict[tuple[str, str], tuple[int, int, int]] = {
    ("exp",  "dedicated"): (1800, 2, 0),
    ("exp",  "shared"):    (2200, 3, 0),
    ("ln",   "dedicated"): (1500, 2, 0),
    ("ln",   "shared"):    (1900, 2, 0),
    ("sin",  "dedicated"): (2000, 2, 0),
    ("sin",  "shared"):    (2400, 3, 0),
    ("cos",  "dedicated"): (2000, 2, 0),
    ("cos",  "shared"):    (2400, 3, 0),
    ("tan",  "dedicated"): (2200, 2, 0),
    ("tan",  "shared"):    (2600, 3, 0),
    ("sqrt", "dedicated"): (1200, 2, 0),
    ("sqrt", "shared"):    (1500, 2, 0),
}

MAC_LUTS_PER_UNIT = 80
MAC_DSPS_PER_UNIT = 1


def precision_multiplier(precision_bits: int) -> tuple[float, float]:
    """Return (lut_multiplier, dsp_multiplier) for the chosen
    precision. iCE40 lacks native f64 -- f64 forces software emulation
    so the multiplier reflects the LUT-glue cost of doing so."""
    if precision_bits >= 64:
        return (3.0, 2.0)
    if precision_bits >= 32:
        return (1.0, 1.0)
    return (0.5, 0.5)


def as_dict() -> dict:
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
        "toolchain": "yosys + nextpnr-ice40 + icepack",
    }
