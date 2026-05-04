"""Produce a ZK proof for one EML function on a single input vector.

Usage:

    python tools/cli/zk_prove.py examples/sigmoid.eml --fn sigmoid \\
        --input x=1.5

    python tools/cli/zk_prove.py examples/gaussian.eml --fn gaussian \\
        --input x=1.0 --input mu=0.0 --input sigma=1.0 \\
        -o sigmoid_proof.json

This is the Phase 1 round-trip primitive — feed in a function +
inputs, get back a JSON proof artefact bound to the source's
fingerprint. Pair with ``zk_verify.py`` for the consumer side.

Today's prover is the transparent stub from ``lang/zkproof/prover.py``
— it re-executes the circuit and binds the trace to the fingerprint
with SHA-256. When the real PLONK prover lands, the only change to
this script is the import.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="zk_prove",
        description=(
            "Produce a ZK proof (Phase 1 stub) for a function in an "
            ".eml source file, bound to that source's computation "
            "fingerprint."
        ),
    )
    parser.add_argument("source", type=Path, help="Path to an .eml file.")
    parser.add_argument("--fn", required=True,
                        help="Function name to prove. Must be a scalar fn.")
    parser.add_argument(
        "--input", "-i", action="append", default=[],
        help="One `name=value` pair per parameter (repeatable).",
    )
    parser.add_argument("-o", "--output", type=Path,
                        help="Where to write the proof JSON (default: stdout).")
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"error: {args.source} not found", file=sys.stderr)
        return 1

    inputs = _parse_inputs(args.input)

    from lang.fingerprint import fingerprint_module
    from lang.parser import parse_file
    from lang.profiler import Profiler
    from lang.zkproof import (
        CircuitCompileError,
        compile_circuit,
        prove,
    )

    mod = parse_file(args.source)
    Profiler().profile_module(mod)

    fn_obj = next((f for f in mod.functions if f.name == args.fn), None)
    if fn_obj is None:
        print(f"error: function `{args.fn}` not found in {args.source}",
              file=sys.stderr)
        return 1

    try:
        circuit = compile_circuit(fn_obj)
    except CircuitCompileError as exc:
        print(f"error: ZK lowering rejected `{args.fn}`: {exc}",
              file=sys.stderr)
        return 1

    missing = [p for p in circuit.parameters if p not in inputs]
    if missing:
        print(f"error: missing inputs for parameters: {', '.join(missing)}",
              file=sys.stderr)
        return 1

    fp = fingerprint_module(mod)
    proof = prove(circuit, inputs=inputs,
                  fingerprint_module_hash=fp.module_hash)

    payload = proof.to_json()
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {args.output} ({len(payload)} bytes; "
              f"chain_order={proof.chain_order}, "
              f"n_gates={proof.n_gates})", file=sys.stderr)
    else:
        sys.stdout.write(payload + "\n")
    return 0


def _parse_inputs(items: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"bad --input `{item}` — expected name=value")
        k, _, v = item.partition("=")
        try:
            out[k.strip()] = float(v)
        except ValueError as e:
            raise SystemExit(f"bad input value `{v}`: {e}") from e
    return out


if __name__ == "__main__":
    raise SystemExit(main())
