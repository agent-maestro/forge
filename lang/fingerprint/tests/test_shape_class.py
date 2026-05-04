"""Tests for the C-237 shape-class lookup."""

from __future__ import annotations

from lang.fingerprint.shape_class import (
    classify,
    class_name,
    coverage_of,
    _canonical_index,
)


# ── Canonical index ───────────────────────────────────────────────


def test_canonical_index_holds_exactly_seventy_six_classes() -> None:
    by_name, classes = _canonical_index()
    assert len(classes) == 76
    assert len(by_name) == 76


def test_class_zero_is_the_most_common_in_the_corpus() -> None:
    """The C-237 corpus puts ``p0-d3-w0-c0`` (chain-0, depth-3,
    no-transcendental, no-composite) at the top of the frequency
    distribution. ID 0 is reserved for it forever — moving it would
    break every published fingerprint."""
    _, classes = _canonical_index()
    assert classes[0] == "p0-d3-w0-c0"


# ── classify() ────────────────────────────────────────────────────


def test_classify_known_cost_class_returns_id() -> None:
    profile = {"cost_class": "p0-d3-w0-c0"}
    assert classify(profile) == 0


def test_classify_recognises_chain_one_gaussian_class() -> None:
    """Sigmoid + Gaussian both land in the ``p1-d2-w1-c0`` class."""
    profile = {"cost_class": "p1-d2-w1-c0"}
    assert classify(profile) is not None
    assert isinstance(classify(profile), int)


def test_classify_returns_none_for_unknown_class() -> None:
    profile = {"cost_class": "p99-d99-w99-c99"}
    assert classify(profile) is None


def test_classify_returns_none_for_empty_profile() -> None:
    assert classify({}) is None


def test_classify_returns_none_for_none_profile() -> None:
    assert classify(None) is None


def test_classify_returns_none_when_cost_class_is_not_a_string() -> None:
    assert classify({"cost_class": 5}) is None


# ── class_name() ──────────────────────────────────────────────────


def test_class_name_round_trips() -> None:
    cc = "p1-d2-w1-c0"
    cid = classify({"cost_class": cc})
    assert cid is not None
    assert class_name(cid) == cc


def test_class_name_rejects_out_of_range_id() -> None:
    assert class_name(-1) is None
    assert class_name(76) is None
    assert class_name(10_000) is None


# ── coverage_of() ─────────────────────────────────────────────────


def test_coverage_of_mixed_input() -> None:
    profiles = [
        {"cost_class": "p0-d3-w0-c0"},     # known
        {"cost_class": "p1-d2-w1-c0"},     # known
        {"cost_class": "p99-d99-w99-c99"}, # unknown_with_cost_class
        {"chain_order": 5},                # no_cost_class
        None,                               # no_cost_class
    ]
    out = coverage_of(profiles)
    assert out == {
        "known": 2,
        "unknown_with_cost_class": 1,
        "no_cost_class": 2,
    }
