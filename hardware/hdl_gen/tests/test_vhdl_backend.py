"""Tests for the VHDL backend."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.vhdl_backend import VHDLBackend
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[3]


def _profile(path: Path):
    mod = parse_file(str(path))
    Profiler().profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    return mod, plan


def test_additive_voice_emits_entity_and_arch():
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = VHDLBackend().compile(mod, plan)
    assert "entity voice_sample_pipeline is" in v
    assert "architecture rtl of voice_sample_pipeline is" in v
    assert "library IEEE;" in v
    assert "use IEEE.numeric_std.all;" in v
    # The transcendental sub-component is referenced.
    assert "entity work.eml_sin" in v


def test_biquad_lowpass_emits_one_module():
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "dsp" / "biquad_lowpass.eml"
    )
    v = VHDLBackend().compile(mod, plan)
    n_entities = len(re.findall(r"^entity \w+_pipeline is", v, re.MULTILINE))
    assert n_entities >= 1


def test_optimize_flag_can_be_disabled():
    """optimize=False bypasses the optimizer and still produces valid VHDL."""
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = VHDLBackend(optimize=False).compile(mod, plan)
    assert "entity voice_sample_pipeline is" in v
    assert "library IEEE;" in v


def test_signal_decls_are_in_arch_declarative_region():
    """In VHDL, `signal` decls go between `architecture` and `begin`."""
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = VHDLBackend().compile(mod, plan)
    # Find the first architecture block; signal decls should precede begin.
    arch_match = re.search(
        r"architecture rtl of \w+_pipeline is(.+?)begin",
        v, re.DOTALL,
    )
    assert arch_match
    declarative_region = arch_match.group(1)
    assert "signal s_w1 : signed(WIDTH-1 downto 0);" in declarative_region
