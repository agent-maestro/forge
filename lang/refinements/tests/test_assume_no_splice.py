"""Phase G tests: assume clauses are never spliced into refinements.

RED phase (TDD). Tests the no-splice contract from the design spec:

  "assume clauses are NEVER folded into refinements, regardless of
   --strict-refinements flag state."

Also verifies the predicate language for assume is unrestricted (full expr).
"""

from __future__ import annotations

import pytest

from lang.parser import parse_source
from lang.refinements.auto_splice import auto_splice_module


# ── Core no-splice contract ───────────────────────────────────────────────────


def test_assume_abs_does_not_splice_strict_mode():
    """assume (abs(x) <= 1.0) NEVER splices into a refinement, strict ON."""
    src = """
fn f(x: Real) -> Real
assume (abs(x) <= 1.0)
{ x }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    assert len(fn.assumes) == 2 or len(fn.assumes) == 1, \
        "assume clause should still exist post-splice"
    # The real test: param x has no refinement
    assert fn.params[0].refinement is None, \
        "assume must not splice into parameter refinement"
    # And assumes list is non-empty (not consumed)
    assert len(fn.assumes) >= 1, "assume clause must not be consumed by splicer"


def test_assume_abs_does_not_splice_non_strict_mode():
    """assume (abs(x) <= 1.0) NEVER splices even when strict_mode=False."""
    src = """
fn f(x: Real) -> Real
assume (abs(x) <= 1.0)
{ x }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=False)
    fn = mod.functions[0]
    assert fn.params[0].refinement is None
    assert len(fn.assumes) >= 1


def test_requires_abs_still_splices_strict_mode():
    """Regression: requires (abs(x) <= 1.0) STILL splices (strict ON)."""
    src = """
fn f(x: Real) -> Real
requires (abs(x) <= 1.0)
{ x }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    # requires should splice: param gets refinement, fn.requires emptied
    assert fn.params[0].refinement is not None, \
        "requires still splices -- Phase G must not break this"
    assert len(fn.requires) == 0, "spliced requires clause should be removed"


def test_requires_not_spliced_non_strict_mode():
    """requires does NOT splice when strict_mode=False (pre-existing behaviour)."""
    src = """
fn f(x: Real) -> Real
requires (x > 0.0)
{ x }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=False)
    fn = mod.functions[0]
    # In non-strict mode, requires stays in fn.requires
    assert len(fn.requires) == 1, "requires must stay when strict_mode=False"
    assert fn.params[0].refinement is None


def test_multiple_assume_none_splice():
    """Multiple assume clauses: none splice, all remain in fn.assumes."""
    src = """
fn f(x: Real, y: Real) -> Real
assume (x > 0.0)
assume (y < 100.0)
assume (x < y)
{ x + y }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    assert len(fn.assumes) == 3, "All 3 assume clauses must remain"
    for p in fn.params:
        assert p.refinement is None, "No parameter should get refinement from assume"


# ── assume with transcendental -- no-splice ───────────────────────────────────


def test_assume_transcendental_not_spliced():
    """assume (sqrt(x) > 0) -- transcendental, never spliced."""
    src = """
fn f(x: Real) -> Real
assume (sqrt(x) > 0.0)
{ sqrt(x) }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    assert len(fn.assumes) == 1
    assert fn.params[0].refinement is None


def test_assume_multi_var_not_spliced():
    """Multi-variable assume -- stays in fn.assumes, no refinement created."""
    src = """
fn f(x: Real, y: Real) -> Real
assume (x + y > 0.0)
{ x * y }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    assert len(fn.assumes) == 1
    for p in fn.params:
        assert p.refinement is None


# ── Mixed requires + assume: requires still splices, assume does not ──────────


def test_mixed_requires_splices_assume_does_not():
    """Mixed: requires splices, assume stays as-is."""
    src = """
fn f(x: Real, y: Real) -> Real
requires (x > 0.0)
assume (y != 0.0)
{ x / y }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    # requires (x > 0.0): single-var, splices onto x
    x_param = next(p for p in fn.params if p.name == "x")
    assert x_param.refinement is not None, "requires on x must splice"
    assert len(fn.requires) == 0, "spliced requires removed"
    # assume (y != 0.0): stays
    assert len(fn.assumes) == 1, "assume clause must not be consumed"
    y_param = next(p for p in fn.params if p.name == "y")
    assert y_param.refinement is None, "assume must not splice onto y"
