"""forge audit -- one-command scan of a .eml file.

Reports four things in a single pass:

  1. Per-function profile (chain order, cost class, drift risk, eml_depth).
  2. Backend compatibility matrix across all 21 Forge backends
     (in-memory compile; no files written).
  3. MachLib theorem coverage for every @verify(lean, theorem="X") block.
  4. Aggregate health-check (pass/skip/fail counts + status verdict).

Usage:

    python tools/cli/audit.py path/to/file.eml             # text report
    python tools/cli/audit.py path/to/file.eml --json      # machine-readable
    python tools/cli/audit.py path/to/file.eml --quiet     # exit code only

Exit codes:
    0 -- all backends compile, all theorems found, no warnings
    1 -- one or more backends failed
    2 -- one or more @verify theorems missing from MachLib
    3 -- both above
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

# Make the repo root importable when invoked directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# UTF-8 stdout/stderr on Windows for Lean characters in @verify blocks.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# ─── Backend invocations ──────────────────────────────────────────
#
# Each entry is (display_name, invocation_fn). The invocation_fn takes
# a parsed+profiled module and returns the emitted source as a string,
# or raises. Hardware backends need an FPGAAllocator plan; Lean uses
# compile_module rather than compile; Coq/Isabelle return "" when no
# @verify block is present (which we treat as skip).


def _ada_invoke(mod):
    from software.backends.ada_backend import AdaBackend
    art = AdaBackend(optimize=True).compile_full(mod)
    return art.spec + "\n" + art.body


def _make_software_invoke(module_path: str, class_suffix: str):
    def _invoke(mod):
        backend_mod = __import__(module_path, fromlist=["*"])
        cls = next(
            getattr(backend_mod, a) for a in dir(backend_mod)
            if a.endswith(class_suffix) and isinstance(getattr(backend_mod, a), type)
            and hasattr(getattr(backend_mod, a), "compile")
        )
        return cls(optimize=True).compile(mod)
    return _invoke


def _make_hdl_invoke(module_path: str, class_name: str):
    def _invoke(mod):
        from hardware.allocator import FPGAAllocator
        backend_mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(backend_mod, class_name)
        plan = FPGAAllocator().allocate(mod, constraints={"target": "xilinx.artix7"})
        return cls(optimize=True).compile(mod, plan)
    return _invoke


def _lean_invoke(mod):
    from software.verification.lean.LeanBackend import LeanBackend
    return LeanBackend(optimize=True).compile_module(mod) or ""


def _make_optional_verify_invoke(module_path: str, class_name: str):
    """Coq / Isabelle: return '' when no @verify block; treat as skip."""
    def _invoke(mod):
        backend_mod = __import__(module_path, fromlist=[class_name])
        cls = getattr(backend_mod, class_name)
        out = cls(optimize=True).compile(mod)
        return out or ""
    return _invoke


_BACKEND_INVOKERS: list[tuple[str, Callable, bool]] = [
    # (name, invoker, requires_any_verify)
    ("c",             _make_software_invoke("software.backends.c_backend",      "Backend"), False),
    ("cpp",           _make_software_invoke("software.backends.cpp_backend",    "Backend"), False),
    ("rust",          _make_software_invoke("software.backends.rust_backend",   "Backend"), False),
    ("python",        _make_software_invoke("software.backends.python_backend", "Backend"), False),
    ("go",            _make_software_invoke("software.backends.go_backend",     "Backend"), False),
    ("java",          _make_software_invoke("software.backends.java_backend",   "Backend"), False),
    ("kotlin",        _make_software_invoke("software.backends.kotlin_backend", "Backend"), False),
    ("llvm",          _make_software_invoke("software.backends.llvm_backend",   "Backend"), False),
    ("wasm",          _make_software_invoke("software.backends.wasm_backend",   "Backend"), False),
    ("matlab",        _make_software_invoke("software.backends.matlab_backend", "Backend"), False),
    ("spice",         _make_software_invoke("software.backends.spice_backend",  "Backend"), False),
    ("ros2",          _make_software_invoke("software.backends.ros2_backend",   "Backend"), False),
    ("autosar",       _make_software_invoke("software.backends.autosar_backend","Backend"), False),
    ("aadl",          _make_software_invoke("software.backends.aadl_backend",   "Backend"), False),
    ("ada",           _ada_invoke, False),
    ("verilog",       _make_hdl_invoke("hardware.hdl_gen.verilog_backend",       "VerilogBackend"), False),
    ("systemverilog", _make_hdl_invoke("hardware.hdl_gen.systemverilog_backend", "SystemVerilogBackend"), False),
    ("vhdl",          _make_hdl_invoke("hardware.hdl_gen.vhdl_backend",          "VHDLBackend"), False),
    ("chisel",        _make_hdl_invoke("hardware.hdl_gen.chisel_backend",        "ChiselBackend"), False),
    ("lean",          _lean_invoke, True),
    ("coq",           _make_optional_verify_invoke("software.verification.coq.coq_backend",          "CoqBackend"), True),
    ("isabelle",      _make_optional_verify_invoke("software.verification.isabelle.isabelle_backend", "IsabelleBackend"), True),
]


# ─── MachLib theorem index ────────────────────────────────────────

_MACHLIB_FOUNDATIONS = Path("D:/machlib/foundations/MachLib")


def _index_machlib_theorems() -> set[str]:
    """One-time scan of MachLib/*.lean for every theorem/axiom/lemma name."""
    if not _MACHLIB_FOUNDATIONS.is_dir():
        return set()

    names: set[str] = set()
    pattern = re.compile(
        r"^\s*(?:theorem|lemma|axiom)\s+([A-Za-z_][A-Za-z0-9_']*)",
        re.MULTILINE,
    )
    for lean_file in _MACHLIB_FOUNDATIONS.rglob("*.lean"):
        try:
            text = lean_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        names.update(m.group(1) for m in pattern.finditer(text))
    return names


# ─── Audit data shapes ────────────────────────────────────────────


@dataclass
class FunctionProfile:
    name: str
    chain_order: int | None
    cost_class: str | None
    eml_depth: int | None
    fp16_drift_risk: str | None
    has_verify: bool
    verify_theorem: str | None
    machlib_covered: bool | None  # None when no theorem name


@dataclass
class BackendResult:
    name: str
    status: str  # "ok" / "skip" / "error"
    bytes_emitted: int = 0
    error: str | None = None


@dataclass
class AuditReport:
    source: str
    module: str
    n_functions: int
    n_constants: int
    n_types: int
    has_any_verify: bool
    functions: list[FunctionProfile] = field(default_factory=list)
    backends: list[BackendResult] = field(default_factory=list)
    machlib_total_indexed: int = 0
    summary: dict = field(default_factory=dict)


# ─── Audit logic ──────────────────────────────────────────────────


def _profile_functions(mod, machlib_index: set[str]) -> tuple[list[FunctionProfile], bool]:
    """Pull per-function profile + verify annotation theorem names."""
    out: list[FunctionProfile] = []
    any_verify = False
    for fn in mod.functions:
        prof = fn.profile or {}
        verify_theorem: str | None = None
        for ann in getattr(fn, "annotations", []) or []:
            if getattr(ann, "kind", "") == "verify":
                args = getattr(ann, "args", {}) or {}
                # Annotation args use positional key `0` for the prover
                # name and named key `theorem` for the theorem id.
                prover = args.get(0) or args.get("prover")
                if (
                    prover in (None, "lean")
                    and "theorem" in args
                    and not verify_theorem
                ):
                    verify_theorem = str(args["theorem"]).strip().strip('"')
                any_verify = True
        covered: bool | None
        if verify_theorem is None:
            covered = None
        else:
            covered = verify_theorem in machlib_index

        out.append(
            FunctionProfile(
                name=fn.name,
                chain_order=prof.get("chain_order"),
                cost_class=prof.get("cost_class"),
                eml_depth=prof.get("eml_depth"),
                fp16_drift_risk=prof.get("fp16_drift_risk"),
                has_verify=verify_theorem is not None,
                verify_theorem=verify_theorem,
                machlib_covered=covered,
            )
        )
    return out, any_verify


def _try_backends(mod, has_verify: bool) -> list[BackendResult]:
    """Run every registered backend in-memory; capture pass/skip/fail."""
    results: list[BackendResult] = []
    for name, invoke, requires_verify in _BACKEND_INVOKERS:
        if requires_verify and not has_verify:
            results.append(
                BackendResult(name=name, status="skip",
                              error="no @verify(lean) blocks")
            )
            continue
        try:
            artifact = invoke(mod)
            if not artifact:
                # Coq / Isabelle return empty string when there's
                # nothing to prove — treat as skip.
                results.append(
                    BackendResult(name=name, status="skip",
                                  error="backend produced empty output")
                )
                continue
            results.append(
                BackendResult(name=name, status="ok",
                              bytes_emitted=len(artifact))
            )
        except ImportError as e:
            results.append(
                BackendResult(name=name, status="skip",
                              error=f"backend not installed: {e}")
            )
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            # Hardware backends correctly refuse modules lacking any
            # @target(fpga, ...) function — that is by design, not a
            # backend bug, so we surface it as `skip`, not `error`.
            if "No @target(fpga" in msg or "no @target(fpga" in msg:
                results.append(
                    BackendResult(name=name, status="skip",
                                  error="no @target(fpga) function")
                )
            else:
                results.append(
                    BackendResult(name=name, status="error",
                                  error=f"{type(e).__name__}: {e}")
                )
    return results


def audit(source_path: Path,
          *, skip_backends: bool = False) -> AuditReport:
    """Run the full audit on a parsed .eml file.

    When ``skip_backends`` is ``True``, the 21-backend compile matrix
    is skipped and ``backends`` is left empty. Useful for downstream
    drivers (auto_prove, machlib coverage sweeps) that only consume
    the per-function profile + MachLib coverage and don't care about
    backend health — typically ~10x faster end-to-end since the
    backend matrix dominates audit wall-clock.
    """
    if not source_path.is_file():
        raise FileNotFoundError(f"{source_path} does not exist")

    from lang.parser import parse_file
    from lang.profiler import Profiler

    mod = parse_file(source_path)
    Profiler().profile_module(mod)

    machlib_index = _index_machlib_theorems()
    functions, any_verify = _profile_functions(mod, machlib_index)
    backends: list[BackendResult] = (
        [] if skip_backends else _try_backends(mod, any_verify)
    )

    n_ok = sum(1 for b in backends if b.status == "ok")
    n_skip = sum(1 for b in backends if b.status == "skip")
    n_err = sum(1 for b in backends if b.status == "error")

    n_fns_with_verify = sum(1 for f in functions if f.has_verify)
    n_fns_covered = sum(1 for f in functions if f.machlib_covered is True)
    n_fns_missing = sum(1 for f in functions if f.machlib_covered is False)

    return AuditReport(
        source=str(source_path),
        module=mod.name or "(unnamed)",
        n_functions=len(mod.functions),
        n_constants=len(mod.constants),
        n_types=len(mod.types),
        has_any_verify=any_verify,
        functions=functions,
        backends=backends,
        machlib_total_indexed=len(machlib_index),
        summary={
            "backends_ok": n_ok,
            "backends_skip": n_skip,
            "backends_error": n_err,
            "fns_with_verify": n_fns_with_verify,
            "fns_machlib_covered": n_fns_covered,
            "fns_machlib_missing": n_fns_missing,
        },
    )


# ─── Rendering ────────────────────────────────────────────────────


def render_text(report: AuditReport) -> str:
    out: list[str] = []
    out.append(f"# forge audit  --  {report.module}")
    out.append(f"# source: {report.source}")
    out.append(f"# module: {report.n_functions} fn, "
               f"{report.n_constants} const, {report.n_types} type")
    out.append("")

    out.append("## per-function profile")
    if not report.functions:
        out.append("  (no functions)")
    for f in report.functions:
        bits = [
            f"chain={f.chain_order}",
            f"depth={f.eml_depth}",
            f"cost={f.cost_class}",
            f"drift={f.fp16_drift_risk}",
        ]
        out.append(f"  {f.name:32s}  " + "  ".join(bits))
        if f.has_verify:
            cov = (
                "OK" if f.machlib_covered
                else ("MISSING" if f.machlib_covered is False else "n/a")
            )
            out.append(f"      @verify(lean, theorem={f.verify_theorem!r})  -> machlib: {cov}")
    out.append("")

    out.append("## backend compatibility matrix")
    by_status: dict[str, list[str]] = {"ok": [], "skip": [], "error": []}
    for b in report.backends:
        by_status[b.status].append(b.name)
    out.append(f"  ok    ({len(by_status['ok']):2d}): {', '.join(by_status['ok'])}")
    out.append(f"  skip  ({len(by_status['skip']):2d}): {', '.join(by_status['skip'])}")
    out.append(f"  error ({len(by_status['error']):2d}): {', '.join(by_status['error'])}")
    if by_status["error"]:
        out.append("")
        out.append("  errors:")
        for b in report.backends:
            if b.status == "error":
                out.append(f"    {b.name:14s}  {b.error}")
    out.append("")

    out.append("## machlib theorem coverage")
    s = report.summary
    out.append(f"  indexed theorems in MachLib foundations: {report.machlib_total_indexed}")
    out.append(f"  fns with @verify(lean): {s['fns_with_verify']}")
    out.append(f"  covered:                {s['fns_machlib_covered']}")
    out.append(f"  missing:                {s['fns_machlib_missing']}")

    out.append("")
    verdict = "PASS"
    if s["backends_error"] > 0:
        verdict = "FAIL (backend errors)"
    elif s["fns_machlib_missing"] > 0:
        verdict = "WARN (missing MachLib theorems)"
    out.append(f"## verdict: {verdict}")
    return "\n".join(out)


# ─── CLI ──────────────────────────────────────────────────────────


def _exit_code(report: AuditReport) -> int:
    s = report.summary
    code = 0
    if s["backends_error"] > 0:
        code |= 1
    if s["fns_machlib_missing"] > 0:
        code |= 2
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge-audit",
        description="One-command scan of a .eml file: profile, backend "
                    "matrix, MachLib theorem coverage.",
    )
    parser.add_argument("source", type=Path, help="Path to a .eml source file")
    parser.add_argument("--json", action="store_true",
                        help="Emit a machine-readable JSON report.")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress all output; exit code carries verdict.")
    parser.add_argument(
        "--no-backend-recompile", "--skip-backends",
        action="store_true",
        dest="skip_backends",
        help=("Skip the 21-backend compile matrix. ~10x faster; useful "
              "for downstream drivers (auto_prove etc.) that only need "
              "per-function profile + MachLib coverage. Exit code in "
              "this mode reflects MachLib coverage only — backend "
              "health is not checked."),
    )
    args = parser.parse_args(argv)

    try:
        report = audit(args.source, skip_backends=args.skip_backends)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if args.quiet:
        return _exit_code(report)
    if args.json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        print(render_text(report))
    return _exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
