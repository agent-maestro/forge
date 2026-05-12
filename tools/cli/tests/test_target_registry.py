"""CLI target registry and license-tier truth tests."""

from __future__ import annotations

from tools.cli.main import ORDERED_TARGETS, TARGET_CHOICES, target_all_expansion
from tools.license.verifier import FREE_TARGETS, PRO_TARGETS, License, target_allowed


def test_cli_choices_excluding_all_count_to_36() -> None:
    choices = tuple(t for t in TARGET_CHOICES if t != "all")
    assert len(choices) == 36
    assert choices == ORDERED_TARGETS


def test_license_tiers_sum_to_declared_targets() -> None:
    assert len(FREE_TARGETS) == 13
    assert len(PRO_TARGETS) == 23
    assert len(FREE_TARGETS | PRO_TARGETS) == 36
    assert set(ORDERED_TARGETS) == FREE_TARGETS | PRO_TARGETS


def test_key_targets_are_in_expected_tiers() -> None:
    assert "wasm" in FREE_TARGETS
    assert "zkproof" in FREE_TARGETS
    for target in ("spice", "kicad", "jlcpcb"):
        assert target in PRO_TARGETS
        assert target in target_all_expansion()


def test_target_all_expansion_covers_every_cli_target() -> None:
    assert target_all_expansion() == ORDERED_TARGETS
    assert set(target_all_expansion()) == set(TARGET_CHOICES) - {"all"}


def test_license_gate_matches_target_registry() -> None:
    pro_license = License(
        email="agent@example.test",
        tier="pro",
        issued_at="2026-05-11",
    )
    for target in PRO_TARGETS:
        assert not target_allowed(target, None)
        assert target_allowed(target, pro_license)
    for target in FREE_TARGETS:
        assert target_allowed(target, None)
        assert target_allowed(target, pro_license)
