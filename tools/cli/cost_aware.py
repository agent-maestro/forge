"""``eml-compile --cost-aware`` orchestrator.

For each function in a source, convert the body to SymPy, profile it
via :func:`eml_cost.analyze`, and (if the baseline violates user
constraints) brute-force search the corpus of known SuperBEST
routings via :func:`eml_cost.find_siblings` for cheaper algebraic
alternatives.

v1 scope (explicit):

  * Constraints are EML-cost-profile attributes
    (``max_chain_order``, ``max_eml_depth``).
  * The "search" is :func:`eml_cost.find_siblings` over the prebuilt
    SuperBEST corpus -- no rewriting, no SAT, no equality saturation.
  * The output is a *recommendation* report; we never silently
    rewrite the function. Pick the form yourself based on the table.

What v1 does NOT do (deferred to v2):

  * Direct FPGA-resource constraints (``--max-luts``, ``--max-dsps``,
    ``--max-latency``). Mapping a sibling SymPy expression back
    through FPGAAllocator requires a sympy_to_eml printer that
    doesn't exist yet. The chain-order / eml-depth ceilings are
    correlated proxies for FPGA cost (chain order drives transcendental
    nesting depth which dominates LUT count).
  * Auto-rewrite. Honest framing: a recommendation table beats a
    silent codegen change you didn't ask for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lang.parser.ast_nodes import EMLFunction, EMLModule


# ────────────────────────── Dataclasses ──────────────────────────


@dataclass(frozen=True)
class CostConstraints:
    max_chain_order: int | None = None
    max_eml_depth: int | None = None

    def violations(self, *, chain_order: int, eml_depth: int) -> list[str]:
        out: list[str] = []
        if (self.max_chain_order is not None
                and chain_order > self.max_chain_order):
            out.append(
                f"chain_order: {chain_order} > max {self.max_chain_order}"
            )
        if (self.max_eml_depth is not None
                and eml_depth > self.max_eml_depth):
            out.append(
                f"eml_depth: {eml_depth} > max {self.max_eml_depth}"
            )
        return out


@dataclass(frozen=True)
class FunctionCostReport:
    fn_name: str
    status: str   # "ok" | "violates" | "skipped"
    reason: str = ""
    baseline_chain_order: int | None = None
    baseline_eml_depth: int | None = None
    baseline_cost_class: str = ""
    violations: tuple[str, ...] = field(default_factory=tuple)
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    recommended_form: dict[str, Any] | None = None


@dataclass(frozen=True)
class CostAwareReport:
    source: Path
    constraints: CostConstraints
    per_function: tuple[FunctionCostReport, ...]

    @property
    def all_ok(self) -> bool:
        return all(r.status != "violates" for r in self.per_function)


# ────────────────────────── Per-function ────────────────────────


def _baseline_profile(fn: EMLFunction) -> tuple[int, int, str, Any] | None:
    """Convert fn body to SymPy, then run eml_cost.analyze on it.

    Returns (chain_order, eml_depth, cost_class, sympy_expr) or None
    if the body can't be converted (multi-statement, tuple return,
    etc.). The pre-existing Profiler skip-tier matches.
    """
    from lang.profiler.ast_to_sympy import convert_function_body

    try:
        conv = convert_function_body(fn)
    except Exception:  # noqa: BLE001
        return None
    sympy_expr = getattr(conv, "expression", None)
    if sympy_expr is None:
        return None
    try:
        from eml_cost import analyze
        ar = analyze(sympy_expr)
    except Exception:  # noqa: BLE001
        return None
    chain = int(ar.pfaffian_r)
    depth = int(ar.eml_depth)
    cclass = f"p{chain}-d{depth}"
    return chain, depth, cclass, sympy_expr


def _search_siblings(
    sympy_expr: Any, *, k: int, constraints: CostConstraints,
) -> list[dict[str, Any]]:
    """Return cheaper siblings that satisfy constraints, sorted by distance."""
    from eml_cost import find_siblings

    try:
        sibs = find_siblings(sympy_expr, k=k)
    except Exception:  # noqa: BLE001
        return []

    out: list[dict[str, Any]] = []
    for s in sibs:
        prof = s.profile
        # PfaffianProfile uses (r, degree, width); AnalyzeResult
        # used (pfaffian_r, eml_depth) -- they're the same axes,
        # different field names. Read both for safety.
        chain = int(getattr(prof, "r",
                             getattr(prof, "pfaffian_r", -1)))
        depth = int(getattr(prof, "degree",
                             getattr(prof, "eml_depth", -1)))
        violations = constraints.violations(
            chain_order=chain, eml_depth=depth,
        )
        if violations:
            continue   # candidate would also fail constraints
        out.append({
            "name": s.name,
            "domain": s.domain,
            "expression": str(s.expression),
            "cost_class": s.cost_class,
            "distance": float(s.distance),
            "chain_order": chain,
            "eml_depth": depth,
        })
    return out


def _recommendation(sympy_expr: Any) -> dict[str, Any] | None:
    from eml_cost import recommend_form
    try:
        rec = recommend_form(sympy_expr)
    except Exception:  # noqa: BLE001
        return None
    if rec is None:
        return None
    return {
        "family": rec.family,
        "canonical_form": str(rec.canonical_form),
        "digits_saved": float(getattr(rec, "digits_saved", 0.0) or 0.0),
        "honest_note": getattr(rec, "honest_note", "") or "",
    }


def cost_aware_for_function(
    fn: EMLFunction,
    *,
    constraints: CostConstraints,
    k: int = 10,
) -> FunctionCostReport:
    base = _baseline_profile(fn)
    if base is None:
        return FunctionCostReport(
            fn_name=fn.name, status="skipped",
            reason="body not convertible to SymPy expression",
        )
    chain, depth, cclass, sympy_expr = base
    base_violations = constraints.violations(
        chain_order=chain, eml_depth=depth,
    )

    if not base_violations:
        # Baseline already fits -- no search needed; still report
        # any recommended canonical form (numerical-stability hint).
        return FunctionCostReport(
            fn_name=fn.name, status="ok",
            baseline_chain_order=chain,
            baseline_eml_depth=depth,
            baseline_cost_class=cclass,
            recommended_form=_recommendation(sympy_expr),
        )

    candidates = _search_siblings(
        sympy_expr, k=k, constraints=constraints,
    )
    return FunctionCostReport(
        fn_name=fn.name, status="violates",
        baseline_chain_order=chain,
        baseline_eml_depth=depth,
        baseline_cost_class=cclass,
        violations=tuple(base_violations),
        candidates=tuple(candidates),
        recommended_form=_recommendation(sympy_expr),
    )


# ────────────────────────── Orchestrator ────────────────────────


def run(
    source: Path,
    *,
    max_chain_order: int | None = None,
    max_eml_depth: int | None = None,
    k: int = 10,
) -> CostAwareReport:
    from lang.parser import parse_file
    from lang.profiler import Profiler

    if not source.is_file():
        raise FileNotFoundError(f"source not found: {source}")

    constraints = CostConstraints(
        max_chain_order=max_chain_order,
        max_eml_depth=max_eml_depth,
    )

    mod: EMLModule = parse_file(source)
    Profiler().profile_module(mod)

    per_fn = tuple(
        cost_aware_for_function(fn, constraints=constraints, k=k)
        for fn in mod.functions
    )
    return CostAwareReport(
        source=source, constraints=constraints, per_function=per_fn,
    )


# ────────────────────────── Pretty print ────────────────────────


def format_report(report: CostAwareReport) -> str:
    lines: list[str] = []
    lines.append(f"--cost-aware: {report.source}")
    c = report.constraints
    if c.max_chain_order is None and c.max_eml_depth is None:
        lines.append("  constraints: <none>  "
                     "(report-only; nothing will be flagged as violating)")
    else:
        bits = []
        if c.max_chain_order is not None:
            bits.append(f"max_chain_order={c.max_chain_order}")
        if c.max_eml_depth is not None:
            bits.append(f"max_eml_depth={c.max_eml_depth}")
        lines.append(f"  constraints: {' '.join(bits)}")

    for r in report.per_function:
        lines.append("")
        if r.status == "skipped":
            lines.append(f"  [SKIP] {r.fn_name}: {r.reason}")
            continue
        if r.status == "ok":
            marker = "OK"
        else:
            marker = "FAIL"
        lines.append(
            f"  [{marker}] {r.fn_name}  "
            f"chain_order={r.baseline_chain_order}  "
            f"eml_depth={r.baseline_eml_depth}  "
            f"cost_class={r.baseline_cost_class}"
        )
        for v in r.violations:
            lines.append(f"      violates: {v}")
        if r.candidates:
            lines.append("      candidates (cheaper alternatives within constraints):")
            for cand in r.candidates[:5]:
                lines.append(
                    f"        - {cand['name']:<28} "
                    f"distance={cand['distance']:.3f}  "
                    f"r={cand['chain_order']}  "
                    f"d={cand['eml_depth']}  "
                    f"({cand['domain']})"
                )
                lines.append(
                    f"          {cand['expression']}"
                )
        elif r.status == "violates":
            lines.append(
                "      no constraint-satisfying siblings found "
                "(consider relaxing or rewriting by hand)"
            )
        if r.recommended_form is not None:
            rf = r.recommended_form
            lines.append(
                f"      recommend: {rf['family']} -> "
                f"{rf['canonical_form']}  "
                f"(digits_saved={rf['digits_saved']:.2f})"
            )

    summary = "OK" if report.all_ok else "FAIL"
    lines.append("")
    lines.append(f"--cost-aware: overall {summary}")
    return "\n".join(lines)
