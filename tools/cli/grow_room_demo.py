"""Demo loop — publish a ZK proof every N seconds.

Mirrors the Phase 2 spec line: "First deployment: grow room
publishes VPD computation proofs every 10 seconds." Picks a function
out of an .eml source, samples random inputs, produces a stub ZK
proof, and POSTs it to the verification network.

Usage:

    python tools/cli/grow_room_demo.py examples/sigmoid.eml \\
        --fn sigmoid --interval 10 --count 6 \\
        --registry-url http://localhost:3010/api/proof \\
        --publisher grow-room-controller-01

Stops after `--count` publishes (or run with `--count -1` for an
infinite stream). Prints the proof's tree-size + module hash for
each publish so you can watch the log grow in real time.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="grow_room_demo",
        description=(
            "Publish a ZK proof for one EML function on a fresh "
            "input vector every N seconds."
        ),
    )
    parser.add_argument("source", type=Path,
                        help="An .eml source file.")
    parser.add_argument("--fn", required=True,
                        help="Function name to repeatedly prove.")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="Seconds between publishes (default 10).")
    parser.add_argument("--count", type=int, default=6,
                        help="How many publishes total. -1 → infinite. "
                             "Default 6.")
    parser.add_argument(
        "--registry-url",
        default="http://localhost:3010/api/proof",
        help="POST endpoint (default localhost).",
    )
    parser.add_argument(
        "--publisher", default="grow-room-controller-01",
        help="Publisher tag to attach to each entry.",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="RNG seed for reproducible input vectors.",
    )
    args = parser.parse_args(argv)

    if args.seed is not None:
        random.seed(args.seed)

    from lang.fingerprint import fingerprint_module
    from lang.parser import parse_file
    from lang.profiler import Profiler
    from lang.zkproof import (
        CircuitCompileError,
        compile_circuit,
        prove,
    )

    if not args.source.is_file():
        print(f"error: {args.source} not found", file=sys.stderr)
        return 1

    mod = parse_file(args.source)
    Profiler().profile_module(mod)
    fp = fingerprint_module(mod)
    fn_obj = next((f for f in mod.functions if f.name == args.fn), None)
    if fn_obj is None:
        print(f"error: function `{args.fn}` not found", file=sys.stderr)
        return 1
    try:
        circuit = compile_circuit(fn_obj)
    except CircuitCompileError as e:
        print(f"error: circuit lowering failed: {e}", file=sys.stderr)
        return 1

    print(
        f"grow_room_demo: publishing {args.fn} every {args.interval}s "
        f"to {args.registry_url}",
        file=sys.stderr,
    )
    print(
        f"  module_hash:  {fp.module_hash}\n"
        f"  publisher:    {args.publisher}\n"
        f"  parameters:   {circuit.parameters}",
        file=sys.stderr,
    )

    n = 0
    while args.count == -1 or n < args.count:
        n += 1
        inputs = {p: round(random.uniform(-3.0, 3.0), 6)
                  for p in circuit.parameters}
        proof = prove(circuit, inputs=inputs,
                      fingerprint_module_hash=fp.module_hash)
        body = json.dumps({
            "proof":     json.loads(proof.to_json(indent=None)),
            "publisher": args.publisher,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                args.registry_url, data=body, method="POST",
                headers={"content-type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            entry = payload.get("entry", {})
            leaf_hash = entry.get("leaf_hash") or "(pre-Phase-2 entry)"
            print(
                f"  [{n:>3}] id={entry.get('id'):>4}  "
                f"out={proof.output:.6f}  leaf={leaf_hash[:30]}…",
                file=sys.stderr,
            )
        except urllib.error.HTTPError as e:
            print(f"  [{n}] HTTP {e.code} {e.reason}", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"  [{n}] connection error: {e.reason}", file=sys.stderr)
            return 2

        if args.count != -1 and n >= args.count:
            break
        time.sleep(args.interval)

    print(f"\ndone; published {n} proof(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
