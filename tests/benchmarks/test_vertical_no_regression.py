"""Vertical benchmark snapshots -- regression gate.

Loads the baseline from `tools/benchmarks/vertical_baseline.json`
and verifies the current run's snapshot is at least as good on
every metric:

  - chain_order  : strictly equal (any change is a regression)
  - node_count   : current <= baseline
  - fpga_cycles  : current <= baseline
  - mac_units    : current <= baseline
  - trig_units   : current <= baseline

Updating the baseline is deliberate: when an optimizer change
genuinely improves things, regenerate via

    python -c "from tools.benchmarks import snapshot_path; \\
      from tools.benchmarks.snapshot import to_json; \\
      from pathlib import Path; \\
      m = {}; \\
      [m.update(snapshot_path(p)) for p in \\
        sorted(Path('industries').rglob('*.eml'))]; \\
      Path('tools/benchmarks/vertical_baseline.json').write_text( \\
        to_json(m), encoding='utf-8')"

then commit the regenerated JSON.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.benchmarks import (
    diff_against,
    load_baseline,
    snapshot_path,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = (
    REPO_ROOT / "tools" / "benchmarks" / "vertical_baseline.json"
)
INDUSTRY = REPO_ROOT / "industries"


def _generate_current() -> dict:
    """Build the current snapshot by walking every vertical .eml."""
    out: dict = {}
    for path in sorted(INDUSTRY.rglob("*.eml")):
        out.update(snapshot_path(path))
    return out


def test_baseline_file_exists() -> None:
    assert BASELINE_PATH.is_file(), (
        f"missing baseline at {BASELINE_PATH} -- regenerate via "
        f"the snippet in this file's docstring"
    )


def test_no_vertical_regressions() -> None:
    """Current per-vertical metrics must be >= baseline on every
    function. This is the foundation gate: an optimizer change
    that secretly grows a vertical's node count or FPGA cycles
    fails here loudly."""
    baseline = load_baseline(BASELINE_PATH)
    current = _generate_current()
    findings = diff_against(baseline, current)
    # Filter informational findings (NEW / DELETED) from REGRESS.
    regressions = [f for f in findings if f.startswith("REGRESS")]
    informational = [f for f in findings if not f.startswith("REGRESS")]
    assert not regressions, (
        "Vertical metric regressions detected:\n  "
        + "\n  ".join(regressions)
        + (
            f"\n\nInformational (drift, not regression):\n  "
            + "\n  ".join(informational)
            if informational else ""
        )
    )


def test_baseline_covers_every_local_vertical_function() -> None:
    """Every locally-defined function in every vertical .eml must
    appear in the baseline (so the regression gate covers it)."""
    baseline = load_baseline(BASELINE_PATH)
    current = _generate_current()
    missing = sorted(set(current) - set(baseline))
    if missing:
        pytest.fail(
            "Baseline missing entries (regenerate baseline JSON):\n  "
            + "\n  ".join(missing)
        )
