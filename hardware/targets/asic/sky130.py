"""SkyWater SKY130 ASIC target -- open-PDK ASIC tapeout.

The SKY130 PDK (released by SkyWater + Google in 2020) is the
open-source 130nm process node powering the Efabless / OpenLane
ASIC tapeout flow. EML-lang's Lean-verified pipelines target this
PDK as the "free" path to silicon, the same way iCE40 is the free
FPGA path.

Cost model: ASIC numbers are *gate equivalents* (NAND2-eq) rather
than LUTs/DSPs because there is no fixed-function silicon to map
into. We expose them under the same field names so the allocator
needs zero special-casing.
"""

from __future__ import annotations


NAME    = "SkyWater SKY130 (open-PDK)"
VENDOR  = "skywater"
FAMILY  = "sky130"
PART    = "sky130_fd_sc_hd"

# Gate-equivalent budget for a typical ~1 mm^2 die. Real numbers
# depend on standard-cell library + density; these are conservative
# upper bounds for what the OpenLane flow handles routinely.
LUTS         = 200_000     # interpreted as NAND2-equivalent gates
DSPS         = 0           # no fixed multipliers in standard-cell flow
BRAM_KB      = 0           # SRAM macros via OpenRAM, opted in per design
MAX_FREQ_MHZ = 100

CONSTRAINTS_FILE = "constraints/openlane.config.tcl"


# Synthesized gate-eq cost per transcendental unit (combinational
# CORDIC, 32-bit, single-cycle pipeline stage).
PER_UNIT_COST: dict[tuple[str, str], tuple[int, int, int]] = {
    ("exp",  "dedicated"): (12_000, 0, 0),
    ("exp",  "shared"):    (15_000, 0, 0),
    ("ln",   "dedicated"): (10_000, 0, 0),
    ("ln",   "shared"):    (13_000, 0, 0),
    ("sin",  "dedicated"): (14_000, 0, 0),
    ("sin",  "shared"):    (17_000, 0, 0),
    ("cos",  "dedicated"): (14_000, 0, 0),
    ("cos",  "shared"):    (17_000, 0, 0),
    ("tan",  "dedicated"): (15_000, 0, 0),
    ("tan",  "shared"):    (18_000, 0, 0),
    ("sqrt", "dedicated"): (8_000,  0, 0),
    ("sqrt", "shared"):    (10_000, 0, 0),
}

# A 32x32 multiplier in standard cells is roughly 4000 NAND2-eq.
MAC_LUTS_PER_UNIT = 4_000
MAC_DSPS_PER_UNIT = 0


def precision_multiplier(precision_bits: int) -> tuple[float, float]:
    """Standard-cell gate count scales linearly with width since
    there are no fixed-function multipliers."""
    if precision_bits >= 64:
        return (2.0, 1.0)
    if precision_bits >= 32:
        return (1.0, 1.0)
    return (0.5, 1.0)


def as_dict() -> dict:
    return {
        "name": NAME,
        "vendor": VENDOR,
        "family": FAMILY,
        "part": PART,
        "luts": LUTS,           # NAND2-equivalent
        "dsps": DSPS,
        "bram_kb": BRAM_KB,
        "max_freq_mhz": MAX_FREQ_MHZ,
        "constraints_file": CONSTRAINTS_FILE,
        "toolchain": "OpenLane (yosys + OpenROAD + magic + klayout)",
        "pdk": "sky130A",
    }
