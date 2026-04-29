"""Intel/Altera Cyclone 10 LP target.

Numbers from the Intel Cyclone 10 LP Device Datasheet (DS-1090) for
the 10CL025YE144C8G part on the Terasic DE10-Lite. The Quartus Prime
Lite toolchain is free (closed) -- this target is the most accessible
Intel option for hobbyist and education contexts.
"""

from __future__ import annotations


NAME    = "Cyclone 10 LP 10CL025"
VENDOR  = "intel"
FAMILY  = "cyclone10lp"
PART    = "10CL025YE144C8G"

LUTS         = 24_624
DSPS         = 132     # 18x18 multipliers, packed into DSP blocks
BRAM_KB      = 594     # M9K blocks
MAX_FREQ_MHZ = 100

CONSTRAINTS_FILE = "constraints/de10_lite.qsf"


PER_UNIT_COST: dict[tuple[str, str], tuple[int, int, int]] = {
    ("exp",  "dedicated"): (1400, 5, 0),
    ("exp",  "shared"):    (1700, 6, 0),
    ("ln",   "dedicated"): (1200, 4, 0),
    ("ln",   "shared"):    (1500, 5, 0),
    ("sin",  "dedicated"): (1600, 5, 0),
    ("sin",  "shared"):    (1900, 6, 0),
    ("cos",  "dedicated"): (1600, 5, 0),
    ("cos",  "shared"):    (1900, 6, 0),
    ("tan",  "dedicated"): (1800, 5, 0),
    ("tan",  "shared"):    (2100, 6, 0),
    ("sqrt", "dedicated"): (1000, 4, 0),
    ("sqrt", "shared"):    (1300, 5, 0),
}

MAC_LUTS_PER_UNIT = 60
MAC_DSPS_PER_UNIT = 1


def precision_multiplier(precision_bits: int) -> tuple[float, float]:
    if precision_bits >= 64:
        return (2.1, 1.6)
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
        "toolchain": "Quartus Prime Lite",
    }
