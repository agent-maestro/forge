"""Bulk-fingerprint every ``.eml`` source in the Forge tree.

Usage:

    python tools/cli/fingerprint_corpus.py
    python tools/cli/fingerprint_corpus.py --root examples
    python tools/cli/fingerprint_corpus.py --out registry/fingerprints.jsonl

Walks the configured roots, parses + profiles each ``.eml`` file,
computes its fingerprint, and writes one JSONL line per file to the
registry path. Files that fail to parse are reported on stderr with
a non-zero exit code, but the rest of the corpus is still processed.

This is the Phase 0 deliverable from the Verification Network spec:
"All 217+ corpus kernels get fingerprints computed and stored."
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Make the repo root importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


_DEFAULT_ROOTS = (
    "examples",
    "industries",
    "hardware",
    "software",
    "lang/spec",
    "stdlib",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fingerprint_corpus",
        description=(
            "Compute and store the computation fingerprint for every "
            ".eml file in the Forge tree. Outputs JSONL — one record "
            "per file — at `--out` (default registry/fingerprints.jsonl)."
        ),
    )
    parser.add_argument(
        "--root", action="append", type=Path, default=None,
        help=(
            "Repeatable. Walk these subtrees instead of the defaults "
            "({}). Paths are interpreted relative to the Forge repo "
            "root.".format(", ".join(_DEFAULT_ROOTS))
        ),
    )
    parser.add_argument(
        "--out", type=Path,
        default=_REPO_ROOT / "registry" / "fingerprints.jsonl",
        help="Output JSONL path (default: registry/fingerprints.jsonl).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Stop after fingerprinting this many files (debugging).",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Don't print per-file progress to stderr.",
    )
    args = parser.parse_args(argv)

    roots = args.root or [_REPO_ROOT / r for r in _DEFAULT_ROOTS]
    eml_files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        eml_files.extend(sorted(root.rglob("*.eml")))
    if args.limit is not None:
        eml_files = eml_files[: args.limit]

    if not eml_files:
        print("error: no .eml files found under any root.", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)

    from lang.fingerprint import fingerprint_module
    from lang.parser import ParseError, parse_file
    from lang.profiler import Profiler

    profiler = Profiler()
    n_ok = 0
    n_fail = 0
    started = time.monotonic()

    with args.out.open("w", encoding="utf-8") as f:
        for i, src in enumerate(eml_files, 1):
            rel = src.relative_to(_REPO_ROOT) if src.is_relative_to(_REPO_ROOT) else src
            try:
                mod = parse_file(src)
            except (ParseError, FileNotFoundError, UnicodeDecodeError) as e:
                n_fail += 1
                if not args.quiet:
                    print(f"  SKIP {rel}: {e}", file=sys.stderr)
                continue
            except Exception as e:  # noqa: BLE001 — parser may raise unexpected
                n_fail += 1
                if not args.quiet:
                    print(f"  SKIP {rel}: {type(e).__name__}: {e}",
                          file=sys.stderr)
                continue

            try:
                profiler.profile_module(mod)
            except Exception as e:  # noqa: BLE001
                # Still record the fingerprint without the profile —
                # tamper-evidence doesn't depend on the profile being
                # populated.
                if not args.quiet:
                    print(f"  warn {rel}: profile failed ({e})",
                          file=sys.stderr)

            fp = fingerprint_module(mod)
            record = {
                "path":         str(rel).replace("\\", "/"),
                "module":       fp.module["name"],
                "module_hash":  fp.module_hash,
                "n_functions":  len(fp.functions),
                "spec":         fp.spec,
                "version":      fp.version,
                "fingerprint":  json.loads(fp.to_json(indent=None)),
            }
            f.write(json.dumps(record, sort_keys=True) + "\n")
            n_ok += 1
            if not args.quiet and (i % 50 == 0 or i == len(eml_files)):
                print(f"  ... {i}/{len(eml_files)}", file=sys.stderr)

    elapsed = time.monotonic() - started
    print(
        f"\nfingerprinted {n_ok} module(s), {n_fail} skipped, "
        f"in {elapsed:.2f}s -> {args.out}",
        file=sys.stderr,
    )
    return 0 if n_fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
