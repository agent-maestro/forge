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
            "Compile one .eml source to 35 different targets: software, "
            "GPU shaders, FPGA RTL, formal-verification proofs, and "
            "safety-critical avionics."
        ),
        epilog=(
            "EXAMPLES\n"
            "  eml-compile pid.eml --profile-only           # chain order + cost\n"
            "  eml-compile pid.eml --target rust -o pid.rs  # single target\n"
            "  eml-compile pid.eml --target all  -o build/  # every target your tier permits\n"
            "  eml-compile pid.eml --explain                # what the optimizer did\n"
            "  eml-compile pid.eml --allocate \\\n"
            "                       --fpga-target xilinx.artix7  # FPGA resource plan\n"
            "  eml-compile init my_project                  # scaffold a new project\n"
            "  eml-compile manpage                          # print the man page\n"
            "\n"
            "TIERS\n"
            "  Free:  c, cpp, rust, python, go, java, kotlin, csharp,\n"
            "         javascript, wasm, matlab, lean, zkproof\n"
            "  Pro:   verilog, vhdl, systemverilog, chisel, llvm,\n"
            "         hlsl, glsl, glsles, wgsl, metal, swift,\n"
            "         luau, gdscript, ada, autosar, aadl, ros2,\n"
            "         coq, isabelle, solidity, spice, kicad, jlcpcb\n"
            "  Get a Pro license at https://monogateforge.com/get-started\n"
            "\n"
            "DOCS\n"
            "  Quickstart:    https://github.com/agent-maestro/forge/blob/master/docs/quickstart.md\n"
            "  Lang reference: https://github.com/agent-maestro/forge/blob/master/docs/language-reference.md\n"
            "  Tutorial:      https://monogate.dev/learn/eml/intro\n"
            "  Bug reports:   https://github.com/agent-maestro/forge/issues"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("source", type=Path, nargs="?",
                        help="Path to a .eml source file")
    parser.add_argument("--target", choices=[
        "c", "cpp", "rust", "python", "llvm", "wasm",
        "verilog", "systemverilog", "vhdl", "chisel", "lean",
        "ada", "matlab",
        "coq", "isabelle", "ros2",
        "java", "kotlin", "csharp", "hlsl", "glsl", "glsles",
        "wgsl", "metal", "swift",
        "javascript", "luau",
        "gdscript",
        "go", "autosar", "aadl",
        "solidity",
        "zkproof",
        "spice",
        "kicad",
        "jlcpcb",
        "all",
    ], help=("Output target. 'all' runs every backend your "
            "license tier permits (Free: 12 application + Lean + "
            "zkproof; Pro: all 35 + jlcpcb bundle) and writes <stem>.<ext> files "
            "into --output (must be a directory) or alongside the "
            "source. See `--help` epilog for the tier list."))
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
    parser.add_argument("--namespace-emitted-consts", action="store_true",
                        help="WGSL backend only: prefix every emitted "
                             "module-level `const` with `<module>__` so "
                             "multiple compiled kernels can be safely "
                             "concatenated into a single shader without "
                             "name collisions on common constants like "
                             "ZERO/ONE/PI/TINY. Function names stay "
                             "un-prefixed so callers invoke them by EML "
                             "name. Off by default to preserve existing "
                             "single-kernel emission behaviour.")
    parser.add_argument("--emit-fingerprint", action="store_true",
                        help="Compute the computation fingerprint for "
                             "this module (Phase 0 of the Verification "
                             "Network) and write it as a `<stem>.fp.json` "
                             "sidecar. Backends with line-comment "
                             "syntax also embed the module hash + "
                             "per-function tree hashes as a header "
                             "block in the emitted source.")
    parser.add_argument("--fingerprint-only", action="store_true",
                        help="Print the fingerprint JSON to stdout "
                             "(or --output) and exit. Implies "
                             "--emit-fingerprint; no backend runs.")
    parser.add_argument("--no-gas-estimate", action="store_true",
                        help="When used with --target solidity, omit "
                             "the per-function NatSpec @dev gas "
                             "estimate. Useful for diff tests + "
                             "fixture comparisons that should be "
                             "insensitive to the gas table.")
    parser.add_argument("--spec-bundle", action="store_true",
                        help="When used with --target solidity, also "
                             "write a `<stem>.spec.json` sidecar "
                             "carrying the structured formal spec "
                             "(requires/ensures, Lean theorem refs, "
                             "Pfaffian profile, gas estimate). "
                             "Auditors diff this against the .sol.")
    parser.add_argument("--audit-bundle", action="store_true",
                        help="When used with --target solidity, write "
                             "an audit-ready directory `<stem>_audit/` "
                             "containing the .sol, .spec.json, the "
                             "EML source, copies of every referenced "
                             "Lean theorem, an AUDITOR.md guide, and "
                             "a manifest.json with sha256 of every "
                             "artifact. Implies --spec-bundle, "
                             "--with-prbmath, --with-foundry-tests.")
    parser.add_argument("--with-prbmath", action="store_true",
                        help="When used with --target solidity, also "
                             "emit a `<Contract>WithPRBMath.sol` child "
                             "contract that wires the transcendental "
                             "stubs to PRBMath SD59x18 implementations.")
    parser.add_argument("--with-foundry-tests", action="store_true",
                        help="When used with --target solidity, also "
                             "emit `test/<Contract>Test.t.sol` plus "
                             "`foundry.toml` so `forge test` runs out "
                             "of the box. Implies --with-prbmath.")
    parser.add_argument("--machlib-root", type=Path, default=None,
                        help="Override the MachLib search root used "
                             "by --audit-bundle to locate Lean proof "
                             "files, and by --auto-theorems to write "
                             "new ones. Defaults to the MACHLIB_ROOT "
                             "env var, then to the sibling-repo "
                             "`~/monogate/machlib`.")
    parser.add_argument("--cost-aware", action="store_true",
                        help="For each function, profile via "
                             "eml_cost.analyze and (if EML-cost "
                             "constraints are violated) brute-force "
                             "search the SuperBEST corpus for cheaper "
                             "siblings. Reports a recommendation "
                             "table; never auto-rewrites. Pro-tier "
                             "feature.")
    parser.add_argument("--max-chain-order", type=int, default=None,
                        help="(--cost-aware) Maximum allowed chain "
                             "order (Pfaffian r). Functions exceeding "
                             "this trigger a sibling search.")
    parser.add_argument("--max-eml-depth", type=int, default=None,
                        help="(--cost-aware) Maximum allowed eml_depth. "
                             "Functions exceeding this trigger a "
                             "sibling search.")
    parser.add_argument("--cost-aware-k", type=int, default=10,
                        help="(--cost-aware) Number of corpus "
                             "siblings to consider per function. "
                             "Default 10.")
    parser.add_argument("--generate-tests", action="store_true",
                        help="Auto-generate input vectors for every "
                             "Real-typed function in the source, run "
                             "the existing cross-target equivalence "
                             "harness (Python ref vs Rust + C by "
                             "default), and print pass/fail per "
                             "function. No files written -- the "
                             "compile/run lands in a temp dir per "
                             "backend. Exits non-zero if any function "
                             "disagrees on an available backend.")
    parser.add_argument("--gen-tests-vectors", type=int, default=32,
                        help="(--generate-tests) Random input vectors "
                             "per function. Default 32.")
    parser.add_argument("--gen-tests-targets", default="rust,c",
                        help="(--generate-tests) Comma-separated "
                             "targets to compare against the Python "
                             "reference. Default `rust,c`. `python` "
                             "is always the reference and is implicit.")
    parser.add_argument("--gen-tests-tolerance", type=float, default=1e-9,
                        help="(--generate-tests) Max absolute error "
                             "for a per-vector pass. Default 1e-9.")
    parser.add_argument("--gen-tests-seed", type=int, default=0,
                        help="(--generate-tests) RNG seed for "
                             "reproducible vector generation.")
    parser.add_argument("--auto-theorems", action="store_true",
                        help="After compiling, also emit Lean "
                             "theorem scaffolding for any "
                             "`@verify(lean, ...)` block to "
                             "`<machlib-root>/foundations/MachLib/"
                             "Discovered/<basename>.lean`. The "
                             "source-path comment is redacted to "
                             "`<private>/<basename>.eml` per the "
                             "open-core IP rule. No-op when the "
                             "source has no Lean verification "
                             "blocks. Same emit logic as "
                             "`tools/scripts/regen_discovered.py`, "
                             "but per-file at compile time.")
    parser.add_argument("--strict-refinements", action="store_true",
                        default=False,
                        help="(Phase C) Enable the refinement auto-splicer. "
                             "Single-variable `requires`/`ensures` clauses are "
                             "folded into the corresponding parameter or return "
                             "refinement type. Multi-variable clauses stay as-is. "
                             "When this flag is OFF (the default), behaviour is "
                             "byte-identical to pre-Phase-C. When ON, a one-line "
                             "note appears in `--explain` output for each clause "
                             "that was absorbed into a refinement.")
    parser.add_argument("--lint", action="store_true",
                        default=False,
                        help="(v0.5 deprecation) Emit warnings for `requires` "
                             "clauses that use transcendental functions (sin, "
                             "cos, tan, exp, ln, sqrt, asin, acos, atan, sinh, "
                             "cosh, tanh, pow with non-integer exponent). "
                             "The refinement sub-language cannot decide such "
                             "predicates; migrate to `assume (...)` or move the "
                             "check into the function body. Default OFF: "
                             "without this flag behaviour is byte-identical to "
                             "pre-v0.5. Warnings are emitted to stderr; the "
                             "compile still succeeds.")
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
                        version="eml-compile 0.4.0")
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

    # ── Phase C addendum: alias refinement/unit expansion ────
    # Must run BEFORE the unit type-checker so that a parameter declared
    # with an alias type (e.g. `f: AudibleFreq` where AudibleFreq is
    # `Real[Hz]{...}`) carries the alias's unit_expr during unit inference.
    try:
        from lang.refinements import expand_aliases_module as _expand_aliases
        _expand_aliases(mod)
    except ImportError:
        pass  # lang.refinements not yet installed in older envs -- skip silently

    # ── Phase B: dimensional type-check (before optimizer) ───
    try:
        from lang.unit_types import check_module as _unit_check, UnitTypeError
        _unit_check(mod)
    except UnitTypeError as e:
        print(f"type error: {e}", file=sys.stderr)
        return 1
    except ImportError:
        pass  # lang.unit_types not yet installed in older envs -- skip silently

    # ── Phase C: refinement auto-splicer + refinement check ──────────
    # The auto-splicer is gated behind --strict-refinements (default OFF).
    # With the flag OFF, this block is a no-op; output is byte-identical
    # to pre-Phase-C.  With the flag ON, single-variable requires/ensures
    # clauses are folded into parameter/return refinements.
    _refinement_splice_notes: list[str] = []
    try:
        from lang.refinements import (
            auto_splice_module as _ref_splice,
            check_module as _ref_check,
            RefinementError,
        )
        _strict = getattr(args, "strict_refinements", False)
        _ref_splice(mod, strict_mode=_strict)
        # Collect splice notes for --explain output
        if _strict:
            for fn in mod.functions:
                notes = getattr(fn, "_splice_notes", [])
                for note in notes:
                    _refinement_splice_notes.append(f"  [refinement-splicer] {fn.name}: {note}")
        _ref_check(mod)
    except RefinementError as e:
        print(f"refinement error: {e}", file=sys.stderr)
        return 1
    except ImportError:
        pass  # lang.refinements not yet installed -- skip silently

    # ── v0.5 deprecation lint: transcendental `requires` warnings ────
    # Default OFF.  Only runs when --lint is set.  Warnings go to stderr;
    # the compile continues and exits 0 regardless.
    if getattr(args, "lint", False):
        try:
            from lang.lint import lint_module as _lint_module
            _lint_warnings = _lint_module(mod, lint_enabled=True)
            for _w in _lint_warnings:
                print(_w.message, file=sys.stderr)
        except ImportError:
            pass  # lang.lint not yet installed -- skip silently

    profiler = Profiler()
    profiler.profile_module(mod)

    # ── Fingerprint (Phase 0 of the Verification Network) ────
    # Computed once after profiling so the deterministic profile
    # subset is available for embedding.
    from lang.fingerprint import (
        embed_fingerprint as _fp_embed,
        fingerprint_module as _fp_module,
        has_embed_support as _fp_has_embed,
    )

    _fp = _fp_module(mod) if (
        args.emit_fingerprint or args.fingerprint_only
    ) else None
    _fp_sidecar_written: list[Path] = []

    def _maybe_stamp(source: str, target: str) -> str:
        """Prepend the fingerprint header comment, when --emit-fingerprint
        is on and the target supports line/block comments."""
        if _fp is None or not _fp_has_embed(target):
            return source
        return _fp_embed(source, target=target, fp=_fp)

    def _maybe_write_sidecar(out_path: Path | None) -> None:
        """Write the .fp.json sidecar next to ``out_path``, idempotently.

        Skipped when --emit-fingerprint isn't on, when the user is
        printing to stdout (no out_path), or when an identical
        sidecar already exists (build-cache friendliness)."""
        if _fp is None or out_path is None:
            return
        sidecar = (
            out_path.with_suffix(out_path.suffix + ".fp.json")
            if out_path.suffix
            else out_path.with_suffix(".fp.json")
        )
        payload = _fp.to_json()
        if (
            not sidecar.exists()
            or sidecar.read_text(encoding="utf-8") != payload
        ):
            sidecar.write_text(payload, encoding="utf-8")
        if sidecar not in _fp_sidecar_written:
            _fp_sidecar_written.append(sidecar)

    # ── --fingerprint-only -> emit JSON and exit ─────────────
    if args.fingerprint_only:
        payload = _fp.to_json() if _fp else "{}"
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
            print(f"wrote {args.output} ({len(payload)} bytes)",
                  file=sys.stderr)
        else:
            sys.stdout.write(payload + "\n")
        return 0

    if args.cost_aware:
        from tools.cli.cost_aware import (
            format_report as _format_cost_report,
            run as _run_cost_aware,
        )
        cost_report = _run_cost_aware(
            args.source,
            max_chain_order=args.max_chain_order,
            max_eml_depth=args.max_eml_depth,
            k=args.cost_aware_k,
        )
        print(_format_cost_report(cost_report))
        return 0 if cost_report.all_ok else 1

    if args.generate_tests:
        from tools.cli.generate_tests import (
            format_report,
            generate_and_run,
        )
        targets = tuple(
            t.strip() for t in args.gen_tests_targets.split(",")
            if t.strip()
        )
        report = generate_and_run(
            args.source,
            n_vectors=args.gen_tests_vectors,
            targets=targets,
            tolerance=args.gen_tests_tolerance,
            seed=args.gen_tests_seed,
        )
        print(format_report(report))
        return 0 if report.all_pass else 1

    if args.auto_theorems:
        from software.verification.lean.discovered_emit import (
            resolve_machlib_root,
            write_discovered_lean,
        )
        try:
            dest = write_discovered_lean(
                mod,
                basename=args.source.stem,
                machlib_root=resolve_machlib_root(args.machlib_root),
            )
        except FileNotFoundError as e:
            print(f"--auto-theorems: {e}", file=sys.stderr)
            return 2
        if dest is None:
            print(f"--auto-theorems: no `@verify(lean, ...)` blocks "
                  f"in {args.source}; nothing emitted",
                  file=sys.stderr)
        else:
            print(f"--auto-theorems: wrote {dest} "
                  f"({dest.stat().st_size} bytes)",
                  file=sys.stderr)

    # ── --explain -> per-function optimizer diff ─────────────
    if args.explain:
        from tools.cli.explain import print_explain_report
        print_explain_report(
            mod,
            include_backend_stats=args.backend_stats,
            as_json=args.json,
        )
        # Phase C: append splice notes when --strict-refinements was also used.
        if _refinement_splice_notes:
            print()
            print("# Phase C refinement auto-splicer absorbed the following clauses:")
            for note in _refinement_splice_notes:
                print(note)
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
        # When --emit-fingerprint is on without a backend target,
        # write the sidecar next to the source so users can compute
        # fingerprints in CI without picking a target.
        if _fp is not None:
            sidecar = args.source.with_suffix(args.source.suffix + ".fp.json")
            payload = _fp.to_json()
            if (not sidecar.exists()
                    or sidecar.read_text(encoding="utf-8") != payload):
                sidecar.write_text(payload, encoding="utf-8")
            print(f"# fingerprint: {sidecar}", file=sys.stderr)
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

        # When --emit-fingerprint is on, drop the sidecar in the
        # output dir under the source stem. Each per-target write
        # below also calls _maybe_write_sidecar, which is idempotent
        # so repeated writes are free.
        if _fp is not None:
            sidecar = out_dir / f"{stem}.fp.json"
            payload = _fp.to_json()
            if (not sidecar.exists()
                    or sidecar.read_text(encoding="utf-8") != payload):
                sidecar.write_text(payload, encoding="utf-8")
            print(f"# fingerprint: {sidecar}", file=sys.stderr)

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

        # C# (Unity-ready)
        try:
            from software.backends.csharp_backend import CSharpBackend
            cs_path = out_dir / f"{stem.title().replace('_', '')}.cs"
            cs_src = CSharpBackend(optimize=not args.no_optimize).compile(mod)
            cs_path.write_text(cs_src, encoding="utf-8")
            results.append(("csharp", cs_path, len(cs_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("csharp", Path("<skipped>"), 0))
            print(f"  csharp skipped: {e}", file=sys.stderr)

        # HLSL shader function library
        try:
            from software.backends.hlsl_backend import HLSLBackend
            hl_path = out_dir / f"{stem}.hlsl"
            hl_src = HLSLBackend(optimize=not args.no_optimize).compile(mod)
            hl_path.write_text(hl_src, encoding="utf-8")
            results.append(("hlsl", hl_path, len(hl_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("hlsl", Path("<skipped>"), 0))
            print(f"  hlsl skipped: {e}", file=sys.stderr)

        # GLSL desktop function library (Godot, OpenGL 3.3+)
        try:
            from software.backends.glsl_backend import GLSLBackend
            gl_path = out_dir / f"{stem}.glsl"
            gl_src = GLSLBackend(
                optimize=not args.no_optimize, flavor="desktop",
            ).compile(mod)
            gl_path.write_text(gl_src, encoding="utf-8")
            results.append(("glsl", gl_path, len(gl_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("glsl", Path("<skipped>"), 0))
            print(f"  glsl skipped: {e}", file=sys.stderr)

        # GLSL ES function library (WebGL 2.0, mobile OpenGL ES 3.0)
        try:
            from software.backends.glsl_backend import GLSLBackend
            gles_path = out_dir / f"{stem}.glsles"
            gles_src = GLSLBackend(
                optimize=not args.no_optimize, flavor="es",
            ).compile(mod)
            gles_path.write_text(gles_src, encoding="utf-8")
            results.append(("glsles", gles_path, len(gles_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("glsles", Path("<skipped>"), 0))
            print(f"  glsles skipped: {e}", file=sys.stderr)

        # GDScript (Godot 4.x)
        try:
            from software.backends.gdscript_backend import GDScriptBackend
            gd_path = out_dir / f"{stem}.gd"
            gd_src = GDScriptBackend(optimize=not args.no_optimize).compile(mod)
            gd_path.write_text(gd_src, encoding="utf-8")
            results.append(("gdscript", gd_path, len(gd_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("gdscript", Path("<skipped>"), 0))
            print(f"  gdscript skipped: {e}", file=sys.stderr)

        # WGSL (WebGPU)
        try:
            from software.backends.wgsl_backend import WGSLBackend
            wg_path = out_dir / f"{stem}.wgsl"
            # `namespace_constants=args.namespace_emitted_consts` to mirror the
            # single-target dispatch at the bottom of this module — the
            # multi-target loop was silently dropping the flag, so a
            # multi-target compile produced bare `ZERO`/`ONE`/`PI` while a
            # `--target wgsl` compile of the same source produced
            # `<module>__ZERO`. That asymmetry tripped the engine's drift-
            # check (which assumes the two backends agree).
            wg_src = WGSLBackend(
                optimize=not args.no_optimize,
                namespace_constants=args.namespace_emitted_consts,
            ).compile(mod)
            wg_path.write_text(wg_src, encoding="utf-8")
            results.append(("wgsl", wg_path, len(wg_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("wgsl", Path("<skipped>"), 0))
            print(f"  wgsl skipped: {e}", file=sys.stderr)

        # Metal (Apple iOS / macOS / iPadOS shaders)
        try:
            from software.backends.metal_backend import MetalBackend
            mt_path = out_dir / f"{stem}.metal"
            mt_src = MetalBackend(optimize=not args.no_optimize).compile(mod)
            mt_path.write_text(mt_src, encoding="utf-8")
            results.append(("metal", mt_path, len(mt_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("metal", Path("<skipped>"), 0))
            print(f"  metal skipped: {e}", file=sys.stderr)

        # Swift
        try:
            from software.backends.swift_backend import SwiftBackend
            sw_path = out_dir / f"{stem}.swift"
            sw_src = SwiftBackend(optimize=not args.no_optimize).compile(mod)
            sw_path.write_text(sw_src, encoding="utf-8")
            results.append(("swift", sw_path, len(sw_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("swift", Path("<skipped>"), 0))
            print(f"  swift skipped: {e}", file=sys.stderr)

        # JavaScript (ES module)
        try:
            from software.backends.javascript_backend import (
                JavaScriptBackend,
            )
            js_path = out_dir / f"{stem}.mjs"
            js_src = JavaScriptBackend(
                optimize=not args.no_optimize,
            ).compile(mod)
            js_path.write_text(js_src, encoding="utf-8")
            results.append(("javascript", js_path, len(js_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("javascript", Path("<skipped>"), 0))
            print(f"  javascript skipped: {e}", file=sys.stderr)

        # Luau (Roblox typed Lua)
        try:
            from software.backends.luau_backend import LuauBackend
            lu_path = out_dir / f"{stem}.luau"
            lu_src = LuauBackend(optimize=not args.no_optimize).compile(mod)
            lu_path.write_text(lu_src, encoding="utf-8")
            results.append(("luau", lu_path, len(lu_src)))
        except Exception as e:  # noqa: BLE001
            results.append(("luau", Path("<skipped>"), 0))
            print(f"  luau skipped: {e}", file=sys.stderr)

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
            sol_backend = SolidityBackend(
                optimize=not args.no_optimize,
                gas_estimate=not args.no_gas_estimate,
            )
            sol_src = sol_backend.compile(mod)
            sol_path.write_text(sol_src, encoding="utf-8")
            results.append(("solidity", sol_path, len(sol_src)))
            if args.spec_bundle and not args.audit_bundle:
                from software.backends.solidity_spec import build_spec
                spec_path = out_dir / f"{stem}.spec.json"
                import json as _json
                spec_path.write_text(
                    _json.dumps(
                        build_spec(mod, backend=sol_backend),
                        indent=2, sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                results.append(
                    ("solidity-spec", spec_path,
                     spec_path.stat().st_size),
                )
            if args.audit_bundle:
                from software.backends.solidity_audit import (
                    write_audit_bundle,
                )
                bundle = write_audit_bundle(
                    mod,
                    eml_source_path=args.source.resolve(),
                    out_root=out_dir / f"{stem}_audit",
                    backend=sol_backend,
                    machlib_root=args.machlib_root,
                )
                results.append((
                    "solidity-audit", bundle.root,
                    sum(p.stat().st_size for p in bundle.files),
                ))
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
        c_source = _maybe_stamp(c_source, "c")
        if args.output:
            args.output.write_text(c_source, encoding="utf-8")
            _maybe_write_sidecar(args.output)
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

    if args.target == "csharp":
        from software.backends.csharp_backend import (
            CSharpBackend, CompileError as CsErr,
        )
        try:
            cs = CSharpBackend(optimize=not args.no_optimize).compile(mod)
        except CsErr as e:
            print(f"compile error (csharp backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(cs, encoding="utf-8")
            print(f"wrote {args.output} ({len(cs)} bytes)", file=sys.stderr)
        else:
            print(cs, end="")
        return 0

    if args.target == "hlsl":
        from software.backends.hlsl_backend import (
            HLSLBackend, CompileError as HlslErr,
        )
        try:
            hl = HLSLBackend(optimize=not args.no_optimize).compile(mod)
        except HlslErr as e:
            print(f"compile error (hlsl backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(hl, encoding="utf-8")
            print(f"wrote {args.output} ({len(hl)} bytes)", file=sys.stderr)
        else:
            print(hl, end="")
        return 0

    if args.target in ("glsl", "glsles"):
        from software.backends.glsl_backend import (
            GLSLBackend, CompileError as GlslErr,
        )
        flavor = "desktop" if args.target == "glsl" else "es"
        try:
            gl = GLSLBackend(
                optimize=not args.no_optimize, flavor=flavor,
            ).compile(mod)
        except GlslErr as e:
            print(f"compile error (glsl backend, {flavor}): {e}",
                  file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(gl, encoding="utf-8")
            print(f"wrote {args.output} ({len(gl)} bytes)", file=sys.stderr)
        else:
            print(gl, end="")
        return 0

    if args.target == "javascript":
        from software.backends.javascript_backend import (
            JavaScriptBackend, CompileError as JsErr,
        )
        try:
            js = JavaScriptBackend(optimize=not args.no_optimize).compile(mod)
        except JsErr as e:
            print(f"compile error (javascript backend): {e}", file=sys.stderr)
            return 1
        js = _maybe_stamp(js, "javascript")
        if args.output:
            args.output.write_text(js, encoding="utf-8")
            _maybe_write_sidecar(args.output)
            print(f"wrote {args.output} ({len(js)} bytes)", file=sys.stderr)
        else:
            print(js, end="")
        return 0

    if args.target == "luau":
        from software.backends.luau_backend import (
            LuauBackend, CompileError as LuauErr,
        )
        try:
            lu = LuauBackend(optimize=not args.no_optimize).compile(mod)
        except LuauErr as e:
            print(f"compile error (luau backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(lu, encoding="utf-8")
            print(f"wrote {args.output} ({len(lu)} bytes)", file=sys.stderr)
        else:
            print(lu, end="")
        return 0

    if args.target == "swift":
        from software.backends.swift_backend import (
            SwiftBackend, CompileError as SwErr,
        )
        try:
            sw = SwiftBackend(optimize=not args.no_optimize).compile(mod)
        except SwErr as e:
            print(f"compile error (swift backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(sw, encoding="utf-8")
            print(f"wrote {args.output} ({len(sw)} bytes)", file=sys.stderr)
        else:
            print(sw, end="")
        return 0

    if args.target == "metal":
        from software.backends.metal_backend import (
            MetalBackend, CompileError as MtlErr,
        )
        try:
            mt = MetalBackend(optimize=not args.no_optimize).compile(mod)
        except MtlErr as e:
            print(f"compile error (metal backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(mt, encoding="utf-8")
            print(f"wrote {args.output} ({len(mt)} bytes)", file=sys.stderr)
        else:
            print(mt, end="")
        return 0

    if args.target == "wgsl":
        from software.backends.wgsl_backend import (
            WGSLBackend, CompileError as WgslErr,
        )
        try:
            wg = WGSLBackend(
                optimize=not args.no_optimize,
                namespace_constants=args.namespace_emitted_consts,
            ).compile(mod)
        except WgslErr as e:
            print(f"compile error (wgsl backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(wg, encoding="utf-8")
            print(f"wrote {args.output} ({len(wg)} bytes)", file=sys.stderr)
        else:
            print(wg, end="")
        return 0

    if args.target == "gdscript":
        from software.backends.gdscript_backend import (
            GDScriptBackend, CompileError as GdErr,
        )
        try:
            gd = GDScriptBackend(optimize=not args.no_optimize).compile(mod)
        except GdErr as e:
            print(f"compile error (gdscript backend): {e}", file=sys.stderr)
            return 1
        if args.output:
            args.output.write_text(gd, encoding="utf-8")
            print(f"wrote {args.output} ({len(gd)} bytes)", file=sys.stderr)
        else:
            print(gd, end="")
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
            sol_backend = SolidityBackend(
                optimize=not args.no_optimize,
                gas_estimate=not args.no_gas_estimate,
            )
            s = sol_backend.compile(mod)
        except SolErr as e:
            print(f"compile error (solidity backend): {e}", file=sys.stderr)
            return 1
        if args.audit_bundle:
            from software.backends.solidity_audit import write_audit_bundle
            stem = (
                args.output.with_suffix("").name if args.output
                else (mod.name or args.source.stem)
            )
            audit_root = (
                args.output.parent if args.output else Path.cwd()
            ) / f"{stem}_audit"
            bundle = write_audit_bundle(
                mod,
                eml_source_path=args.source.resolve(),
                out_root=audit_root,
                backend=sol_backend,
                machlib_root=args.machlib_root,
            )
            print(
                f"wrote audit bundle {bundle.root} "
                f"({len(bundle.files)} files)",
                file=sys.stderr,
            )
            return 0
        if args.output:
            args.output.write_text(s, encoding="utf-8")
            print(f"wrote {args.output} ({len(s)} bytes)", file=sys.stderr)
            if args.spec_bundle:
                from software.backends.solidity_spec import build_spec
                import json as _json
                spec_path = args.output.with_suffix(".spec.json")
                spec_text = _json.dumps(
                    build_spec(mod, backend=sol_backend),
                    indent=2, sort_keys=True,
                )
                spec_path.write_text(spec_text, encoding="utf-8")
                print(
                    f"wrote {spec_path} ({len(spec_text)} bytes)",
                    file=sys.stderr,
                )
            if args.with_prbmath or args.with_foundry_tests:
                from software.backends.solidity_prbmath import (
                    emit_prbmath_override,
                )
                from software.backends.solidity_trig import (
                    emit_trig_library,
                )
                from software.backends.solidity_spec import build_spec
                spec = build_spec(mod, backend=sol_backend)
                used_builtins = set(sol_backend._used_builtins)
                trig = emit_trig_library(used_builtins)
                if trig is not None:
                    trig_path = args.output.with_name(
                        f"{trig.library_name}.sol",
                    )
                    trig_path.write_text(trig.source, encoding="utf-8")
                    print(
                        f"wrote {trig_path} ({len(trig.source)} bytes)",
                        file=sys.stderr,
                    )
                override = emit_prbmath_override(
                    parent_name=spec["contract"],
                    used_builtins=used_builtins,
                    parent_path=f"./{args.output.name}",
                )
                override_path = args.output.with_name(
                    f"{override.contract_name}.sol",
                )
                override_path.write_text(override.source, encoding="utf-8")
                print(
                    f"wrote {override_path} ({len(override.source)} bytes)",
                    file=sys.stderr,
                )
                if args.with_foundry_tests:
                    from software.backends.solidity_foundry import (
                        emit_foundry_scaffold,
                    )
                    scaffold = emit_foundry_scaffold(
                        spec=spec,
                        override_contract=override.contract_name,
                        override_path=f"../{override.contract_name}.sol",
                    )
                    test_dir = args.output.parent / "test"
                    test_dir.mkdir(exist_ok=True)
                    test_path = test_dir / (
                        f"{scaffold.test_contract_name}.t.sol"
                    )
                    test_path.write_text(
                        scaffold.test_source, encoding="utf-8",
                    )
                    foundry_path = args.output.parent / "foundry.toml"
                    foundry_path.write_text(
                        scaffold.foundry_toml, encoding="utf-8",
                    )
                    print(
                        f"wrote {test_path} + {foundry_path}",
                        file=sys.stderr,
                    )
        else:
            print(s, end="")
            if args.spec_bundle or args.with_prbmath or args.with_foundry_tests:
                print(
                    "warn: --spec-bundle / --with-prbmath / "
                    "--with-foundry-tests ignored without -o "
                    "(those write sidecar files).",
                    file=sys.stderr,
                )
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
        m_source = _maybe_stamp(m_source, "matlab")
        if args.output:
            args.output.write_text(m_source, encoding="utf-8")
            _maybe_write_sidecar(args.output)
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
        rust_source = _maybe_stamp(rust_source, "rust")
        if args.output:
            args.output.write_text(rust_source, encoding="utf-8")
            _maybe_write_sidecar(args.output)
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
        py_source = _maybe_stamp(py_source, "python")
        if args.output:
            args.output.write_text(py_source, encoding="utf-8")
            _maybe_write_sidecar(args.output)
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

    if args.target == "jlcpcb":
        # Phase E3 of the Math-to-Manufactured-PCB pipeline. Map
        # @spice_<component> decorations to LCSC part numbers,
        # emit a JLCPCB-upload BOM CSV + CPL stub + manifest JSON.
        # `-o` MUST be a directory; the bundle is three files.
        from software.manufacturing import (
            JLCPCBMapper, CompileError as JlcErr,
        )
        if not args.output:
            print("--target jlcpcb requires -o <dir> (the bundle is "
                  "3 files: BOM CSV + CPL CSV + manifest JSON)",
                  file=sys.stderr)
            return 1
        try:
            bundle = JLCPCBMapper().bundle(mod)
        except JlcErr as e:
            print(f"compile error (jlcpcb mapper): {e}", file=sys.stderr)
            return 1
        out_dir = args.output
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = mod.name or "eml_circuit"
        bom_path      = out_dir / f"{stem}.bom.csv"
        cpl_path      = out_dir / f"{stem}.cpl.csv"
        manifest_path = out_dir / f"{stem}.jlc.json"
        bom_path.write_text(bundle.bom_csv,    encoding="utf-8")
        cpl_path.write_text(bundle.cpl_csv,    encoding="utf-8")
        manifest_path.write_text(bundle.manifest, encoding="utf-8")
        print(f"wrote {bom_path} + {cpl_path.name} + {manifest_path.name} "
              f"({bundle.matched} matched, {bundle.unmatched} unmatched)",
              file=sys.stderr)
        if bundle.unmatched > 0:
            print(f"  WARNING: {bundle.unmatched} component(s) had no "
                  f"registry match; JLC will refuse the upload until "
                  f"resolved (see {manifest_path.name}.unmatched).",
                  file=sys.stderr)
        return 0

    if args.target == "kicad":
        # Phase E2 of the Math-to-Manufactured-PCB pipeline. Compile
        # an EML circuit module to a KiCad 8 .kicad_sch schematic
        # file. Same decorator convention as --target spice
        # (@spice_resistor, @spice_capacitor, @spice_voltage, ...);
        # one EML source -> simulatable netlist (spice) AND editable
        # schematic (kicad), no duplication.
        from software.backends.kicad_backend import (
            KiCadBackend, CompileError as KiCadErr,
        )
        try:
            kicad_result = KiCadBackend(
                optimize=not args.no_optimize,
            ).compile_full(mod)
        except KiCadErr as e:
            print(f"compile error (kicad backend): {e}", file=sys.stderr)
            return 1
        kicad_source = kicad_result.schematic
        if args.output:
            args.output.write_text(kicad_source, encoding="utf-8")
            _maybe_write_sidecar(args.output)
            print(f"wrote {args.output} "
                  f"({kicad_result.component_count} component(s), "
                  f"{kicad_result.label_count} label(s), "
                  f"libs: {', '.join(kicad_result.used_lib_ids)})",
                  file=sys.stderr)
        else:
            print(kicad_source, end="")
        return 0

    if args.target == "spice":
        # Phase E1 of the Math-to-Manufactured-PCB pipeline. Compile
        # an EML module to an ngspice-compatible netlist. By
        # convention: const names starting with R/C/L/V/I become
        # SPICE components; the const's unit annotation `[a:b]`
        # carries the net pair. See spice_backend.py for the v1
        # baseline + deferred features (MOSFETs, op-amps, .SUBCKT
        # bodies — slated for E1.5).
        from software.backends.spice_backend import (
            SpiceBackend, CompileError as SpiceErr,
        )
        try:
            spice_result = SpiceBackend(
                optimize=not args.no_optimize,
            ).compile_full(mod)
        except SpiceErr as e:
            print(f"compile error (spice backend): {e}", file=sys.stderr)
            return 1
        spice_source = spice_result.netlist
        if args.output:
            args.output.write_text(spice_source, encoding="utf-8")
            _maybe_write_sidecar(args.output)
            print(f"wrote {args.output} "
                  f"({spice_result.component_count} component(s), "
                  f"{spice_result.analysis_count} analysis line(s))",
                  file=sys.stderr)
        else:
            print(spice_source, end="")
        return 0

    if args.target == "zkproof":
        # Phase 1 of the Verification Network. Lower every scalar
        # function in the module to a fixed-gate ZK circuit and emit
        # a JSON document that downstream provers / verifiers consume.
        # The circuit hash is bound to the fingerprint module hash so
        # tamper-evidence flows from one to the other.
        from lang.fingerprint import fingerprint_module as _fp_mod
        from lang.zkproof import (
            CircuitCompileError as _ZkErr,
            canonical_circuit_hash,
            circuit_to_dict,
            compile_circuit,
        )
        # We compute the fingerprint for binding even when
        # --emit-fingerprint isn't set — the circuit needs it.
        _fp_for_zk = _fp or _fp_mod(mod)
        circuits: list[dict] = []
        skipped: list[tuple[str, str]] = []
        for fn in mod.functions:
            try:
                c = compile_circuit(fn)
            except Exception as exc:  # noqa: BLE001
                skipped.append((fn.name, str(exc)))
                continue
            circuits.append({
                "function":     fn.name,
                "circuit_hash": canonical_circuit_hash(c),
                "fingerprint_module_hash": _fp_for_zk.module_hash,
                "circuit":      circuit_to_dict(c),
            })
        bundle = {
            "spec":         "monogate-zkcircuit/v1",
            "module":       _fp_for_zk.module["name"],
            "module_hash":  _fp_for_zk.module_hash,
            "n_functions":  len(circuits),
            "n_skipped":    len(skipped),
            "skipped":      [{"fn": n, "reason": r} for n, r in skipped],
            "circuits":     circuits,
        }
        import json as _json
        payload = _json.dumps(bundle, indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(payload + "\n", encoding="utf-8")
            _maybe_write_sidecar(args.output)
            print(f"wrote {args.output} "
                  f"({len(circuits)} circuit(s), "
                  f"{len(skipped)} skipped)",
                  file=sys.stderr)
        else:
            sys.stdout.write(payload + "\n")
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
