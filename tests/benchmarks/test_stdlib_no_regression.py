"""Stdlib benchmark snapshots -- regression gate.

Mirrors `test_vertical_no_regression.py` but for the 6 stdlib
modules. The baseline JSON lives at
`tools/benchmarks/stdlib_baseline.json`.

Why duplicate the vertical gate? Stdlib functions are imported by
every vertical -- if the optimizer accidentally bloats `lerp`'s
node count by 50 %, every caller suffers. Catching the regression
in the stdlib gate fingers the cause directly rather than letting
6 vertical gates light up red simultaneously.

Update procedure: same as the vertical gate -- regenerate via the
snippet in this file's docstring, commit the new JSON.

Snippet:

    python -c "from pathlib import Path; \\
      from tools.benchmarks import snapshot_path; \\
      from tools.benchmarks.snapshot import to_json; \\
      m = {}; \\
      [m.update(snapshot_path(p)) for p in \\
        sorted(Path('lang/spec/stdlib').glob('*.eml'))]; \\
      Path('tools/benchmarks/stdlib_baseline.json').write_text( \\
        to_json(m), encoding='utf-8')"
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
    REPO_ROOT / "tools" / "benchmarks" / "stdlib_baseline.json"
)
STDLIB_DIR = REPO_ROOT / "lang" / "spec" / "stdlib"


def _generate_current() -> dict:
    out: dict = {}
    for path in sorted(STDLIB_DIR.glob("*.eml")):
        out.update(snapshot_path(path))
    return out


def test_baseline_file_exists() -> None:
    assert BASELINE_PATH.is_file(), (
        f"missing baseline at {BASELINE_PATH} -- regenerate via "
        f"the snippet in this file's docstring"
    )


def test_no_stdlib_regressions() -> None:
    """Current per-stdlib metrics must be >= baseline. Any
    optimiser change that secretly grows a stdlib function's
    node count or FPGA cycles fails here loudly."""
    baseline = load_baseline(BASELINE_PATH)
    current = _generate_current()
    findings = diff_against(baseline, current)
    regressions = [f for f in findings if f.startswith("REGRESS")]
    informational = [f for f in findings if not f.startswith("REGRESS")]
    assert not regressions, (
        "Stdlib metric regressions detected:\n  "
        + "\n  ".join(regressions)
        + (
            f"\n\nInformational (drift, not regression):\n  "
            + "\n  ".join(informational)
            if informational else ""
        )
    )


def test_baseline_covers_every_stdlib_function() -> None:
    """Every function defined in lang/spec/stdlib/*.eml must
    appear in the baseline."""
    baseline = load_baseline(BASELINE_PATH)
    current = _generate_current()
    missing = sorted(set(current) - set(baseline))
    if missing:
        pytest.fail(
            "Stdlib baseline missing entries:\n  "
            + "\n  ".join(missing)
        )
