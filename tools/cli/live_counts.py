"""live_counts -- emit forge-related canonical numbers as JSON.

Single source of truth for site CONSTANTS objects on
monogateforge.com / machlib.org. Computes counts live where cheap;
slow-cached values (pytest collect, lake build) read from a JSON
cache and refresh under --slow.

Usage:
    python tools/cli/live_counts.py            # JSON to stdout (cached)
    python tools/cli/live_counts.py --slow     # refresh pytest + lake build
    python tools/cli/live_counts.py --field tests
    python tools/cli/live_counts.py --pretty   # multi-line JSON

Schema (every key always present; slow-cache misses surface as null):

    {
      "backends":                  int,
      "tests":                     int | null,
      "eml_files":                 int,
      "verticals":                 int,
      "theorems":                  int,
      "patents":                   int,
      "expressions":               int | null,
      "machlib_records":           int | null,
      "machlib_foundation_lines":  int | null,
      "machlib_build_seconds":     float | null
    }

Cache lives at tools/cli/.live_counts_cache.json (24h TTL). Repo
roots are discovered relative to this file -- no hard-coded D:/
paths in the derivation logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
from pathlib import Path

FORGE_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = FORGE_ROOT.parent
MACHLIB_ROOT = WORKSPACE_ROOT / "machlib"
RESEARCH_ROOT = WORKSPACE_ROOT / "monogate-research"
PATENTS_DIR = WORKSPACE_ROOT / "monogate" / "monogate-research" / "ip" / "patents"

CACHE_PATH = FORGE_ROOT / "tools" / "cli" / ".live_counts_cache.json"
CACHE_TTL_SECONDS = 24 * 3600

# Builder_v2 (monogate-research) maintains its own slow-counts cache
# and refreshes `forge_test_count` whenever `summary --slow` runs.
# Reading it here keeps the two tools in sync without a duplicate
# 7-second pytest collect.
SHARED_CACHE_PATH = (
    RESEARCH_ROOT / "tools" / "graph" / "output" / "slow_counts_cache.json"
)
SHARED_CACHE_KEYS = {"tests": "forge_test_count"}

SCHEMA_KEYS = (
    "backends",
    "tests",
    "eml_files",
    "verticals",
    "theorems",
    "patents",
    "expressions",
    "machlib_records",
    "machlib_foundation_lines",
    "machlib_build_seconds",
)


def _load_cache() -> dict:
    if not CACHE_PATH.is_file():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, indent=2), encoding="utf-8",
        )
    except OSError:
        pass


def _cache_fresh(entry: dict | None) -> bool:
    if not isinstance(entry, dict) or "value" not in entry:
        return False
    age = time.time() - entry.get("computed_at", 0)
    return age <= CACHE_TTL_SECONDS


def count_backends() -> int:
    """Canonical backend modules under software/ + hardware/."""
    n = 0
    for sub in (
        FORGE_ROOT / "software" / "backends",
        FORGE_ROOT / "hardware" / "hdl_gen",
    ):
        if sub.is_dir():
            n += sum(
                1 for p in sub.glob("*_backend.py")
                if p.is_file() and not p.name.startswith("test_")
            )
    verif = FORGE_ROOT / "software" / "verification"
    if verif.is_dir():
        for prover in verif.iterdir():
            if not prover.is_dir():
                continue
            for p in prover.glob("*.py"):
                name = p.name.lower()
                if name.startswith("test_") or name == "__init__.py":
                    continue
                if name.endswith("backend.py"):
                    n += 1
    return n


def count_eml_files() -> int:
    industries = FORGE_ROOT / "industries"
    if not industries.is_dir():
        return 0
    return sum(1 for _ in industries.rglob("*.eml"))


def count_verticals() -> int:
    industries = FORGE_ROOT / "industries"
    if not industries.is_dir():
        return 0
    return sum(
        1 for p in industries.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


_LEAN_BLOCK_COMMENT = re.compile(r"/-.*?-/", re.DOTALL)
_LEAN_LINE_COMMENT = re.compile(r"--[^\n]*")


def count_forge_theorems() -> int:
    """theorems + lemmas in forge-emitted .lean files (exclude .lake)."""
    total = 0
    for p in FORGE_ROOT.rglob("*.lean"):
        if ".lake" in p.parts:
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        src = _LEAN_BLOCK_COMMENT.sub("", src)
        src = _LEAN_LINE_COMMENT.sub("", src)
        total += len(re.findall(r"\btheorem\s+\w+", src))
        total += len(re.findall(r"\blemma\s+\w+", src))
    return total


def count_patents() -> int:
    if not PATENTS_DIR.is_dir():
        return 0
    return sum(
        1 for p in PATENTS_DIR.glob("patent-*.txt") if p.is_file()
    )


def count_expressions() -> int | None:
    """Rows in the latest exploration/master_corpus_*.csv."""
    exploration = RESEARCH_ROOT / "exploration"
    if not exploration.is_dir():
        return None
    files = sorted(exploration.rglob("master_corpus_*.csv"), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None
            return sum(1 for _ in reader)
    except OSError:
        return None


def count_machlib_records() -> int | None:
    corpus = MACHLIB_ROOT / "corpus"
    if not corpus.is_dir():
        return None
    return sum(1 for _ in corpus.rglob("*.json"))


def count_machlib_foundation_lines() -> int | None:
    """Non-`.lake` MachLib/*.lean line total (excluding Test.lean).

    Matches `wc -l` semantics so the headline number on machlib.org
    is what a human pasting `wc -l MachLib/*.lean` would see.
    """
    foundations = MACHLIB_ROOT / "foundations" / "MachLib"
    if not foundations.is_dir():
        return None
    total = 0
    for p in sorted(foundations.rglob("*.lean")):
        if not p.is_file():
            continue
        if ".lake" in p.parts or p.name == "Test.lean":
            continue
        try:
            total += len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
    return total


def measure_pytest_count() -> int | None:
    """Run `pytest --collect-only -q` from the forge root."""
    try:
        proc = subprocess.run(
            ["python", "-m", "pytest", "--collect-only", "-q"],
            cwd=FORGE_ROOT, capture_output=True, text=True,
            timeout=180, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    m = re.search(r"\b(\d+)\s+tests?\s+collected\b", output)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _resolve_lake_exe() -> str | None:
    """Locate the `lake` binary, preferring an elan toolchain install.

    On Windows, lake is typically at ``~/.elan/bin/lake.exe`` rather
    than on PATH for non-interactive subshells. Falling back to the
    bare name lets a custom PATH still work.
    """
    elan = Path.home() / ".elan" / "bin"
    for name in ("lake.exe", "lake"):
        candidate = elan / name
        if candidate.is_file():
            return str(candidate)
    return "lake"  # let subprocess raise if PATH can't find it


def measure_machlib_build_seconds() -> float | None:
    """Time a clean `lake build` of MachLib foundations.

    Destructive: removes .lake first to measure the cold-build claim.
    Caller must opt in via --slow.
    """
    foundations = MACHLIB_ROOT / "foundations"
    if not foundations.is_dir():
        return None
    lake_dir = foundations / ".lake"
    if lake_dir.is_dir():
        # rmtree falls back gracefully if a sub-process holds a handle.
        import shutil
        try:
            shutil.rmtree(lake_dir)
        except OSError:
            return None
    lake_exe = _resolve_lake_exe()
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [lake_exe, "build"], cwd=foundations,
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return round(time.perf_counter() - started, 2)


def derive_counts(refresh_slow: bool = False) -> dict:
    cache = _load_cache()

    out: dict = {}
    out["backends"] = count_backends()
    out["eml_files"] = count_eml_files()
    out["verticals"] = count_verticals()
    out["theorems"] = count_forge_theorems()
    out["patents"] = count_patents()
    out["expressions"] = count_expressions()
    out["machlib_records"] = count_machlib_records()
    out["machlib_foundation_lines"] = count_machlib_foundation_lines()

    # ── Slow values: cache-aware ──────────────────────────────
    out["tests"] = _resolve_slow(
        cache, "tests", measure_pytest_count, refresh_slow,
    )
    out["machlib_build_seconds"] = _resolve_slow(
        cache, "machlib_build_seconds",
        measure_machlib_build_seconds, refresh_slow,
    )

    if refresh_slow:
        _save_cache(cache)

    # Fixed key ordering (matches SCHEMA_KEYS) so the JSON diff is
    # readable when checked into a site repo.
    return {k: out.get(k) for k in SCHEMA_KEYS}


def _read_shared_cache_entry(key: str) -> dict | None:
    shared_key = SHARED_CACHE_KEYS.get(key)
    if not shared_key or not SHARED_CACHE_PATH.is_file():
        return None
    try:
        data = json.loads(SHARED_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    entry = data.get(shared_key)
    return entry if isinstance(entry, dict) else None


def _resolve_slow(cache: dict, key: str, fn, refresh: bool):
    entry = cache.get(key)
    if refresh:
        fresh = fn()
        if fresh is not None:
            cache[key] = {"value": fresh, "computed_at": time.time()}
            return fresh
        # measurement failed; fall through to cached value if any
    if _cache_fresh(entry):
        return entry["value"]
    shared = _read_shared_cache_entry(key)
    if _cache_fresh(shared):
        return shared["value"]
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="live_counts",
        description="Emit forge-related canonical numbers as JSON.",
    )
    p.add_argument(
        "--slow", action="store_true",
        help="refresh slow-cached values (pytest collect + lake build)",
    )
    p.add_argument(
        "--pretty", action="store_true",
        help="multi-line JSON (default: compact one-line)",
    )
    p.add_argument(
        "--field",
        help="emit one field's value as a bare line (e.g. --field tests)",
    )
    args = p.parse_args(argv)

    counts = derive_counts(refresh_slow=args.slow)

    if args.field:
        if args.field not in counts:
            print(
                f"unknown field: {args.field!r} "
                f"(known: {', '.join(SCHEMA_KEYS)})",
                file=sys.stderr,
            )
            return 2
        value = counts[args.field]
        print("" if value is None else value)
        return 0

    if args.pretty:
        print(json.dumps(counts, indent=2))
    else:
        print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
