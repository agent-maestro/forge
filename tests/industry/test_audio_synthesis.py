"""Tests for industries/audio/synthesis/additive_voice.eml.

The vertical is the Patent #14 (FPGA resource allocator) demo:
4 sin calls + 1 exp call in one @target(fpga) function. The
allocator's `dedicated` vs `shared` decision is the headline
behaviour these tests pin down.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hardware.allocator import FPGAAllocator
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler


REPO_ROOT = Path(__file__).resolve().parents[2]
VOICE_FILE = (
    REPO_ROOT / "industries" / "audio" / "synthesis"
    / "additive_voice.eml"
)


@pytest.fixture(scope="module")
def voice_module():
    mod = parse_file(VOICE_FILE)
    Profiler().profile_module(mod)
    return mod


# ── Source presence + parse ──────────────────────────────────


def test_voice_source_exists():
    assert VOICE_FILE.exists(), f"missing {VOICE_FILE}"


def test_voice_module_has_expected_functions(voice_module):
    """3 local fns: partial / envelope / voice_sample."""
    local = {
        f.name for f in voice_module.functions
        if f.imported_from is None
    }
    assert local == {"partial", "envelope", "voice_sample"}


def test_voice_sample_carries_target_and_verify(voice_module):
    fn = next(
        f for f in voice_module.functions if f.name == "voice_sample"
    )
    targets = [a for a in fn.annotations if a.kind == "target"]
    verifies = [a for a in fn.annotations if a.kind == "verify"]
    assert len(targets) == 1
    assert len(verifies) == 1


# ── Patent #14: allocator behaviour ──────────────────────────


def test_allocator_picks_shared_sin_dedicated_exp(voice_module):
    """4 sin call sites -> over the SHARING_THRESHOLD (2) ->
    `shared` time-multiplexed sin unit. 1 exp -> `dedicated`."""
    plan = FPGAAllocator().allocate(voice_module)
    by_op = {u.op: u for u in plan.transcendental_units}
    assert "sin" in by_op, "expected at least one sin unit"
    assert "exp" in by_op, "expected at least one exp unit"

    sin_unit = by_op["sin"]
    exp_unit = by_op["exp"]
    assert sin_unit.count == 4, (
        f"expected 4 sin call-sites; got {sin_unit.count}"
    )
    assert sin_unit.sharing == "shared", (
        f"with count > SHARING_THRESHOLD, sin should share; "
        f"got sharing={sin_unit.sharing!r}"
    )
    assert exp_unit.count == 1, (
        f"expected 1 exp call-site; got {exp_unit.count}"
    )
    assert exp_unit.sharing == "dedicated", (
        f"with count == 1, exp should be dedicated; "
        f"got sharing={exp_unit.sharing!r}"
    )


def test_allocator_emits_arbiter_note(voice_module):
    """When ANY transcendental is shared, the plan's notes
    flag that the Verilog backend will need FIFO arbiters."""
    plan = FPGAAllocator().allocate(voice_module)
    note_text = " ".join(plan.notes)
    assert "arbiter" in note_text.lower() or "shared" in note_text.lower()


def test_allocator_disables_optimize_pre_pass_when_asked(
    voice_module,
):
    """With optimize=False the allocator sees the unoptimised
    AST; the user CALLs to `partial` / `envelope` survive and
    the transcendentals stay hidden behind them. Test verifies
    the opt-out path still works for users who want it."""
    plan = FPGAAllocator(optimize=False).allocate(voice_module)
    by_op = {u.op: u for u in plan.transcendental_units}
    # No sin / exp visible because they're inside the helpers'
    # bodies, not directly in voice_sample.
    assert "sin" not in by_op
    assert "exp" not in by_op


# ── FPGA budget fits Arty A7-100 ─────────────────────────────


def test_voice_fits_arty_a7_budget(voice_module):
    """Resource consumption stays within the Arty A7-100's
    LUT / DSP budget. Patent #14's headline claim: sharing keeps
    the footprint bounded even as call-site count grows."""
    plan = FPGAAllocator().allocate(voice_module)
    assert plan.target_device == "Arty A7-100"
    assert plan.estimated_luts < 50_000, (
        f"LUT budget exceeded: {plan.estimated_luts}"
    )
    assert plan.estimated_dsps < 200, (
        f"DSP budget exceeded: {plan.estimated_dsps}"
    )
