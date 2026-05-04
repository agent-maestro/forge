"""Publish ``.fp.json`` files to a Verification Network registry.

Usage:

    python tools/cli/fingerprint_publish.py path/to/foo.eml.fp.json
    python tools/cli/fingerprint_publish.py registry/fingerprints.jsonl --bulk
    python tools/cli/fingerprint_publish.py path/to/foo.fp.json \\
        --registry-url https://api.monogate.dev/fingerprint

Bulk mode reads our own JSONL corpus dump and posts each
``record.fingerprint`` to the registry, so a fresh registry can be
pre-seeded with the canonical Forge corpus in one command.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

_DEFAULT_URL = "http://localhost:3000/api/fingerprint"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fingerprint_publish",
        description=(
            "POST one or more computation fingerprints to a "
            "Verification Network registry."
        ),
    )
    parser.add_argument("source", type=Path,
                        help="Path to a .fp.json file (single mode) or a "
                             "fingerprints.jsonl produced by "
                             "tools/cli/fingerprint_corpus.py (--bulk).")
    parser.add_argument("--bulk", action="store_true",
                        help="Treat the source as JSONL and publish "
                             "each record.")
    parser.add_argument("--registry-url", default=_DEFAULT_URL,
                        help=f"Registry endpoint (default: {_DEFAULT_URL}).")
    parser.add_argument("--publisher", default=None,
                        help="Free-form publisher tag (engineer / fleet / etc.).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't actually POST. Print what would be sent.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-file progress output.")
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"error: {args.source} not found", file=sys.stderr)
        return 1

    payloads = list(_load_payloads(args.source, bulk=args.bulk))
    if not payloads:
        print("error: nothing to publish", file=sys.stderr)
        return 1

    n_ok = 0
    n_fail = 0
    for i, fp in enumerate(payloads, 1):
        body = json.dumps({
            "fingerprint": fp,
            "publisher":   args.publisher,
        }).encode("utf-8")

        if args.dry_run:
            if not args.quiet:
                print(f"  [{i}/{len(payloads)}] DRY-RUN module_hash="
                      f"{fp.get('module_hash')}", file=sys.stderr)
            n_ok += 1
            continue

        try:
            req = urllib.request.Request(
                args.registry_url, data=body, method="POST",
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            n_ok += 1
            if not args.quiet:
                created = payload.get("created", False)
                tag = "+CREATED" if created else "·UPDATED"
                print(f"  [{i}/{len(payloads)}] {tag} "
                      f"{fp.get('module_hash')}", file=sys.stderr)
        except urllib.error.HTTPError as e:
            n_fail += 1
            print(f"  [{i}/{len(payloads)}] HTTP {e.code} {e.reason} "
                  f"({fp.get('module_hash')})", file=sys.stderr)
            try:
                err_body = e.read().decode("utf-8")
                print(f"    {err_body[:200]}", file=sys.stderr)
            except Exception:
                pass
        except urllib.error.URLError as e:
            n_fail += 1
            print(f"  [{i}/{len(payloads)}] connection error: {e.reason}",
                  file=sys.stderr)
            return 2     # whole batch will fail the same way; bail early

    print(f"\npublished {n_ok} fingerprint(s), {n_fail} failed",
          file=sys.stderr)
    return 0 if n_fail == 0 else 2


def _load_payloads(src: Path, *, bulk: bool):
    text = src.read_text(encoding="utf-8")
    if bulk:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            fp = record.get("fingerprint")
            if fp is not None:
                yield fp
    else:
        yield json.loads(text)


if __name__ == "__main__":
    raise SystemExit(main())
