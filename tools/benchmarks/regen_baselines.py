#!/usr/bin/env python3
"""Regenerate the benchmark baseline JSONs from current source.

Run this AFTER an intentional change adds or modifies functions
in `industries/` (vertical baseline) or `lang/spec/stdlib/`
(stdlib baseline). The baseline files are tracked in git so the
diff lands in the next commit.

CRITICAL: diagnose the test failure FIRST, then regenerate.
Auto-accepting a regression silently launders bugs into the
baseline. The manual diagnose-or-regenerate loop IS the audit
system -- do not bypass it.

Usage:

    # Regenerate the vertical baseline (default):
    python tools/benchmarks/regen_baselines.py

    # Regenerate the stdlib baseline instead:
    python tools/benchmarks/regen_baselines.py --stdlib

    # Regenerate both at once:
    python tools/benchmarks/regen_baselines.py --all
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the script runnable from anywhere by anchoring to the repo
# root from this file's location.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.benchmarks import snapshot_path
from tools.benchmarks.snapshot import to_json


VERTICAL_BASELINE = REPO_ROOT / "tools" / "benchmarks" / "vertical_baseline.json"
STDLIB_BASELINE   = REPO_ROOT / "tools" / "benchmarks" / "stdlib_baseline.json"

INDUSTRY_DIR = REPO_ROOT / "industries"
STDLIB_DIR   = REPO_ROOT / "lang" / "spec" / "stdlib"


def regen_vertical() -> int:
    """Walk every .eml under industries/ and rewrite the vertical
    baseline JSON. Returns the entry count for the operator."""
    snapshot: dict = {}
    for path in sorted(INDUSTRY_DIR.rglob("*.eml")):
        snapshot.update(snapshot_path(path))
    VERTICAL_BASELINE.write_text(to_json(snapshot), encoding="utf-8")
    return len(snapshot)


def regen_stdlib() -> int:
    """Walk every .eml under lang/spec/stdlib/ and rewrite the
    stdlib baseline JSON. Returns the entry count for the operator."""
    snapshot: dict = {}
    for path in sorted(STDLIB_DIR.glob("*.eml")):
        snapshot.update(snapshot_path(path))
    STDLIB_BASELINE.write_text(to_json(snapshot), encoding="utf-8")
    return len(snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate benchmark baseline JSONs.",
    )
    parser.add_argument(
        "--stdlib",
        action="store_true",
        help="Regenerate the stdlib baseline instead of the vertical one.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Regenerate both baselines.",
    )
    args = parser.parse_args()

    if args.all:
        v = regen_vertical()
        s = regen_stdlib()
        print(f"  vertical_baseline.json: {v} entries")
        print(f"  stdlib_baseline.json:   {s} entries")
    elif args.stdlib:
        s = regen_stdlib()
        print(f"  stdlib_baseline.json: {s} entries")
    else:
        v = regen_vertical()
        print(f"  vertical_baseline.json: {v} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
