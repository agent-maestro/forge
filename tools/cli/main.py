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
_LIVE_TARGETS = {"c", "rust", "lean", "verilog"}

# Backends that print "not built yet" with a phase pointer.
_PLANNED_TARGETS = {
    "python":  "Phase 2.4 (eml-cost transpile reuse)",
    "llvm":    "Phase 2.3",
    "wasm":    "Phase 2.3 (via LLVM)",
    "vhdl":    "Phase 3.2 (Verilog already shipped; VHDL is a syntax port)",
    "chisel":  "Phase 3.2 (Verilog already shipped; Chisel is FIRRTL emit)",
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
        "all",
    ], help=("Output target. 'all' runs every live backend "
            "(c, rust, lean, verilog) and writes <stem>.<ext> "
            "files alongside the source (or into --output if it's "
            "a directory)."))
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
    parser.add_argument("--allocate", action="store_true",
                        help="Run the FPGA resource allocator (Patent #14) "
                             "and print the allocation plan. Requires at "
                             "least one @target(fpga, ...) function.")
    parser.add_argument("--fpga-target", default="xilinx.artix7",
                        help="FPGA target (e.g. xilinx.artix7). "
                             "Default: xilinx.artix7.")
    parser.add_argument("--fmt", action="store_true",
                        help="Print canonically-formatted source to "
                             "stdout (eml-fmt). Use with --write to "
                             "rewrite the file in place.")
    parser.add_argument("--write", action="store_true",
                        help="When used with --fmt, rewrite the source "
                             "file in place if formatting changed it.")
    parser.add_argument("--check", action="store_true",
                        help="When used with --fmt, exit 1 if the file "
                             "is not in canonical form (CI gate).")
    parser.add_argument("--no-optimize", action="store_true",
                        help="Disable the optimizer pass sequence "
                             "(constant folding + CSE + SuperBEST). "
                             "Useful when comparing optimized vs "
                             "unoptimized output.")
    parser.add_argument("--explain", action="store_true",
                        help="Print a per-function diff showing which "
                             "optimizer passes fired, before/after "
                             "node counts, SuperBEST family + digits "
                             "saved, and CSE bindings introduced. "
                             "Doesn't emit any backend code.")
    parser.add_argument("--backend-stats", action="store_true",
                        help="When used with --explain, also compile "
                             "to every backend and report per-target "
                             "emitted-source size (LOC, chars, "
                             "Verilog module count).")
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

    # ── --fmt -> canonical formatter (no profile needed) ──────
    if args.fmt:
        from tools.fmt import format_file
        original = args.source.read_text(encoding="utf-8")
        try:
            formatted = format_file(args.source)
        except Exception as e:
            print(f"format error: {e}", file=sys.stderr)
            return 1
        if args.check:
            if original != formatted:
                print(
                    f"error: {args.source} is not formatted "
                    f"(run with --fmt --write to fix)",
                    file=sys.stderr,
                )
                return 1
            return 0
        if args.write:
            if original != formatted:
                args.source.write_text(formatted, encoding="utf-8")
            return 0
        sys.stdout.write(formatted)
        return 0

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

    # ── --explain -> per-function optimizer diff ─────────────
    if args.explain:
        from tools.cli.explain import print_explain_report
        print_explain_report(
            mod, include_backend_stats=args.backend_stats,
        )
        return 0

    # ── --allocate -> run FPGA allocator + print plan ──────────
    if args.allocate:
        from hardware.allocator import FPGAAllocator, CompileError as AllocErr
        try:
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )
        except AllocErr as e:
            print(f"allocator error: {e}", file=sys.stderr)
            return 1
        print(plan.render())
        return 0

    # ── No target / --profile-only -> summary ─────────────────
    if not args.target or args.profile_only:
        _print_profile_summary(mod)
        return 0

    # ── --target all -> run every live backend ────────────────
    if args.target == "all":
        out_dir = args.output if args.output else args.source.parent
        if out_dir.exists() and not out_dir.is_dir() and args.output:
            print(f"error: --output must be a directory when "
                  f"--target=all (got file: {out_dir})", file=sys.stderr)
            return 1
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = args.source.stem
        results: list[tuple[str, Path, int]] = []  # (target, path, bytes)

        # C
        from software.backends.c_backend import CBackend
        c_path = out_dir / f"{stem}.c"
        c_src = CBackend(optimize=not args.no_optimize).compile(mod)
        c_path.write_text(c_src, encoding="utf-8")
        results.append(("c", c_path, len(c_src)))

        # Rust
        from software.backends.rust_backend import RustBackend
        rs_path = out_dir / f"{stem}.rs"
        rs_src = RustBackend(optimize=not args.no_optimize).compile(mod)
        rs_path.write_text(rs_src, encoding="utf-8")
        results.append(("rust", rs_path, len(rs_src)))

        # Lean (only if any @verify(lean) blocks)
        from software.verification.lean.LeanBackend import LeanBackend
        lean_src = LeanBackend(optimize=not args.no_optimize).compile_module(mod)
        if lean_src:
            lean_path = out_dir / f"{stem}.lean"
            lean_path.write_text(lean_src, encoding="utf-8")
            results.append(("lean", lean_path, len(lean_src)))

        # Verilog (only if any @target(fpga) functions)
        try:
            from hardware.allocator import FPGAAllocator
            from hardware.hdl_gen.verilog_backend import VerilogBackend
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )
            v_src = VerilogBackend(optimize=not args.no_optimize).compile(mod, plan)
            v_path = out_dir / f"{stem}.v"
            v_path.write_text(v_src, encoding="utf-8")
            results.append(("verilog", v_path, len(v_src)))
        except Exception as e:  # noqa: BLE001 -- best-effort
            results.append(("verilog", Path("<skipped>"), 0))
            print(f"  verilog skipped: {e}", file=sys.stderr)

        print(f"# eml-compile --target all -> {out_dir}")
        for target, path, nbytes in results:
            if path.name == "<skipped>":
                print(f"  [skip] {target}")
            else:
                print(f"  [ok]   {target:8s} {path}  ({nbytes:,} bytes)")
        return 0

    # ── Live targets ──────────────────────────────────────────
    if args.target == "c":
        from software.backends.c_backend import CBackend, CompileError
        try:
            c_source = CBackend(optimize=not args.no_optimize).compile(mod)
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
            rust_source = RustBackend(optimize=not args.no_optimize).compile(mod)
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

    if args.target == "verilog":
        from hardware.allocator import FPGAAllocator
        from hardware.allocator import CompileError as AllocErr
        from hardware.hdl_gen.verilog_backend import (
            VerilogBackend,
            CompileError as VerilogErr,
        )
        try:
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )
            verilog_source = VerilogBackend(optimize=not args.no_optimize).compile(mod, plan)
        except (AllocErr, VerilogErr) as e:
            print(f"compile error (verilog backend): {e}",
                  file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(verilog_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(verilog_source)} bytes, "
                  f"{verilog_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(verilog_source, end="")
        return 0

    if args.target == "lean":
        from software.verification.lean.LeanBackend import LeanBackend
        lean_source = LeanBackend(optimize=not args.no_optimize).compile_module(mod)
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
