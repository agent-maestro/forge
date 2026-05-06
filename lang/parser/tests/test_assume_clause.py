"""Phase G tests: `assume` keyword parsing.

RED phase (TDD) -- these tests are written BEFORE the implementation.
They will all fail until:
  1. `assume` is added to the KEYWORDS frozenset in lexer.py
  2. _parse_function() in parser.py is extended to recognise `assume` clauses
  3. EMLFunction.assumes list field is added in ast_nodes.py

Test plan:
  A. assume (P) parses; EMLFunction.assumes is populated.
  B. Multiple assume clauses preserve source order.
  C. assume (sqrt(x) > 0) parses cleanly (transcendentals allowed).
  D. Mixed requires and assume parse correctly, lists are independent.
  E. Parser idempotent: existing .eml files without `assume` parse unchanged.
  F. assume does NOT splice into refinements regardless of strict_refinements.
  G. require clauses still work exactly as before (backwards-compat).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_source, parse_file
from lang.parser.ast_nodes import EMLFunction, NodeKind


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


# ── A: single assume clause ───────────────────────────────────────────────────


def test_assume_single_clause_populates_assumes_list():
    """assume (x > 0) parses into EMLFunction.assumes with one entry."""
    src = """
fn scale(x: Real) -> Real
assume (x > 0.0)
{ x * 2.0 }
"""
    mod = parse_source(src)
    fn: EMLFunction = mod.functions[0]
    assert hasattr(fn, "assumes"), "EMLFunction must have 'assumes' field"
    assert len(fn.assumes) == 1, "Expected 1 assume clause"
    assert len(fn.requires) == 0, "requires must be empty when only assume used"


def test_assume_clause_parses_to_correct_ast():
    """assume (x > 0.0): predicate should be a BINOP with GT."""
    src = """
fn scale(x: Real) -> Real
assume (x > 0.0)
{ x }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    pred = fn.assumes[0]
    assert pred.kind == NodeKind.BINOP
    assert pred.value == ">"
    assert pred.children[0].kind == NodeKind.VAR
    assert pred.children[0].value == "x"


# ── B: multiple assume clauses preserve order ─────────────────────────────────


def test_multiple_assume_clauses_preserve_order():
    """Multiple assume clauses must appear in source order in fn.assumes."""
    src = """
fn f(x: Real, y: Real) -> Real
assume (x > 0.0)
assume (y < 1.0)
assume (x != y)
{ x + y }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.assumes) == 3, "Expected 3 assume clauses"
    # First: x > 0.0
    assert fn.assumes[0].value == ">"
    # Second: y < 1.0
    assert fn.assumes[1].value == "<"
    # Third: x != y
    assert fn.assumes[2].value == "!="


# ── C: transcendentals allowed in assume ──────────────────────────────────────


def test_assume_allows_sqrt_transcendental():
    """assume (sqrt(x) > 0) is legal -- assume uses FULL expression language."""
    src = """
fn use_sqrt(x: Real) -> Real
assume (sqrt(x) > 0.0)
{ sqrt(x) }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.assumes) == 1
    # The predicate tree must have a SQRT node on the left of GT
    pred = fn.assumes[0]
    assert pred.kind == NodeKind.BINOP
    assert pred.value == ">"
    assert pred.children[0].kind == NodeKind.SQRT


def test_assume_allows_sin_transcendental():
    """assume (sin(theta) >= -1.0) parses cleanly."""
    src = """
fn bounded_sin(theta: Real) -> Real
assume (sin(theta) >= -1.0)
{ sin(theta) }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.assumes) == 1
    pred = fn.assumes[0]
    assert pred.children[0].kind == NodeKind.SIN


def test_assume_allows_exp_transcendental():
    """assume (exp(x) > 0.0) parses -- exp is always positive."""
    src = """
fn safe_exp(x: Real) -> Real
assume (exp(x) > 0.0)
{ exp(x) }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.assumes) == 1


# ── D: mixed requires and assume parse correctly ──────────────────────────────


def test_mixed_requires_and_assume_parse_independently():
    """Mixed requires + assume: both lists populated, order preserved."""
    src = """
fn mixed(x: Real, y: Real) -> Real
requires (x > 0.0)
assume (y != 0.0)
requires (x < 100.0)
{ x / y }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.requires) == 2, "Expected 2 requires clauses"
    assert len(fn.assumes) == 1, "Expected 1 assume clause"
    # requires 0: x > 0.0
    assert fn.requires[0].value == ">"
    # assumes 0: y != 0.0
    assert fn.assumes[0].value == "!="
    # requires 1: x < 100.0
    assert fn.requires[1].value == "<"


def test_assume_before_requires_also_works():
    """assume before requires: order of list entries follows source order."""
    src = """
