"""Lattice ECP5 LFE5UM-85F target -- mid-range open-toolchain FPGA.

Numbers from the Lattice ECP5/ECP5-5G Family Data Sheet (FPGA-DS-02012).
The ECP5 has DSP slices (sysDSP) and is the preferred Lattice target
when the iCE40 runs out of resources -- still drives through the open
yosys + nextpnr-ecp5 toolchain.
"""

from __future__ import annotations


NAME    = "ECP5 LFE5UM-85F"
VENDOR  = "lattice"
FAMILY  = "ecp5"
PART    = "LFE5UM-85F-8BG756C"

LUTS         = 84_000
DSPS         = 156
BRAM_KB      = 3_744
MAX_FREQ_MHZ = 200

CONSTRAINTS_FILE = "constraints/ecp5_evn.lpf"


PER_UNIT_COST: dict[tuple[str, str], tuple[int, int, int]] = {
    ("exp",  "dedicated"): (1300, 4, 0),
    ("exp",  "shared"):    (1600, 5, 0),
    ("ln",   "dedicated"): (1100, 3, 0),
    ("ln",   "shared"):    (1400, 4, 0),
    ("sin",  "dedicated"): (1500, 4, 0),
    ("sin",  "shared"):    (1800, 5, 0),
    ("cos",  "dedicated"): (1500, 4, 0),
    ("cos",  "shared"):    (1800, 5, 0),
    ("tan",  "dedicated"): (1700, 4, 0),
    ("tan",  "shared"):    (2000, 5, 0),
    ("sqrt", "dedicated"): (900,  3, 0),
    ("sqrt", "shared"):    (1100, 4, 0),
}

MAC_LUTS_PER_UNIT = 50
MAC_DSPS_PER_UNIT = 1


def precision_multiplier(precision_bits: int) -> tuple[float, float]:
    if precision_bits >= 64:
        return (2.2, 1.6)
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
        "toolchain": "yosys + nextpnr-ecp5 + ecppack",
    }
