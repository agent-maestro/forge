"""``eml-compile --generate-tests`` orchestrator.

For a single .eml source, walk every Real-only function and run it
through the existing `tools.equivalence.cross_target_check` against
auto-generated input vectors. The harness already handles
emit-to-temp-dir, build, run, and per-vector compare for each
backend; this module owns vector generation, function selection,
and pretty pass/fail reporting.

Vectors are seeded so repeat runs are deterministic. Functions with
non-Real parameters are skipped for v1 (would need range-aware
sampling for Int / Bool / etc.).

Exit / return-code policy:
  * 0  -- all functions matched on every available backend
  * 1  -- one or more functions disagreed on at least one backend
  * Toolchains that aren't on PATH (cargo, gcc) report
    `available=False` and do NOT fail the run -- partial coverage
    is honest coverage.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from lang.parser.ast_nodes import EMLFunction, EMLModule
from tools.equivalence import cross_target_check
from tools.equivalence.harness import EquivalenceReport


# ────────────────────────── Dataclass ──────────────────────────


@dataclass(frozen=True)
class GenTestsReport:
    source: Path
    n_functions_total: int
    n_functions_tested: int
    n_functions_skipped: int
    skipped: tuple[tuple[str, str], ...]   # (fn_name, reason)
    per_function: tuple[EquivalenceReport, ...] = field(default_factory=tuple)
    elapsed_s: float = 0.0

    @property
    def all_pass(self) -> bool:
        return all(r.overall_match for r in self.per_function)


# ────────────────────────── Vectors ────────────────────────────


def random_real_vectors(
    n_params: int,
    *,
    n_vectors: int,
    seed: int,
    lo: float = -10.0,
    hi: float = 10.0,
) -> list[tuple[float, ...]]:
    """Deterministic random samples in [lo, hi]^n_params."""
    rng = random.Random(seed)
    return [
        tuple(rng.uniform(lo, hi) for _ in range(n_params))
        for _ in range(n_vectors)
    ]


# ────────────────────────── Selection ──────────────────────────


def is_test_eligible(fn: EMLFunction) -> tuple[bool, str]:
    """Return (eligible, reason). Reason is empty when eligible."""
    if not fn.params:
        # Zero-arg function -> the random sampler emits empty tuples,
        # which still works and produces n_vectors evaluations of a
        # constant. Allow.
        return True, ""
    for p in fn.params:
        # Coerce common aliases: lang permits "Real" / "f64" / "f32";
        # treat any of those as Real-typed for sampling.
        t = (p.type_name or "").strip()
        if t.lower() not in {"real", "f64", "f32", "double", "float"}:
            return False, f"non-Real param {p.name}: {p.type_name}"
    rt = (fn.return_type or "").strip().lower()
    if rt not in {"real", "f64", "f32", "double", "float"}:
        return False, f"non-Real return: {fn.return_type}"
    return True, ""


# ────────────────────────── Orchestrator ───────────────────────


def generate_and_run(
    source: Path,
    *,
    n_vectors: int = 32,
    targets: tuple[str, ...] = ("rust", "c"),
    tolerance: float = 1e-9,
    seed: int = 0,
) -> GenTestsReport:
    """Run cross-target equivalence over every eligible function in `source`."""
    from lang.parser import parse_file
    from lang.profiler import Profiler

    if not source.is_file():
        raise FileNotFoundError(f"source not found: {source}")

    t_start = time.monotonic()
    mod: EMLModule = parse_file(source)
    Profiler().profile_module(mod)

    skipped: list[tuple[str, str]] = []
    reports: list[EquivalenceReport] = []
    n_total = len(mod.functions)

    for i, fn in enumerate(mod.functions):
        ok, reason = is_test_eligible(fn)
        if not ok:
            skipped.append((fn.name, reason))
            continue
        # Per-function deterministic seed so two functions don't
        # share their vector tables (which would mask vector-specific
        # bugs).
        per_fn_seed = seed * 1_000_003 + i
        vectors = random_real_vectors(
            len(fn.params),
            n_vectors=n_vectors,
            seed=per_fn_seed,
        )
        report = cross_target_check(
            source,
            fn.name,
            vectors,
            tolerance=tolerance,
            targets=targets,
        )
        reports.append(report)

    elapsed = time.monotonic() - t_start
    return GenTestsReport(
        source=source,
        n_functions_total=n_total,
        n_functions_tested=len(reports),
        n_functions_skipped=len(skipped),
        skipped=tuple(skipped),
        per_function=tuple(reports),
        elapsed_s=elapsed,
    )


# ────────────────────────── Pretty print ───────────────────────


def format_report(report: GenTestsReport) -> str:
    """Human-readable plain text. Caller writes to stdout / log."""
    lines: list[str] = []
    lines.append(f"--generate-tests: {report.source}")
    lines.append(
        f"  functions: {report.n_functions_total}  "
        f"tested: {report.n_functions_tested}  "
        f"skipped: {report.n_functions_skipped}  "
        f"({report.elapsed_s:.2f}s)"
    )
    if report.skipped:
        lines.append("  skipped:")
        for name, reason in report.skipped:
            lines.append(f"    - {name}: {reason}")

    for r in report.per_function:
        marker = "PASS" if r.overall_match else "FAIL"
        lines.append(
            f"  [{marker}] {r.function_name:<24} n={r.n_vectors}"
        )
        for tgt_name in sorted(r.targets):
            tgt = r.targets[tgt_name]
            if not tgt.available:
                lines.append(
                    f"      {tgt_name:<8} unavailable"
                    + (f" ({tgt.error})" if tgt.error else "")
                )
                continue
            if tgt.error:
                lines.append(
                    f"      {tgt_name:<8} ERROR  {tgt.error}"
                )
                continue
            lines.append(
                f"      {tgt_name:<8} ok  "
                f"max_abs={tgt.max_abs_err:.3e}  "
                f"max_rel={tgt.max_rel_err:.3e}"
            )

    summary = "PASS" if report.all_pass else "FAIL"
    lines.append(f"--generate-tests: overall {summary}")
    return "\n".join(lines)
