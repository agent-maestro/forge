"""Vertical benchmark snapshots.

Records per-function metrics (chain order, node count, FPGA
estimated cycles) into a stable JSON snapshot. The CI gate
asserts no metric regresses without a deliberate snapshot
update -- catching cases where an optimizer change accidentally
made a vertical's resource footprint larger.

Public entries:

  snapshot_module(mod) -> dict     One module's measurements
  snapshot_path(path) -> dict      Same, taking a .eml path
  load_baseline(path)              Read a saved baseline JSON
  diff_against(baseline, current)  -> list[str] of regressions
"""

from tools.benchmarks.snapshot import (
    diff_against,
    load_baseline,
    snapshot_module,
    snapshot_path,
)

__all__ = [
    "diff_against",
    "load_baseline",
    "snapshot_module",
    "snapshot_path",
]
