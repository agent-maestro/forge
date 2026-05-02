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
_LIVE_TARGETS = {
    "c", "rust", "python", "llvm", "wasm",
    "verilog", "vhdl", "chisel", "lean",
}

# Backends that print "not built yet" with a phase pointer. Empty
# now -- every target the parser accepts is wired.
_PLANNED_TARGETS: dict[str, str] = {}


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
    if argv is None:
        argv = sys.argv[1:]

    # Handle subcommands that take their own argv. These must go
    # through their own parser rather than the file-oriented one
    # below.
    if argv and argv[0] == "init":
        from tools.cli.init_cmd import main as init_main
        return init_main(argv[1:])
    if argv and argv[0] in ("manpage", "--manpage"):
        from tools.cli.manpage import emit_manpage
        sys.stdout.write(emit_manpage())
        return 0

    parser = argparse.ArgumentParser(
        prog="eml-compile",
        description=(
            "Monogate Forge -- the EML-lang compiler. "
            "Run `eml-compile init <dir>` to scaffold a new project; "
            "`eml-compile manpage` to print the man page."
        ),
    )
    parser.add_argument("source", type=Path, nargs="?",
                        help="Path to a .eml source file")
    parser.add_argument("--target", choices=[
        "c", "cpp", "rust", "python", "llvm", "wasm",
        "verilog", "systemverilog", "vhdl", "chisel", "lean",
        "ada", "matlab",
        "coq", "isabelle", "ros2",
        "java", "kotlin", "go", "autosar", "aadl",
        "solidity",
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
    parser.add_argument("--json", action="store_true",
                        help="When used with --explain, emit a stable "
                             "JSON shape instead of human-readable "
                             "text. Recommended for CI dashboards "
                             "and agents.")
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

    # ── Resolve license (open core; missing license = Free tier) ──
    try:
        from tools.license import load_license, target_allowed
        license_ = load_license()
    except Exception as e:
        print(f"license error: {e}", file=sys.stderr)
        return 2
    tier_label = "Pro" if (license_ and license_.tier == "pro") else "Free"

    # Single-target dispatch is gated here. --target all is gated
    # per-iteration in the loop below so a Free user gets Free
    # backends emitted and a one-line skip notice for Pro ones.
    if args.target and args.target != "all" and not target_allowed(
        args.target, license_,
    ):
        print(
            f"error: --target {args.target} requires a Pro license "
            f"(current tier: {tier_label}).\n"
            f"  Get Pro at https://monogateforge.com/get-started",
            file=sys.stderr,
        )
        return 2

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
            mod,
            include_backend_stats=args.backend_stats,
            as_json=args.json,
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

        # Per-iteration license gate. Pro backends short-circuit
        # by raising _ProTierRequired, which is caught explicitly
        # before each block's generic `except Exception` so the
        # skip lands in `skipped_pro` instead of being mis-labeled
        # as a runtime error.
        is_pro = license_ is not None and license_.tier == "pro"
        skipped_pro: list[str] = []

        class _ProTierRequired(Exception):
            pass

        # C
        from software.backends.c_backend import CBackend
        c_path = out_dir / f"{stem}.c"
        c_src = CBackend(optimize=not args.no_optimize).compile(mod)
        c_path.write_text(c_src, encoding="utf-8")
        results.append(("c", c_path, len(c_src)))

        # C++
        try:
            from software.backends.cpp_backend import CppBackend
            cpp_path = out_dir / f"{stem}.cpp"
            cpp_src = CppBackend(optimize=not args.no_optimize).compile(mod)
            cpp_path.write_text(cpp_src, encoding="utf-8")
            results.append(("cpp", cpp_path, len(cpp_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("cpp", Path("<skipped>"), 0))
            print(f"  cpp skipped: {e}", file=sys.stderr)

        # Ada / SPARK (writes .ads + .adb) — Pro tier
        try:
            if not is_pro: skipped_pro.append("ada"); raise _ProTierRequired
            from software.backends.ada_backend import AdaBackend
            ada_art = AdaBackend(optimize=not args.no_optimize).compile_full(mod)
            ads_path = out_dir / f"{stem}.ads"
            adb_path = out_dir / f"{stem}.adb"
            ads_path.write_text(ada_art.spec, encoding="utf-8")
            adb_path.write_text(ada_art.body, encoding="utf-8")
            results.append(("ada-spec", ads_path, len(ada_art.spec)))
            results.append(("ada-body", adb_path, len(ada_art.body)))
        except _ProTierRequired:
            pass  # already recorded in skipped_pro
        except Exception as e:  # noqa: BLE001
            results.append(("ada", Path("<skipped>"), 0))
            print(f"  ada skipped: {e}", file=sys.stderr)

        # MATLAB
        try:
            from software.backends.matlab_backend import MatlabBackend
            m_path = out_dir / f"{stem}.m"
            m_src = MatlabBackend(optimize=not args.no_optimize).compile(mod)
            m_path.write_text(m_src, encoding="utf-8")
            results.append(("matlab", m_path, len(m_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("matlab", Path("<skipped>"), 0))
            print(f"  matlab skipped: {e}", file=sys.stderr)

        # Coq (only if any @verify block) — Pro tier
        try:
            if not is_pro: skipped_pro.append("coq"); raise _ProTierRequired
            from software.verification.coq.coq_backend import CoqBackend
            coq_src = CoqBackend(optimize=not args.no_optimize).compile(mod)
            if coq_src:
                coq_path = out_dir / f"{stem}.v"
                coq_path.write_text(coq_src, encoding="utf-8")
                results.append(("coq", coq_path, len(coq_src)))
        except _ProTierRequired:
            pass
        except Exception as e:  # noqa: BLE001
            results.append(("coq", Path("<skipped>"), 0))
            print(f"  coq skipped: {e}", file=sys.stderr)

        # Isabelle/HOL (only if any @verify block) — Pro tier
        try:
            if not is_pro: skipped_pro.append("isabelle"); raise _ProTierRequired
            from software.verification.isabelle.isabelle_backend import (
                IsabelleBackend,
            )
            isa_src = IsabelleBackend(
                optimize=not args.no_optimize,
            ).compile(mod)
            if isa_src:
                isa_path = out_dir / f"{stem}.thy"
                isa_path.write_text(isa_src, encoding="utf-8")
                results.append(("isabelle", isa_path, len(isa_src)))
        except _ProTierRequired:
            pass
        except Exception as e:  # noqa: BLE001
            results.append(("isabelle", Path("<skipped>"), 0))
            print(f"  isabelle skipped: {e}", file=sys.stderr)

        # Java
        try:
            from software.backends.java_backend import JavaBackend
            j_path = out_dir / f"{stem.title().replace('_', '')}.java"
            j_src = JavaBackend(optimize=not args.no_optimize).compile(mod)
            j_path.write_text(j_src, encoding="utf-8")
            results.append(("java", j_path, len(j_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("java", Path("<skipped>"), 0))
            print(f"  java skipped: {e}", file=sys.stderr)

        # Kotlin
        try:
            from software.backends.kotlin_backend import KotlinBackend
            k_path = out_dir / f"{stem}.kt"
            k_src = KotlinBackend(optimize=not args.no_optimize).compile(mod)
            k_path.write_text(k_src, encoding="utf-8")
            results.append(("kotlin", k_path, len(k_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("kotlin", Path("<skipped>"), 0))
            print(f"  kotlin skipped: {e}", file=sys.stderr)

        # Go
        try:
            from software.backends.go_backend import GoBackend
            go_path = out_dir / f"{stem}.go"
            go_src = GoBackend(optimize=not args.no_optimize).compile(mod)
            go_path.write_text(go_src, encoding="utf-8")
            results.append(("go", go_path, len(go_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("go", Path("<skipped>"), 0))
            print(f"  go skipped: {e}", file=sys.stderr)

        # Solidity — Pro tier
        try:
            if not is_pro: skipped_pro.append("solidity"); raise _ProTierRequired
            from software.backends.solidity_backend import SolidityBackend
            sol_path = out_dir / f"{stem}.sol"
            sol_src = SolidityBackend(optimize=not args.no_optimize).compile(mod)
            sol_path.write_text(sol_src, encoding="utf-8")
            results.append(("solidity", sol_path, len(sol_src)))
        except _ProTierRequired:
            pass
        except Exception as e:  # noqa: BLE001
            results.append(("solidity", Path("<skipped>"), 0))
            print(f"  solidity skipped: {e}", file=sys.stderr)

        # AUTOSAR (writes .arxml + .c) — Pro tier
        try:
            if not is_pro: skipped_pro.append("autosar"); raise _ProTierRequired
            from software.backends.autosar_backend import AutosarBackend
            au = AutosarBackend(
                optimize=not args.no_optimize,
            ).compile_full(mod)
            arxml_path = out_dir / f"{stem}.arxml"
            au_c_path = out_dir / f"{stem}.autosar.c"
            arxml_path.write_text(au.arxml, encoding="utf-8")
            au_c_path.write_text(au.c_source, encoding="utf-8")
            results.append(("autosar-arxml", arxml_path, len(au.arxml)))
            results.append(("autosar-c", au_c_path, len(au.c_source)))
        except _ProTierRequired:
            pass
        except Exception as e:  # noqa: BLE001
            results.append(("autosar", Path("<skipped>"), 0))
            print(f"  autosar skipped: {e}", file=sys.stderr)

        # AADL — Pro tier
        try:
            if not is_pro: skipped_pro.append("aadl"); raise _ProTierRequired
            from software.backends.aadl_backend import AadlBackend
            aadl_path = out_dir / f"{stem}.aadl"
            aadl_src = AadlBackend(
                optimize=not args.no_optimize,
            ).compile(mod)
            aadl_path.write_text(aadl_src, encoding="utf-8")
            results.append(("aadl", aadl_path, len(aadl_src)))
        except _ProTierRequired:
            pass
        except Exception as e:  # noqa: BLE001
            results.append(("aadl", Path("<skipped>"), 0))
            print(f"  aadl skipped: {e}", file=sys.stderr)

        # ROS2 package (CMakeLists.txt + package.xml + node) — Pro tier
        try:
            if not is_pro: skipped_pro.append("ros2"); raise _ProTierRequired
            from software.backends.ros2_backend import Ros2Backend
            ros = Ros2Backend(optimize=not args.no_optimize).compile_full(mod)
            ros_dir = out_dir / ros.package_name
            (ros_dir / "src").mkdir(parents=True, exist_ok=True)
            (ros_dir / "CMakeLists.txt").write_text(
                ros.cmakelists, encoding="utf-8")
            (ros_dir / "package.xml").write_text(
                ros.package_xml, encoding="utf-8")
            (ros_dir / "src" / f"{ros.primary_fn}_node.cpp").write_text(
                ros.node_source, encoding="utf-8")
            results.append(
                ("ros2",
                 ros_dir,
                 len(ros.cmakelists) + len(ros.package_xml)
                 + len(ros.node_source))
            )
        except _ProTierRequired:
            pass
        except Exception as e:  # noqa: BLE001
            results.append(("ros2", Path("<skipped>"), 0))
            print(f"  ros2 skipped: {e}", file=sys.stderr)

        # Rust
        from software.backends.rust_backend import RustBackend
        rs_path = out_dir / f"{stem}.rs"
        rs_src = RustBackend(optimize=not args.no_optimize).compile(mod)
        rs_path.write_text(rs_src, encoding="utf-8")
        results.append(("rust", rs_path, len(rs_src)))

        # Python
        from software.backends.python_backend import PythonBackend
        py_path = out_dir / f"{stem}.py"
        py_src = PythonBackend(optimize=not args.no_optimize).compile(mod)
        py_path.write_text(py_src, encoding="utf-8")
        results.append(("python", py_path, len(py_src)))

        # LLVM IR — Pro tier
        if not is_pro:
            skipped_pro.append("llvm")
        else:
            from software.backends.llvm_backend import LLVMBackend
            ll_path = out_dir / f"{stem}.ll"
            ll_src = LLVMBackend(optimize=not args.no_optimize).compile(mod)
            ll_path.write_text(ll_src, encoding="utf-8")
            results.append(("llvm", ll_path, len(ll_src)))

        # WASM (or LLVM-IR fallback when no llc/clang on PATH) — Pro tier
        if not is_pro:
            skipped_pro.append("wasm")
        else:
            from software.backends.wasm_backend import WASMBackend
            wasm_result = WASMBackend(
                optimize=not args.no_optimize,
            ).compile_full(mod)
            if wasm_result.toolchain == "none":
                wasm_path = out_dir / f"{stem}.wasm.ll"
                wasm_path.write_text(wasm_result.ir, encoding="utf-8")
                results.append(("wasm-ir", wasm_path, len(wasm_result.ir)))
            else:
                wasm_path = out_dir / f"{stem}.wasm"
                wasm_path.write_bytes(wasm_result.wasm)
                results.append(("wasm", wasm_path, len(wasm_result.wasm)))

        # Lean (only if any @verify(lean) blocks)
        from software.verification.lean.LeanBackend import LeanBackend
        lean_src = LeanBackend(optimize=not args.no_optimize).compile_module(mod)
        if lean_src:
            lean_path = out_dir / f"{stem}.lean"
            lean_path.write_text(lean_src, encoding="utf-8")
            results.append(("lean", lean_path, len(lean_src)))

        # HDL backends (only if any @target(fpga) functions) — Pro tier
        try:
            if not is_pro:
                skipped_pro.extend(["verilog", "systemverilog",
                                    "vhdl", "chisel"])
                raise _ProTierRequired
            from hardware.allocator import FPGAAllocator
            from hardware.hdl_gen.verilog_backend import VerilogBackend
            from hardware.hdl_gen.vhdl_backend import VHDLBackend
            from hardware.hdl_gen.chisel_backend import ChiselBackend
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )

            v_src = VerilogBackend(optimize=not args.no_optimize).compile(mod, plan)
            v_path = out_dir / f"{stem}.v"
            v_path.write_text(v_src, encoding="utf-8")
            results.append(("verilog", v_path, len(v_src)))

            from hardware.hdl_gen.systemverilog_backend import (
                SystemVerilogBackend,
            )
            sv_src = SystemVerilogBackend(
                optimize=not args.no_optimize,
            ).compile(mod, plan)
            sv_path = out_dir / f"{stem}.sv"
            sv_path.write_text(sv_src, encoding="utf-8")
            results.append(("systemverilog", sv_path, len(sv_src)))

            vhd_src = VHDLBackend(optimize=not args.no_optimize).compile(mod, plan)
            vhd_path = out_dir / f"{stem}.vhd"
            vhd_path.write_text(vhd_src, encoding="utf-8")
            results.append(("vhdl", vhd_path, len(vhd_src)))

            ch_src = ChiselBackend(optimize=not args.no_optimize).compile(mod, plan)
            # snake_case -> CamelCase + .scala
            stem_camel = "".join(w.capitalize() for w in stem.split("_"))
            ch_path = out_dir / f"{stem_camel}.scala"
            ch_path.write_text(ch_src, encoding="utf-8")
            results.append(("chisel", ch_path, len(ch_src)))
        except _ProTierRequired:
            pass  # already recorded in skipped_pro
        except Exception as e:  # noqa: BLE001 -- best-effort
            results.append(("verilog", Path("<skipped>"), 0))
            results.append(("vhdl",    Path("<skipped>"), 0))
            results.append(("chisel",  Path("<skipped>"), 0))
            print(f"  hdl skipped: {e}", file=sys.stderr)

        print(f"# eml-compile --target all  ->  {out_dir}  "
              f"(tier: {tier_label})")
        for target, path, nbytes in results:
            if path.name == "<skipped>":
                print(f"  [skip] {target}")
            else:
                print(f"  [ok]   {target:8s} {path}  ({nbytes:,} bytes)")
        if skipped_pro:
            print(
                f"  [pro]  {len(skipped_pro)} backends skipped "
                f"(Pro tier): {', '.join(sorted(set(skipped_pro)))}",
                file=sys.stderr,
            )
            print(
                f"         Get Pro at https://monogateforge.com/get-started",
                file=sys.stderr,
            )
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

    if args.target == "java":
        from software.backends.java_backend import (
            JavaBackend, CompileError as JavaErr,
        )
        try:
            j = JavaBackend(optimize=not args.no_optimize).compile(mod)
        except JavaErr as e:
            print(f"compile error (java backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(j, encoding="utf-8")
            print(f"wrote {args.output} ({len(j)} bytes)", file=sys.stderr)
        else:
            print(j, end="")
        return 0

    if args.target == "kotlin":
        from software.backends.kotlin_backend import (
            KotlinBackend, CompileError as KtErr,
        )
        try:
            k = KotlinBackend(optimize=not args.no_optimize).compile(mod)
        except KtErr as e:
            print(f"compile error (kotlin backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(k, encoding="utf-8")
            print(f"wrote {args.output} ({len(k)} bytes)", file=sys.stderr)
        else:
            print(k, end="")
        return 0

    if args.target == "go":
        from software.backends.go_backend import (
            GoBackend, CompileError as GoErr,
        )
        try:
            g = GoBackend(optimize=not args.no_optimize).compile(mod)
        except GoErr as e:
            print(f"compile error (go backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(g, encoding="utf-8")
            print(f"wrote {args.output} ({len(g)} bytes)", file=sys.stderr)
        else:
            print(g, end="")
        return 0

    if args.target == "solidity":
        from software.backends.solidity_backend import (
            SolidityBackend, CompileError as SolErr,
        )
        try:
            s = SolidityBackend(optimize=not args.no_optimize).compile(mod)
        except SolErr as e:
            print(f"compile error (solidity backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(s, encoding="utf-8")
            print(f"wrote {args.output} ({len(s)} bytes)", file=sys.stderr)
        else:
            print(s, end="")
        return 0

    if args.target == "autosar":
        from software.backends.autosar_backend import (
            AutosarBackend, CompileError as AutoErr,
        )
        try:
            au = AutosarBackend(
                optimize=not args.no_optimize,
            ).compile_full(mod)
        except AutoErr as e:
            print(f"compile error (autosar backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            stem = args.output.with_suffix("")
            arxml_path = stem.with_suffix(".arxml")
            c_path = stem.with_suffix(".c")
            arxml_path.write_text(au.arxml, encoding="utf-8")
            c_path.write_text(au.c_source, encoding="utf-8")
            print(f"wrote {arxml_path} ({len(au.arxml)} bytes)", file=sys.stderr)
            print(f"wrote {c_path} ({len(au.c_source)} bytes)", file=sys.stderr)
        else:
            print(AutosarBackend(
                optimize=not args.no_optimize,
            ).compile(mod), end="")
        return 0

    if args.target == "aadl":
        from software.backends.aadl_backend import (
            AadlBackend, CompileError as AadlErr,
        )
        try:
            a = AadlBackend(optimize=not args.no_optimize).compile(mod)
        except AadlErr as e:
            print(f"compile error (aadl backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(a, encoding="utf-8")
            print(f"wrote {args.output} ({len(a)} bytes)", file=sys.stderr)
        else:
            print(a, end="")
        return 0

    if args.target == "coq":
        from software.verification.coq.coq_backend import (
            CoqBackend, CompileError as CoqErr,
        )
        try:
            coq_source = CoqBackend(optimize=not args.no_optimize).compile(mod)
        except CoqErr as e:
            print(f"compile error (coq backend): {e}", file=sys.stderr)
            return 1
        if not coq_source:
            print("# coq: no @verify block found -- nothing to emit",
                  file=sys.stderr)
            return 0
        if args.output:
            args.output.write_text(coq_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(coq_source)} bytes)", file=sys.stderr)
        else:
            print(coq_source, end="")
        return 0

    if args.target == "isabelle":
        from software.verification.isabelle.isabelle_backend import (
            IsabelleBackend, CompileError as IsaErr,
        )
        try:
            isa_source = IsabelleBackend(
                optimize=not args.no_optimize,
            ).compile(mod)
        except IsaErr as e:
            print(f"compile error (isabelle backend): {e}", file=sys.stderr)
            return 1
        if not isa_source:
            print("# isabelle: no @verify block found -- nothing to emit",
                  file=sys.stderr)
            return 0
        if args.output:
            args.output.write_text(isa_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(isa_source)} bytes)", file=sys.stderr)
        else:
            print(isa_source, end="")
        return 0

    if args.target == "ros2":
        from software.backends.ros2_backend import (
            Ros2Backend, CompileError as Ros2Err,
        )
        try:
            ros = Ros2Backend(optimize=not args.no_optimize).compile_full(mod)
        except Ros2Err as e:
            print(f"compile error (ros2 backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            # --output is a directory; write a complete ROS2 package
            # tree underneath it.
            pkg_dir = args.output / ros.package_name
            (pkg_dir / "src").mkdir(parents=True, exist_ok=True)
            (pkg_dir / "CMakeLists.txt").write_text(
                ros.cmakelists, encoding="utf-8")
            (pkg_dir / "package.xml").write_text(
                ros.package_xml, encoding="utf-8")
            node_path = pkg_dir / "src" / f"{ros.primary_fn}_node.cpp"
            node_path.write_text(ros.node_source, encoding="utf-8")
            print(f"wrote {pkg_dir}/  (CMakeLists.txt, package.xml, "
                  f"src/{ros.primary_fn}_node.cpp)", file=sys.stderr)
        else:
            print(Ros2Backend(
                optimize=not args.no_optimize,
            ).compile(mod), end="")
        return 0

    if args.target == "matlab":
        from software.backends.matlab_backend import (
            MatlabBackend, CompileError as MatlabErr,
        )
        try:
            m_source = MatlabBackend(optimize=not args.no_optimize).compile(mod)
        except MatlabErr as e:
            print(f"compile error (matlab backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(m_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(m_source)} bytes, "
                  f"{m_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(m_source, end="")
        return 0

    if args.target == "ada":
        from software.backends.ada_backend import AdaBackend, CompileError as AdaErr
        try:
            ada = AdaBackend(optimize=not args.no_optimize).compile_full(mod)
        except AdaErr as e:
            print(f"compile error (ada backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            # Emit two files side-by-side: <stem>.ads and <stem>.adb.
            stem = args.output.with_suffix("")
            ads_path = stem.with_suffix(".ads")
            adb_path = stem.with_suffix(".adb")
            ads_path.write_text(ada.spec, encoding="utf-8")
            adb_path.write_text(ada.body, encoding="utf-8")
            print(f"wrote {ads_path} ({len(ada.spec)} bytes)", file=sys.stderr)
            print(f"wrote {adb_path} ({len(ada.body)} bytes)", file=sys.stderr)
        else:
            # Stdout: combined spec + body with banner separators.
            print(AdaBackend(optimize=not args.no_optimize).compile(mod), end="")
        return 0

    if args.target == "cpp":
        from software.backends.cpp_backend import CppBackend, CompileError as CppErr
        try:
            cpp_source = CppBackend(optimize=not args.no_optimize).compile(mod)
        except CppErr as e:
            print(f"compile error (cpp backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(cpp_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(cpp_source)} bytes, "
                  f"{cpp_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(cpp_source, end="")
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

    if args.target == "systemverilog":
        from hardware.allocator import FPGAAllocator
        from hardware.allocator import CompileError as AllocErr
        from hardware.hdl_gen.systemverilog_backend import (
            SystemVerilogBackend, CompileError as SVErr,
        )
        try:
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )
            sv_source = SystemVerilogBackend(
                optimize=not args.no_optimize,
            ).compile(mod, plan)
        except (AllocErr, SVErr) as e:
            print(f"compile error (systemverilog backend): {e}",
                  file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(sv_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(sv_source)} bytes, "
                  f"{sv_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(sv_source, end="")
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

    if args.target == "python":
        from software.backends.python_backend import (
            PythonBackend, CompileError as PyErr,
        )
        try:
            py_source = PythonBackend(optimize=not args.no_optimize).compile(mod)
        except PyErr as e:
            print(f"compile error (python backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(py_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(py_source)} bytes, "
                  f"{py_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(py_source, end="")
        return 0

    if args.target == "llvm":
        from software.backends.llvm_backend import (
            LLVMBackend, CompileError as LLVMErr,
        )
        try:
            ir = LLVMBackend(optimize=not args.no_optimize).compile(mod)
        except LLVMErr as e:
            print(f"compile error (llvm backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(ir, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(ir)} bytes, "
                  f"{ir.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(ir, end="")
        return 0

    if args.target == "wasm":
        from software.backends.wasm_backend import WASMBackend
        result = WASMBackend(optimize=not args.no_optimize).compile_full(mod)
        if result.toolchain == "none":
            # No llc/clang -- emit IR so the user can finish the
            # compile with their own toolchain.
            if args.output:
                args.output.write_text(result.ir, encoding="utf-8")
                print(f"wrote LLVM IR to {args.output} "
                      f"(no llc/clang on PATH; install one to emit wasm bytecode)",
                      file=sys.stderr)
            else:
                print(result.ir, end="")
            return 0
        if args.output:
            args.output.write_bytes(result.wasm)
            print(f"wrote {args.output} "
                  f"({len(result.wasm)} bytes wasm via {result.toolchain})",
                  file=sys.stderr)
        else:
            sys.stdout.buffer.write(result.wasm)
        return 0

    if args.target == "vhdl":
        from hardware.allocator import FPGAAllocator
        from hardware.allocator import CompileError as AllocErr
        from hardware.hdl_gen.vhdl_backend import (
            VHDLBackend, CompileError as VHDLErr,
        )
        try:
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )
            vhdl_source = VHDLBackend(
                optimize=not args.no_optimize,
            ).compile(mod, plan)
        except (AllocErr, VHDLErr) as e:
            print(f"compile error (vhdl backend): {e}",
                  file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(vhdl_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(vhdl_source)} bytes, "
                  f"{vhdl_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(vhdl_source, end="")
        return 0

    if args.target == "chisel":
        from hardware.allocator import FPGAAllocator
        from hardware.allocator import CompileError as AllocErr
        from hardware.hdl_gen.chisel_backend import (
            ChiselBackend, CompileError as ChiselErr,
        )
        try:
            plan = FPGAAllocator().allocate(
                mod, constraints={"target": args.fpga_target},
            )
            chisel_source = ChiselBackend(
                optimize=not args.no_optimize,
            ).compile(mod, plan)
        except (AllocErr, ChiselErr) as e:
            print(f"compile error (chisel backend): {e}",
                  file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(chisel_source, encoding="utf-8")
            print(f"wrote {args.output} "
                  f"({len(chisel_source)} bytes, "
                  f"{chisel_source.count(chr(10))} lines)",
                  file=sys.stderr)
        else:
            print(chisel_source, end="")
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
