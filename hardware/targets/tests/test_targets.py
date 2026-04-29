"""Smoke tests for FPGA/ASIC target stubs -- verify shape parity with
the canonical artix7 entry."""

from __future__ import annotations

import importlib

import pytest


CANONICAL_KEYS = {
    "name", "vendor", "family", "part",
    "luts", "dsps", "bram_kb", "max_freq_mhz",
    "constraints_file",
}


@pytest.mark.parametrize("module_path", [
    "hardware.targets.xilinx.artix7",
    "hardware.targets.lattice.ice40",
    "hardware.targets.lattice.ecp5",
    "hardware.targets.intel.cyclone10",
    "hardware.targets.asic.sky130",
])
def test_target_module_exposes_canonical_dict(module_path):
    mod = importlib.import_module(module_path)
    d = mod.as_dict()
    missing = CANONICAL_KEYS - d.keys()
    assert not missing, f"{module_path}.as_dict() missing keys: {missing}"
    # Resource budgets are positive (or zero for ASIC with no fixed DSPs).
    assert d["luts"] >= 0
    assert d["dsps"] >= 0
    assert d["bram_kb"] >= 0
    assert d["max_freq_mhz"] > 0


@pytest.mark.parametrize("module_path", [
    "hardware.targets.xilinx.artix7",
    "hardware.targets.lattice.ice40",
    "hardware.targets.lattice.ecp5",
    "hardware.targets.intel.cyclone10",
    "hardware.targets.asic.sky130",
])
def test_per_unit_cost_table_present(module_path):
    mod = importlib.import_module(module_path)
    cost = getattr(mod, "PER_UNIT_COST", None)
    assert cost is not None
    # At least exp + sin + sqrt covered in both sharing modes.
    for op in ("exp", "sin", "sqrt"):
        for sharing in ("dedicated", "shared"):
            key = (op, sharing)
            assert key in cost, f"{module_path} missing {key}"


@pytest.mark.parametrize("module_path,bits,expect_lut_bigger_than_one", [
    ("hardware.targets.lattice.ice40",        64, True),
    ("hardware.targets.lattice.ice40",        32, False),
    ("hardware.targets.lattice.ice40",        16, False),
    ("hardware.targets.intel.cyclone10",      64, True),
    ("hardware.targets.asic.sky130",          64, True),
])
def test_precision_multiplier(module_path, bits, expect_lut_bigger_than_one):
    mod = importlib.import_module(module_path)
    lut_mult, dsp_mult = mod.precision_multiplier(bits)
    assert lut_mult > 0 and dsp_mult > 0
    if expect_lut_bigger_than_one:
        assert lut_mult > 1.0
