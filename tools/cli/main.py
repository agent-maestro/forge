"""eml-compile -- the Forge CLI.

Parses + profiles + (optionally) compiles `.eml` source through a
chosen backend.

Phase 1 + 2.1 surface live today:

    eml-compile <file.eml>                  # parse + profile, print summary
    eml-compile <file.eml> --profile-only   # explicit; same as no --target
    eml-compile <file.eml> --target c       # emit C99 to stdout
    eml-compile <file.eml> --target c -o out.c

Targets that print "not built yet" gracefully: rust, python, llvm,
wasm, verilog, vhdl, chisel, lean. Each lands per the phase plan
in roadmap/phases/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make the repo root importable when this script is invoked directly
# (e.g. `python tools/cli/main.py ...`). When installed via pip /
# pyproject scripts entry, Python's import system handles this for us.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Reconfigure stdout/stderr to utf-8 so Unicode in source files
# (Lean characters in @verify blocks, etc.) prints cleanly on
# Windows consoles defaulting to cp1252.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# Backends that are wired today.
_LIVE_TARGETS = {"c", "rust", "lean"}

# Backends that print "not built yet" with a phase pointer.
_PLANNED_TARGETS = {
    "python":  "Phase 2.4 (eml-cost transpile reuse)",
    "llvm":    "Phase 2.3",
    "wasm":    "Phase 2.3 (via LLVM)",
    "verilog": "Phase 3.2",
    "vhdl":    "Phase 3.2",
    "chisel":  "Phase 3.2",
}


def _print_profile_summary(mod) -> None:
    """One-line profile for each function. Used when --profile-only."""
    print(f"# Module: {mod.name or '(unnamed)'}  "
          f"({len(mod.functions)} fn, "
          f"{len(mod.constants)} const, "
          f"{len(mod.types)} type)")
    print(f"# Source: {mod.source_file}")
    print()
    if not mod.functions:
        print("(no functions to profile)")
        return
    for fn in mod.functions:
        prof = fn.profile or {}
        st = prof.get("status", "?")
        co = prof.get("chain_order", "?")
        cc = prof.get("cost_class", "?")
        depth = prof.get("eml_depth", "?")
        drift = prof.get("fp16_drift_risk", "?")
        dyn = prof.get("dynamics", {})
        fp = prof.get("fpga_estimate", {})
        print(f"  {fn.name}")
        print(f"    status: {st}    chain_order: {co}    "
              f"cost_class: {cc}    eml_depth: {depth}    "
              f"drift: {drift}")
        if dyn:
            print(f"    dynamics: {dyn.get('oscillations', 0)} osc, "
                  f"{dyn.get('decays', 0)} decay  "
                  f"(predicted_r={dyn.get('predicted_r', 0)})")
        if fp:
            print(f"    fpga: {fp.get('mac_units', 0)} MAC, "
                  f"{fp.get('exp_units', 0)} exp, "
                  f"{fp.get('ln_units', 0)} ln, "
                  f"{fp.get('trig_units', 0)} trig "
                  f"({fp.get('estimated_latency_cycles', 0)} cy "
                  f"@ {fp.get('precision_bits_needed', 32)}-bit)")
        for w in prof.get("stability_warnings", []):
            print(f"    WARN: {w}")
        print()


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
                        help="Print Pfaffian profile summary and exit")
    parser.add_argument("--verify", action="store_true",
                        help="Emit Lean / SMT / CBMC verification artifacts "
                             "(Phase 2.4 required)")
    parser.add_argument("--fpga-sim", action="store_true",
                        help="After emitting Verilog, run Verilator simulation "
                             "(Phase 3.3 required)")
    parser.add_argument("--version", action="version",
                        version="eml-compile 0.1.0 (Phase 1 + 2.1)")
    args = parser.parse_args(argv)

    if not args.source:
        parser.print_help()
        return 0

    if not args.source.is_file():
        print(f"error: source file not found: {args.source}",
              file=sys.stderr)
        return 1

    # ── Parse + profile (live for any input) ──────────────────
    try:
        from lang.parser import parse_file, ParseError
        from lang.profiler import Profiler
    except ImportError as e:
        print(f"error: forge package not importable: {e}",
              file=sys.stderr)
        return 1

    try:
        mod = parse_file(args.source)
    except ParseError as e:
        print(f"parse error: {e}", file=sys.stderr)
        return 1

    profiler = Profiler()
    profiler.profile_module(mod)

    # ── No target / --profile-only -> summary ─────────────────
    if not args.target or args.profile_only:
        _print_profile_summary(mod)
        return 0

    # ── Live targets ──────────────────────────────────────────
    if args.target == "c":
        from software.backends.c_backend import CBackend, CompileError
        try:
            c_source = CBackend().compile(mod)
        except CompileError as e:
            print(f"compile error (c backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(c_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(c_source)} bytes, {c_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(c_source, end="")
        return 0

    if args.target == "rust":
        from software.backends.rust_backend import RustBackend
        from software.backends.rust_backend import (
            CompileError as RustCompileError,
        )
        try:
            rust_source = RustBackend().compile(mod)
        except RustCompileError as e:
            print(f"compile error (rust backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(rust_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(rust_source)} bytes, "
                  f"{rust_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(rust_source, end="")
        return 0

    if args.target == "lean":
        from software.verification.lean.LeanBackend import LeanBackend
        lean_source = LeanBackend().compile_module(mod)
        if not lean_source:
            print(f"lean backend: no `@verify(lean, ...)` blocks "
                  f"found in {args.source} -- nothing to emit",
                  file=sys.stderr)
            return 0
        if args.output:
            args.output.write_text(lean_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(lean_source)} bytes, "
                  f"{lean_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(lean_source, end="")
        return 0

    # ── Planned-but-not-built targets ─────────────────────────
    if args.target in _PLANNED_TARGETS:
        phase = _PLANNED_TARGETS[args.target]
        print(f"eml-compile: target {args.target!r} not built yet "
              f"-- {phase} required", file=sys.stderr)
        print(f"  source parsed + profiled OK ({len(mod.functions)} fn).",
              file=sys.stderr)
        print(f"  Run with --profile-only to see the analysis.",
              file=sys.stderr)
        return 2

    # Unreachable given argparse choices.
    print(f"error: unknown target {args.target!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
