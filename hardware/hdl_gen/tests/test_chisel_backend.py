"""Tests for the Chisel/FIRRTL backend."""

from __future__ import annotations

import re
from pathlib import Path

from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.chisel_backend import ChiselBackend
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[3]


def _profile(path: Path):
    mod = parse_file(str(path))
    Profiler().profile_module(mod)
    plan = FPGAAllocator().allocate(mod)
    return mod, plan


def test_additive_voice_emits_class_and_io():
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = ChiselBackend().compile(mod, plan)
    assert "package monogate.gen" in v
    assert "import chisel3._" in v
    assert "class VoiceSamplePipeline(width: Int = " in v
    assert "extends Module" in v
    assert "val io = IO(new Bundle {" in v
    # Transcendental sub-modules referenced.
    assert "Module(new EmlSin(width))" in v


def test_class_name_matches_camelcase():
    """voice_sample -> VoiceSamplePipeline."""
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = ChiselBackend().compile(mod, plan)
    assert "class VoiceSamplePipeline(" in v


def test_custom_package_name():
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = ChiselBackend(package_name="acme.eml").compile(mod, plan)
    assert "package acme.eml" in v


def test_optimize_off_still_compiles():
    mod, plan = _profile(
        REPO_ROOT / "industries" / "audio" / "synthesis" / "additive_voice.eml"
    )
    v = ChiselBackend(optimize=False).compile(mod, plan)
    assert "class VoiceSamplePipeline" in v
