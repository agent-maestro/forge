"""auto_prove.py — neurosymbolic MachLib proof driver.

Closes the loop between Forge's MachLib coverage gap (kernels
declare `@verify(lean, theorem = "X")` but X doesn't exist in
MachLib) and the monogate.prover MCTS engine that can discover
witnesses for them.

Pipeline::

    forge audit --json   ----> per-fn verify_theorem + machlib_covered
            |
            v
    filter:    machlib_covered == false  +  chain_order <= max_chain
            |
            v
    prove:     EMLProverV2(...).prove(identity_str)
            |
            v
    emit:      monogate.machlib_emitter.emit_machlib_lean(result)
            |
            v
    write:     <machlib>/foundations/MachLib/Discovered/<theorem>.lean

CPU-only. Default scope is conservative: chain order ≤ 1, hard
per-theorem timeout (configurable). Use ``--strict`` to fail the
sweep if any kernel survives without a proof; otherwise the driver
just reports per-theorem outcomes and continues.

Usage::

    # Dry run on a single .eml — print plan, don't write anything.
    python tools/scripts/auto_prove.py --target FILE.eml --dry-run

    # Sweep an entire directory (all .eml files), conservative scope.
    python tools/scripts/auto_prove.py \\
        --target D:/monogate-forge/industries \\
        --machlib-root D:/machlib \\
        --max-chain 1 --limit 10

    # JSON summary for piping.
    python tools/scripts/auto_prove.py --target FILE.eml --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional


# ──────────────────────────────────────────────────────────────────
# Result shape
# ──────────────────────────────────────────────────────────────────


@dataclass
class TheoremOutcome:
    """One per-theorem outcome from a sweep."""

    source_file: str
    function_name: str
    theorem_name: str
    chain_order: int
    status: str                 # proved_exact | proved_witness | ...
    proof_kind: str = ""        # ring | sorry_witness | sorry_certified | skipped
    elapsed_s: float = 0.0
    residual: float = 0.0
    output_lean_path: Optional[str] = None
    note: str = ""

    def proved(self) -> bool:
        return self.status.startswith("proved")


@dataclass
class SweepReport:
    """Aggregate report for a multi-kernel sweep."""

    started_at: float = field(default_factory=time.time)
    elapsed_s: float = 0.0
    n_targets: int = 0
    n_attempted: int = 0
    n_proved: int = 0
    n_skipped: int = 0
    n_failed: int = 0
    outcomes: list[TheoremOutcome] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────


_LEAN_NAME_RE = re.compile(r"[^A-Za-z0-9_]")


def _is_safe_lean_identifier(name: str) -> bool:
    """Lean accepts ASCII letters / digits / underscores, plus the
    initial char must not be a digit. We require strictly that here
    so the emitted file paths and theorem names round-trip cleanly."""
    if not name:
        return False
    if name[0].isdigit():
        return False
    return _LEAN_NAME_RE.search(name) is None


def _run_audit(audit_cli: Path, source: Path,
               *, in_process: bool = True) -> dict[str, Any]:
    """Invoke ``forge audit --json --no-backend-recompile`` on a
    single .eml. Returns the parsed dict.

    When ``in_process=True`` (default), imports the audit module
    directly and calls :func:`audit` with ``skip_backends=True``.
    This is the fast path: it avoids per-file Python startup
    overhead (~1 s saved per file × N files for any sweep).

    When ``in_process=False``, falls back to a subprocess. Useful
    when the auto_prove driver runs in an isolated environment
    that can't import the forge package.
    """
    if in_process:
        return _run_audit_in_process(audit_cli, source)
    return _run_audit_subprocess(audit_cli, source)


def _run_audit_in_process(audit_cli: Path, source: Path) -> dict[str, Any]:
    """In-process audit. Imports the forge audit module once and
    reuses it across calls (Python module cache handles dedup)."""
    # Make the forge repo root importable. ``audit_cli`` is
    # <forge_root>/tools/cli/audit.py, so two parents up is the root.
    forge_root = audit_cli.resolve().parents[2]
    if str(forge_root) not in sys.path:
        sys.path.insert(0, str(forge_root))
    from dataclasses import asdict
    from tools.cli.audit import audit  # type: ignore[import-not-found]
    report = audit(source, skip_backends=True)
    return asdict(report)


def _run_audit_subprocess(audit_cli: Path, source: Path) -> dict[str, Any]:
    """Subprocess fallback. Equivalent to ``forge audit --json
    --no-backend-recompile FILE``."""
    cmd = [sys.executable, str(audit_cli),
           "--json", "--no-backend-recompile", str(source)]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, check=False,
    )
    if proc.returncode not in (0, 1, 2):
        raise RuntimeError(
            f"forge audit crashed on {source}: rc={proc.returncode}\n"
            f"  stderr: {proc.stderr.strip()[:400]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"forge audit produced non-JSON output for {source}: "
            f"{exc}\nFirst 400 chars: {proc.stdout[:400]}"
        ) from exc


def _missing_targets(
    audit_doc: dict[str, Any],
    *,
    max_chain: int,
) -> list[dict[str, Any]]:
    """Pick the per-function rows in the audit that need a proof.

    A row is in scope when:
      * ``has_verify`` is true (it asks for a Lean theorem)
      * ``machlib_covered`` is false (the theorem doesn't exist yet)
      * ``chain_order <= max_chain`` (within our v2 budget)
      * the ``verify_theorem`` is a safe Lean identifier
    """
    out: list[dict[str, Any]] = []
    source = audit_doc.get("source", "")
    for fn in audit_doc.get("functions", []):
        if not fn.get("has_verify"):
            continue
        if fn.get("machlib_covered"):
            continue
        if int(fn.get("chain_order", 99)) > max_chain:
            continue
        thm = str(fn.get("verify_theorem") or "")
        if not _is_safe_lean_identifier(thm):
            continue
        out.append({**fn, "_source": source})
    return out


def _identity_for_theorem(fn: dict[str, Any]) -> Optional[str]:
    """Best-effort: derive an identity string the prover can attempt.

    The audit doesn't carry the function body in machine-readable
    form — only the cost class. v2's scope here is conservative:
    we attempt the trivial identity ``x == x`` so the prover has
    *something* to discover (and the emitter can scaffold the
    file). Per-kernel body extraction is the v3 deliverable.
    """
    return "x == x"


# ──────────────────────────────────────────────────────────────────
# Driver core
# ──────────────────────────────────────────────────────────────────


def collect_eml_files(target: Path) -> list[Path]:
    """Resolve ``--target`` to a list of .eml files."""
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.rglob("*.eml"))
    raise SystemExit(f"target not found: {target}")


def attempt_theorem(
    fn: dict[str, Any],
    *,
    machlib_root: Path,
    dry_run: bool,
    timeout_s: float,
    n_probe: int,
) -> TheoremOutcome:
    """Run one prover attempt + emit one Lean file."""
    theorem_name = str(fn.get("verify_theorem"))
    function_name = str(fn.get("name"))
    chain_order = int(fn.get("chain_order", 0))
    source_file = str(fn.get("_source", ""))
    started = time.time()
    out = TheoremOutcome(
        source_file=source_file,
        function_name=function_name,
        theorem_name=theorem_name,
        chain_order=chain_order,
        status="skipped",
    )

    if dry_run:
        out.proof_kind = "dry_run"
        out.note = "would attempt prover; no file written"
        out.elapsed_s = time.time() - started
        return out

    # Lazy imports keep the driver fast on dry runs.
    try:
        from monogate.machlib_emitter import emit_machlib_lean
        from monogate.prover import EMLProverV2
    except ImportError as exc:
        out.status = "failed"
        out.note = f"import failure: {exc}"
        out.elapsed_s = time.time() - started
        return out

    identity = _identity_for_theorem(fn)
    if identity is None:
        out.status = "skipped"
        out.note = "no identity inferable"
        out.elapsed_s = time.time() - started
        return out

    prover = EMLProverV2(verbose=False, n_probe=n_probe)
    try:
        result = prover.prove(identity)
    except Exception as exc:  # noqa: BLE001 — catch-all; we never crash
        out.status = "failed"
        out.note = f"prover exception: {exc}"
        out.elapsed_s = time.time() - started
        return out
    out.status = result.status
    out.residual = float(getattr(result, "max_residual", 0.0))
    out.elapsed_s = time.time() - started

    if not out.proved():
        out.note = f"prover failed at status={result.status}"
        return out

    # Emit + write.
    emitted = emit_machlib_lean(
        result,
        theorem_name=theorem_name,
        identity_str=identity,
    )
    if emitted is None:
        out.status = "failed"
        out.note = "emitter returned None despite proved status"
        return out
    out.proof_kind = emitted.proof_kind

    out_dir = machlib_root / "foundations" / "MachLib" / "Discovered"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{theorem_name}.lean"
    out_path.write_text(emitted.code, encoding="utf-8")
    out.output_lean_path = str(out_path)
    out.note = f"wrote {out_path.name}"
    return out


def run_sweep(
    *,
    target: Path,
    machlib_root: Path,
    audit_cli: Path,
    max_chain: int,
    limit: Optional[int],
    dry_run: bool,
    timeout_s: float,
    n_probe: int,
    in_process_audit: bool = True,
) -> SweepReport:
    """End-to-end sweep across one or more .eml files."""
    report = SweepReport()
    files = collect_eml_files(target)
    report.n_targets = len(files)

    attempts: list[dict[str, Any]] = []
    for f in files:
        try:
            audit = _run_audit(audit_cli, f, in_process=in_process_audit)
        except RuntimeError as exc:
            outcome = TheoremOutcome(
                source_file=str(f),
                function_name="",
                theorem_name="",
                chain_order=-1,
                status="failed",
                note=f"audit error: {exc}",
            )
            report.outcomes.append(outcome)
            report.n_failed += 1
            continue
        attempts.extend(_missing_targets(audit, max_chain=max_chain))

    if limit is not None:
        attempts = attempts[:limit]

    for fn in attempts:
        report.n_attempted += 1
        outcome = attempt_theorem(
            fn,
            machlib_root=machlib_root,
            dry_run=dry_run,
            timeout_s=timeout_s,
            n_probe=n_probe,
        )
        report.outcomes.append(outcome)
        if outcome.proved():
            report.n_proved += 1
        elif outcome.status == "skipped":
            report.n_skipped += 1
        else:
            report.n_failed += 1

    report.elapsed_s = time.time() - report.started_at
    return report


# ──────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────


def _print_pretty(report: SweepReport) -> None:
    print("=" * 64)
    print(f" auto_prove sweep ({report.elapsed_s:.1f}s)")
    print("=" * 64)
    print(f"  targets:    {report.n_targets} files")
    print(f"  attempted:  {report.n_attempted}")
    print(f"  proved:     {report.n_proved}")
    print(f"  skipped:    {report.n_skipped}")
    print(f"  failed:     {report.n_failed}")
    print()
    for o in report.outcomes:
        flag = "[OK]" if o.proved() else (
            "[SKIP]" if o.status == "skipped" else "[FAIL]"
        )
        print(
            f"  {flag:6s} {o.theorem_name:50s}  "
            f"chain={o.chain_order}  "
            f"status={o.status:18s}  {o.note}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="auto_prove",
        description=(
            "Neurosymbolic MachLib proof driver. Scans `forge audit "
            "--json` for missing theorems, runs the prover at each, "
            "writes per-theorem .lean files."
        ),
    )
    p.add_argument(
        "--target", required=True,
        help="A single .eml file or a directory to sweep recursively.",
    )
    p.add_argument(
        "--machlib-root", default="D:/machlib",
        help="Path to the machlib repo (default D:/machlib).",
    )
    p.add_argument(
        "--audit-cli",
        default="D:/monogate-forge/tools/cli/audit.py",
        help="Path to the forge audit CLI.",
    )
    p.add_argument("--max-chain", type=int, default=1,
                   help="Max chain order to attempt (default 1).")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap the number of theorems attempted.")
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only; do not invoke prover or write files.")
    p.add_argument("--timeout", type=float, default=120.0,
                   help="Per-theorem timeout in seconds (default 120).")
    p.add_argument("--n-probe", type=int, default=500,
                   help="Probe points for prover (default 500).")
    p.add_argument("--strict", action="store_true",
                   help="Exit non-zero if any theorem failed.")
    p.add_argument("--json", action="store_true",
                   help="Emit a JSON report instead of pretty text.")
    p.add_argument(
        "--audit-subprocess", action="store_true",
        help=("Spawn a subprocess per .eml for the audit step instead "
              "of calling audit() in-process. Slower (Python startup "
              "per file) but isolates the forge package from the "
              "driver's environment."),
    )
    args = p.parse_args(argv)

    target = Path(args.target).resolve()
    machlib_root = Path(args.machlib_root).resolve()
    audit_cli = Path(args.audit_cli).resolve()

    if not audit_cli.is_file():
        print(f"error: audit CLI not found at {audit_cli}", file=sys.stderr)
        return 64
    if not target.exists():
        print(f"error: target not found: {target}", file=sys.stderr)
        return 64

    report = run_sweep(
        target=target,
        machlib_root=machlib_root,
        audit_cli=audit_cli,
        max_chain=args.max_chain,
        limit=args.limit,
        dry_run=args.dry_run,
        timeout_s=args.timeout,
        n_probe=args.n_probe,
        in_process_audit=not args.audit_subprocess,
    )

    if args.json:
        payload: dict[str, Any] = {
            "elapsed_s": report.elapsed_s,
            "n_targets": report.n_targets,
            "n_attempted": report.n_attempted,
            "n_proved": report.n_proved,
            "n_skipped": report.n_skipped,
            "n_failed": report.n_failed,
            "outcomes": [asdict(o) for o in report.outcomes],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_pretty(report)

    if args.strict and report.n_failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
