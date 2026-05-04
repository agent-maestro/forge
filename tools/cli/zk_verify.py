"""Verify a ZK proof against the original .eml source.

Usage:

    python tools/cli/zk_verify.py sigmoid_proof.json examples/sigmoid.eml

Re-compiles the function out of the .eml source, recomputes its
fingerprint, then independently re-executes the circuit on the
proof's public inputs. Exits 0 only if every check passes (circuit
hash, fingerprint hash, output value, transcript hash).
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
        prog="zk_verify",
        description=(
            "Verify a ZK proof against the source it claims to come from."
        ),
    )
    parser.add_argument("proof",  type=Path, help="The ZK proof JSON.")
    parser.add_argument("source", type=Path, help="The .eml source file.")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only PASS / FAIL.")
    args = parser.parse_args(argv)

    if not args.proof.is_file() or not args.source.is_file():
        print("error: proof or source not found", file=sys.stderr)
        return 1

    proof_dict = json.loads(args.proof.read_text(encoding="utf-8"))

    from lang.fingerprint import fingerprint_module
    from lang.parser import parse_file
    from lang.profiler import Profiler
    from lang.zkproof import (
        CircuitCompileError,
        ZkProof,
        compile_circuit,
        verify as zk_verify,
    )

    mod = parse_file(args.source)
    Profiler().profile_module(mod)
    fp = fingerprint_module(mod)

    target_name = proof_dict.get("function_name", "")
    fn_obj = next((f for f in mod.functions if f.name == target_name), None)
    if fn_obj is None:
        print(f"FAIL — function `{target_name}` not found in {args.source}")
        return 1

    try:
        circuit = compile_circuit(fn_obj)
    except CircuitCompileError as exc:
        print(f"FAIL — circuit re-lowering of `{target_name}` failed: {exc}")
        return 1

    proof = ZkProof(
        spec=proof_dict.get("spec", ""),
        circuit_hash=proof_dict.get("circuit_hash", ""),
        fingerprint_module_hash=proof_dict.get("fingerprint_module_hash", ""),
        function_name=target_name,
        public_inputs=dict(proof_dict.get("public_inputs", {})),
        output=proof_dict.get("output"),
        transcript_hash=proof_dict.get("transcript_hash", ""),
        chain_order=proof_dict.get("chain_order", 0),
        n_gates=proof_dict.get("n_gates", 0),
    )

    result = zk_verify(
        proof,
        circuit=circuit,
        fingerprint_module_hash=fp.module_hash,
    )

    if result.is_valid:
        if not args.quiet:
            print(
                f"PASS — {target_name}\n"
                f"  module_hash:  {fp.module_hash}\n"
                f"  circuit_hash: {proof.circuit_hash}\n"
                f"  output:       {proof.output}\n"
                f"  inputs:       {proof.public_inputs}",
            )
        else:
            print("PASS")
        return 0
    print(f"FAIL — {target_name}: {result.reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