fn f(x: Real) -> Real
assume (x >= 0.0)
requires (x < 1.0)
{ x }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.assumes) == 1
    assert len(fn.requires) == 1
    assert fn.assumes[0].value == ">="
    assert fn.requires[0].value == "<"


def test_assume_requires_assume_ordering():
    """Interleaved assume/requires: both lists carry entries in source order."""
    src = """
fn f(a: Real, b: Real, c: Real) -> Real
assume (a > 0.0)
requires (b > 0.0)
assume (c > 0.0)
requires (b < 10.0)
{ a + b + c }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.assumes) == 2
    assert len(fn.requires) == 2
    # Assumes: a > 0.0, c > 0.0
    a_vars = [n.children[0].value for n in fn.assumes]
    assert a_vars == ["a", "c"]
    # Requires: b > 0.0, b < 10.0
    r_vars = [n.children[0].value for n in fn.requires]
    assert r_vars == ["b", "b"]


# ── E: parser idempotent on existing .eml files ───────────────────────────────


@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_existing_eml_files_parse_unchanged(filename: str):
    """Every existing .eml file must still parse -- assumes list should be empty."""
    mod = parse_file(EXAMPLES_DIR / filename)
    for fn in mod.functions:
        assert hasattr(fn, "assumes"), \
            f"{filename}/{fn.name}: missing 'assumes' attribute"
        assert fn.assumes == [], \
            f"{filename}/{fn.name}: 'assumes' should be empty for pre-G files"


def test_examples_pid_controller_unchanged():
    """pid_controller.eml has no assume clauses -- assumes list is empty."""
    pid = REPO_ROOT / "examples" / "pid_controller.eml"
    mod = parse_file(pid)
    for fn in mod.functions:
        assert fn.assumes == [], f"pid/{fn.name}: unexpected assume entries"


# ── F: assume does NOT splice into refinements (no-splice invariant) ──────────


def test_assume_not_spliced_into_refinement_strict_mode():
    """With strict_refinements=True: assume (abs(x) <= 1.0) must NOT splice."""
    from lang.refinements.auto_splice import auto_splice_module

    src = """
fn bounded(x: Real) -> Real
assume (x <= 1.0)
assume (x >= -1.0)
{ x }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    # assume clauses must remain in fn.assumes -- not promoted to refinements
    assert len(fn.assumes) == 2, "assume clauses must not be consumed by splicer"
    # The parameter x must have no refinement (assume doesn't splice)
    assert fn.params[0].refinement is None, \
        "assume must not splice into parameter refinement"


def test_requires_still_splices_in_strict_mode():
    """Regression: requires (x <= 1.0) STILL splices under strict_mode=True."""
    from lang.refinements.auto_splice import auto_splice_module

    src = """
fn bounded(x: Real) -> Real
requires (x <= 1.0)
{ x }
"""
    mod = parse_source(src)
    auto_splice_module(mod, strict_mode=True)
    fn = mod.functions[0]
    # The requires clause should splice -- param gets a refinement
    assert fn.params[0].refinement is not None, \
        "requires still splices in strict mode (backwards compat)"
    # And the requires list should be empty (consumed by splicer)
    assert len(fn.requires) == 0, "spliced requires clause should be removed"


# ── G: requires semantics unchanged ──────────────────────────────────────────


def test_requires_unchanged_single():
    """Existing `requires (P)` behaviour is unchanged by Phase G."""
    src = """
fn scale(x: Real) -> Real
requires (x > 0.0)
{ x * 2.0 }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.requires) == 1
    assert fn.assumes == []


def test_requires_unchanged_multiple():
    """Multiple requires clauses still all go into fn.requires."""
    src = """
fn clamp(x: Real) -> Real
requires (x >= -1.0)
requires (x <= 1.0)
{ x }
"""
    mod = parse_source(src)
    fn = mod.functions[0]
    assert len(fn.requires) == 2
    assert fn.assumes == []


def test_assume_is_a_keyword_not_ident():
    """After Phase G, `assume` must be tokenised as KEYWORD, not IDENT."""
    from lang.parser.lexer import tokenize
    tokens = tokenize("assume (x > 0)")
    # First token should be KEYWORD `assume`
    assert tokens[0].kind == "KEYWORD"
    assert tokens[0].value == "assume"
