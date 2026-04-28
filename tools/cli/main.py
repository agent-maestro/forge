"""eml-compile -- the Forge CLI.

Status: SCAFFOLD. Subcommand handlers are stubs; real
implementations land as the corresponding backends mature
(see roadmap/phases/).

    eml-compile <file.eml> --profile-only
    eml-compile <file.eml> --target c|rust|python|llvm|wasm|verilog|vhdl|chisel
    eml-compile <file.eml> --verify
    eml-compile <file.eml> --fpga-sim
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eml-compile",
        description="Monogate Forge -- the EML-lang compiler",
    )
    parser.add_argument("source", type=Path, nargs="?",
                        help="Path to a .eml source file")
    parser.add_argument("--target", choices=[
        "c", "rust", "python", "llvm", "wasm",
        "verilog", "vhdl", "chisel", "lean",
    ], help="Output target")
    parser.add_argument("-o", "--output", type=Path,
                        help="Output file (defaults to stdout)")
    parser.add_argument("--profile-only", action="store_true",
                        help="Print Pfaffian profile and exit")
    parser.add_argument("--verify", action="store_true",
                        help="Emit Lean / SMT / CBMC verification artifacts")
    parser.add_argument("--fpga-sim", action="store_true",
                        help="After emitting Verilog, run Verilator simulation")
    parser.add_argument("--version", action="version",
                        version="eml-compile 0.0.1 (SCAFFOLD)")
    args = parser.parse_args(argv)

    if not args.source:
        parser.print_help()
        return 0

    if not args.source.is_file():
        print(f"error: source file not found: {args.source}", file=sys.stderr)
        return 1

    print("eml-compile: SCAFFOLD -- backends not yet implemented",
          file=sys.stderr)
    print(f"  source:       {args.source}", file=sys.stderr)
    print(f"  target:       {args.target or '(none specified)'}",
          file=sys.stderr)
    print(f"  profile-only: {args.profile_only}", file=sys.stderr)
    print(f"  verify:       {args.verify}", file=sys.stderr)
    print(f"  fpga-sim:     {args.fpga_sim}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
