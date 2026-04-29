"""Tests for the benchmark dashboard renderer."""

from __future__ import annotations

from tools.benchmarks.dashboard import render_dashboard


def _example_snapshots() -> tuple[dict, dict]:
    vertical = {
        "alpha::fast":  {
            "chain_order": 0, "node_count": 5,
            "fpga_cycles": 4, "mac_units": 2, "trig_units": 0,
        },
        "alpha::slow":  {
            "chain_order": 4, "node_count": 28,
            "fpga_cycles": 32, "mac_units": 8, "trig_units": 2,
        },
        "beta::middle": {
            "chain_order": 2, "node_count": 14,
            "fpga_cycles": 16, "mac_units": 6, "trig_units": 1,
        },
    }
    stdlib = {
        "math::lerp": {
            "chain_order": 0, "node_count": 7,
            "fpga_cycles": 4, "mac_units": 2, "trig_units": 0,
        },
        "ml::sigmoid": {
            "chain_order": 1, "node_count": 8,
            "fpga_cycles": 8, "mac_units": 1, "trig_units": 0,
        },
    }
    return vertical, stdlib


def test_dashboard_includes_top_level_sections() -> None:
    v, s = _example_snapshots()
    out = render_dashboard(v, s)
    assert "# Forge benchmark dashboard" in out
    assert "## Overview" in out
    assert "## Verticals" in out
    assert "## Stdlib" in out


def test_dashboard_overview_counts() -> None:
    v, s = _example_snapshots()
    out = render_dashboard(v, s)
    assert "Verticals: **3** functions" in out
    assert "Stdlib:    **2** functions" in out


def test_dashboard_per_module_table_groups_by_module() -> None:
    v, s = _example_snapshots()
    out = render_dashboard(v, s)
    # `alpha` and `beta` modules show up in the Verticals table.
    assert "`alpha`" in out
    assert "`beta`" in out
    # Their functions appear with the right metrics.
    assert "`fast`" in out and "`slow`" in out


def test_dashboard_top_n_section_ranks_by_chain_order() -> None:
    v, s = _example_snapshots()
    out = render_dashboard(v, s)
    chain_idx = out.index("Highest chain order")
    after = out[chain_idx:]
    # alpha::slow has the highest chain order (4); it should appear
    # in the top-N table.
    assert "`alpha::slow`" in after


def test_dashboard_handles_empty_snapshots() -> None:
    out = render_dashboard({}, {})
    assert "# Forge benchmark dashboard" in out
    assert "(no entries)" in out


def test_dashboard_output_is_deterministic() -> None:
    """Calling twice with same input yields byte-identical output
    so the report can live in version control without churn."""
    v, s = _example_snapshots()
    a = render_dashboard(v, s)
    b = render_dashboard(v, s)
    assert a == b
