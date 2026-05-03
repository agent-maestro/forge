"""Tests for ``tools/cli/cost_aware.py``."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.cli.cost_aware import (
    CostAwareReport,
    CostConstraints,
    FunctionCostReport,
    cost_aware_for_function,
    format_report,
    run,
)


# ──────── CostConstraints ────────

def test_constraints_no_violations_when_unset():
    c = CostConstraints()
    assert c.violations(chain_order=99, eml_depth=99) == []


def test_constraints_chain_order_violation():
    c = CostConstraints(max_chain_order=1)
    vs = c.violations(chain_order=2, eml_depth=3)
    assert any("chain_order" in v for v in vs)
    assert any("> max 1" in v for v in vs)


def test_constraints_depth_violation():
    c = CostConstraints(max_eml_depth=2)
    vs = c.violations(chain_order=0, eml_depth=5)
    assert any("eml_depth" in v for v in vs)


def test_constraints_both_violations():
    c = CostConstraints(max_chain_order=1, max_eml_depth=2)
    vs = c.violations(chain_order=3, eml_depth=4)
    assert len(vs) == 2


def test_constraints_at_boundary_passes():
    c = CostConstraints(max_chain_order=2, max_eml_depth=4)
    assert c.violations(chain_order=2, eml_depth=4) == []


# ──────── format_report ────────

def _ok_fn_report(name="trivial", chain=0, depth=1):
    return FunctionCostReport(
        fn_name=name, status="ok",
        baseline_chain_order=chain,
        baseline_eml_depth=depth,
        baseline_cost_class=f"p{chain}-d{depth}",
    )


def _violates_fn_report(name="bad", chain=2, depth=4, candidates=()):
    return FunctionCostReport(
        fn_name=name, status="violates",
        baseline_chain_order=chain,
        baseline_eml_depth=depth,
        baseline_cost_class=f"p{chain}-d{depth}",
        violations=("chain_order: 2 > max 1",),
        candidates=tuple(candidates),
    )


def test_format_report_ok():
    rpt = CostAwareReport(
        source=Path("foo.eml"),
        constraints=CostConstraints(max_chain_order=2),
        per_function=(_ok_fn_report("a", chain=1, depth=2),),
    )
    out = format_report(rpt)
    assert "[OK] a" in out
    assert "chain_order=1" in out
    assert "overall OK" in out


def test_format_report_fail_no_candidates():
    rpt = CostAwareReport(
        source=Path("foo.eml"),
        constraints=CostConstraints(max_chain_order=1),
        per_function=(_violates_fn_report("bad", chain=2, depth=4),),
    )
    out = format_report(rpt)
    assert "[FAIL] bad" in out
    assert "no constraint-satisfying siblings" in out
    assert "overall FAIL" in out


def test_format_report_fail_with_candidates():
    cand = {
        "name": "cosine_carrier",
        "domain": "signal",
        "expression": "cos(omega*t)",
        "cost_class": "p1-d2",
        "distance": 0.42,
        "chain_order": 1,
        "eml_depth": 2,
    }
    rpt = CostAwareReport(
        source=Path("foo.eml"),
        constraints=CostConstraints(max_chain_order=1),
        per_function=(_violates_fn_report(
            "bad", chain=2, depth=4, candidates=[cand],
        ),),
    )
    out = format_report(rpt)
    assert "candidates" in out
    assert "cosine_carrier" in out
    assert "distance=0.420" in out


def test_format_report_no_constraints_says_so():
    rpt = CostAwareReport(
        source=Path("foo.eml"),
        constraints=CostConstraints(),
        per_function=(_ok_fn_report(),),
    )
    out = format_report(rpt)
    assert "report-only" in out


def test_format_report_skipped_function():
    rpt = CostAwareReport(
        source=Path("foo.eml"),
        constraints=CostConstraints(max_chain_order=2),
        per_function=(FunctionCostReport(
            fn_name="weird", status="skipped",
            reason="body not convertible to SymPy expression",
        ),),
    )
    out = format_report(rpt)
    assert "[SKIP] weird" in out
    assert "not convertible" in out


# ──────── cost_aware_for_function (real eml_cost calls) ────────


def _parse_one(src: str):
    from lang.parser import parse_source
    from lang.profiler import Profiler
    mod = parse_source(src, "<test>")
    Profiler().profile_module(mod)
    return mod.functions[0]


def test_cost_aware_baseline_within_constraints_is_ok():
    fn = _parse_one(
        "module t;\nfn add(a: Real, b: Real) -> Real { a + b }\n"
    )
    c = CostConstraints(max_chain_order=2, max_eml_depth=10)
    r = cost_aware_for_function(fn, constraints=c, k=5)
    assert r.status == "ok"
    assert r.baseline_chain_order == 0
    assert r.violations == ()


def test_cost_aware_baseline_violates_triggers_search():
    # damped_wave: chain_order should be 2; constrain to 1 -> violates
    fn = _parse_one(
        "module t;\n"
        "fn damped(zeta: Real, omega: Real, t: Real) -> Real "
        "{ exp(-zeta * t) * sin(omega * t) }\n"
    )
    c = CostConstraints(max_chain_order=1)
    r = cost_aware_for_function(fn, constraints=c, k=5)
    assert r.status == "violates"
    assert r.baseline_chain_order >= 2
    assert any("chain_order" in v for v in r.violations)


def test_cost_aware_no_constraints_always_ok():
    fn = _parse_one(
        "module t;\n"
        "fn deep(x: Real) -> Real { exp(sin(cos(x))) }\n"
    )
    r = cost_aware_for_function(fn, constraints=CostConstraints(), k=3)
    assert r.status == "ok"


# ──────── run() integration ────────


def test_run_two_functions_one_violates(tmp_path):
    src = tmp_path / "mixed.eml"
    src.write_text("""\
module mixed;
fn cheap(a: Real, b: Real) -> Real { a + b }
fn deep(zeta: Real, omega: Real, t: Real) -> Real {
    exp(-zeta * t) * sin(omega * t)
}
""")
    report = run(src, max_chain_order=1, k=3)
    assert len(report.per_function) == 2
    by_name = {r.fn_name: r for r in report.per_function}
    assert by_name["cheap"].status == "ok"
    assert by_name["deep"].status == "violates"
    assert report.all_ok is False


def test_run_no_constraints_passes_everything(tmp_path):
    src = tmp_path / "trivial.eml"
    src.write_text(
        "module t;\nfn f(x: Real) -> Real { x * x + 1.0 }\n"
    )
    report = run(src, k=3)
    assert report.all_ok is True


def test_run_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        run(tmp_path / "ghost.eml", max_chain_order=1)
