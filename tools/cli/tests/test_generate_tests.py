"""Tests for ``tools/cli/generate_tests.py``.

The pure functions (vector RNG, eligibility, formatting) test on
every machine. The full `generate_and_run` integration runs Python
unconditionally; rust + c targets skip cleanly when their toolchains
aren't on PATH (existing behaviour of cross_target_check).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_source
from lang.parser.ast_nodes import EMLFunction, Param
from tools.cli.generate_tests import (
    GenTestsReport,
    format_report,
    generate_and_run,
    is_test_eligible,
    random_real_vectors,
)
from tools.equivalence.harness import EquivalenceReport, TargetResult


# ──────── random_real_vectors ────────

def test_vectors_shape_and_count():
    vs = random_real_vectors(3, n_vectors=5, seed=42)
    assert len(vs) == 5
    assert all(len(v) == 3 for v in vs)
    assert all(isinstance(x, float) for v in vs for x in v)


def test_vectors_seed_is_deterministic():
    a = random_real_vectors(2, n_vectors=10, seed=7)
    b = random_real_vectors(2, n_vectors=10, seed=7)
    c = random_real_vectors(2, n_vectors=10, seed=8)
    assert a == b
    assert a != c


def test_vectors_respect_range():
    vs = random_real_vectors(2, n_vectors=100, seed=1, lo=-1.0, hi=1.0)
    for v in vs:
        for x in v:
            assert -1.0 <= x <= 1.0


def test_vectors_zero_params_yields_empty_tuples():
    vs = random_real_vectors(0, n_vectors=4, seed=0)
    assert vs == [(), (), (), ()]


# ──────── is_test_eligible ────────

def _fake_fn(params: list[Param], rt: str = "Real") -> EMLFunction:
    # Tests of `is_test_eligible` only inspect params + return_type,
    # so the body/annotations/etc. can be the dataclass defaults.
    return EMLFunction(
        name="f", params=params, return_type=rt,
    )


def test_eligible_all_real_params():
    fn = _fake_fn([Param(name="x", type_name="Real")])
    ok, reason = is_test_eligible(fn)
    assert ok is True
    assert reason == ""


def test_eligible_zero_params():
    fn = _fake_fn([])
    ok, _ = is_test_eligible(fn)
    assert ok is True


def test_eligible_aliases_for_real():
    for tp in ("Real", "f64", "f32", "double", "Float", "DOUBLE"):
        fn = _fake_fn([Param(name="x", type_name=tp)])
        ok, _ = is_test_eligible(fn)
        assert ok, f"alias {tp!r} should be Real-equivalent"


def test_eligible_int_param_skipped():
    fn = _fake_fn([Param(name="n", type_name="Int")])
    ok, reason = is_test_eligible(fn)
    assert ok is False
    assert "non-Real" in reason
    assert "n" in reason


def test_eligible_non_real_return_skipped():
    fn = _fake_fn([Param(name="x", type_name="Real")], rt="Bool")
    ok, reason = is_test_eligible(fn)
    assert ok is False
    assert "non-Real return" in reason


# ──────── format_report ────────

def _fake_target(name="rust", available=True, error="",
                  max_abs=1e-12, max_rel=1e-12) -> TargetResult:
    return TargetResult(
        target=name, available=available, error=error,
        max_abs_err=max_abs, max_rel_err=max_rel,
        outputs=tuple(),
    )


def _fake_report(name: str, ok: bool) -> EquivalenceReport:
    if ok:
        targets = {
            "python": _fake_target("python"),
            "rust":   _fake_target("rust"),
            "c":      _fake_target("c"),
        }
    else:
        targets = {
            "python": _fake_target("python"),
            "rust":   _fake_target("rust", error="diff at v=3"),
        }
    return EquivalenceReport(
        function_name=name, n_vectors=10,
        targets=targets, overall_match=ok,
    )


def test_format_report_pass():
    rpt = GenTestsReport(
        source=Path("foo.eml"),
        n_functions_total=2,
        n_functions_tested=2,
        n_functions_skipped=0,
        skipped=(),
        per_function=(_fake_report("a", True), _fake_report("b", True)),
        elapsed_s=1.23,
    )
    out = format_report(rpt)
    assert "[PASS] a" in out
    assert "[PASS] b" in out
    assert "overall PASS" in out
    assert "1.23s" in out


def test_format_report_fail():
    rpt = GenTestsReport(
        source=Path("foo.eml"),
        n_functions_total=1,
        n_functions_tested=1,
        n_functions_skipped=0,
        skipped=(),
        per_function=(_fake_report("bad", False),),
        elapsed_s=0.05,
    )
    out = format_report(rpt)
    assert "[FAIL] bad" in out
    assert "overall FAIL" in out
    assert "ERROR" in out


def test_format_report_lists_skipped():
    rpt = GenTestsReport(
        source=Path("foo.eml"),
        n_functions_total=2,
        n_functions_tested=0,
        n_functions_skipped=2,
        skipped=(("with_int", "non-Real param n: Int"),
                  ("with_bool", "non-Real return: Bool")),
        per_function=(),
        elapsed_s=0.01,
    )
    out = format_report(rpt)
    assert "with_int" in out
    assert "with_bool" in out
    assert "non-Real" in out


# ──────── generate_and_run integration (Python ref only) ────────


def test_generate_and_run_python_reference_passes(tmp_path):
    src = tmp_path / "trivial.eml"
    src.write_text("""\
module trivial;

fn add(a: Real, b: Real) -> Real { a + b }

fn square(x: Real) -> Real { x * x }
""")
    # targets=() means: only the python reference runs (nothing to
    # cross-check against). The harness still produces a report for
    # each fn and overall_match is True when no available backend
    # disagrees.
    report = generate_and_run(
        src, n_vectors=8, targets=(), tolerance=1e-9, seed=1,
    )
    assert report.n_functions_total == 2
    assert report.n_functions_tested == 2
    assert report.n_functions_skipped == 0
    assert all(r.overall_match for r in report.per_function)


def test_generate_and_run_skips_int_params(tmp_path):
    src = tmp_path / "mixed.eml"
    src.write_text("""\
module mixed;
fn pure(x: Real) -> Real { x + 1.0 }
fn impure(x: Real, n: Int) -> Real { x }
""")
    report = generate_and_run(
        src, n_vectors=4, targets=(), tolerance=1e-9, seed=1,
    )
    assert report.n_functions_tested == 1
    assert report.n_functions_skipped == 1
    assert report.skipped[0][0] == "impure"


def test_generate_and_run_seeded_is_reproducible(tmp_path):
    src = tmp_path / "trivial.eml"
    src.write_text(
        "module trivial;\nfn f(x: Real) -> Real { x * x + 1.0 }\n"
    )
    a = generate_and_run(src, n_vectors=8, targets=(), seed=42)
    b = generate_and_run(src, n_vectors=8, targets=(), seed=42)
    # Same vectors, same outputs, same overall_match
    assert a.per_function[0].n_vectors == b.per_function[0].n_vectors
    assert a.all_pass == b.all_pass
    assert tuple(a.per_function[0].targets["python"].outputs) == \
        tuple(b.per_function[0].targets["python"].outputs)


def test_generate_and_run_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_and_run(tmp_path / "ghost.eml", n_vectors=1, targets=())
