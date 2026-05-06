"""v0.5 deprecation lint: transcendental functions in `requires` clauses.

Walks each function's ``requires`` predicates, finds any that contain a
transcendental function call, and returns a ``LintWarning`` for each such
clause.  ``assume`` clauses are never flagged (they are the migration target).

Transcendental set
------------------
sin, cos, tan, asin, acos, atan, sinh, cosh, tanh, exp, ln, sqrt

pow special rule
----------------
``pow(b, e)`` is only flagged when ``e`` is NOT an integer literal.
``pow(x, 2)`` and ``pow(x, -2)`` are integer-exponent -- not flagged.
``pow(x, 0.5)`` is a non-integer float -- flagged (equivalent to sqrt).

Scope
-----
Only ``requires`` predicates are inspected.  Body expressions, ``ensures``
clauses, and ``assume`` clauses are intentionally excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind


# ── NodeKinds that are transcendental ────────────────────────────────────────

_TRANSCENDENTAL_KINDS: frozenset[NodeKind] = frozenset({
    NodeKind.SIN,
    NodeKind.COS,
    NodeKind.TAN,
    NodeKind.ASIN,
    NodeKind.ACOS,
    NodeKind.ATAN,
    NodeKind.SINH,
    NodeKind.COSH,
    NodeKind.TANH,
    NodeKind.EXP,
    NodeKind.LN,
    NodeKind.SQRT,
    # POW is handled separately via _is_transcendental_pow
})


@dataclass
class LintWarning:
    """A single lint warning emitted by the transcendental-requires linter.

    Attributes
    ----------
    message : str
        Human-readable warning text.  Includes the transcendental name,
        source location, and migration suggestions.
    line : int
        1-indexed source line of the ``requires`` predicate head token.
    col : int
        1-indexed source column of the predicate head token.
    fn_name : str
        Name of the enclosing function.
    transcendental_name : str
        The specific transcendental function that triggered the warning.
    """
    message: str
    line: int
    col: int
    fn_name: str
    transcendental_name: str


# ── Internal helpers ──────────────────────────────────────────────────────────


def _is_integer(value: object) -> bool:
    """Return True if *value* is an integer or a float equal to an integer."""
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return value == int(value)
    return False


def _is_integer_exponent(node: ASTNode) -> bool:
    """Return True if *node* represents an integer value as an exponent.

    Handles:
    - LITERAL with int or float-equal-to-int value (e.g. ``2``, ``0``)
    - UNARYOP('-', [LITERAL(int)]) -- i.e. negative integer (e.g. ``-2``)
    """
    if node.kind == NodeKind.LITERAL:
        return _is_integer(node.value)
    if (node.kind == NodeKind.UNARYOP and node.value == "-"
            and len(node.children) == 1):
        child = node.children[0]
        if child.kind == NodeKind.LITERAL:
            return _is_integer(child.value)
    return False


def _is_transcendental_pow(node: ASTNode) -> bool:
    """Return True if this POW node has a non-integer exponent."""
    if node.kind != NodeKind.POW:
        return False
    if len(node.children) < 2:
        # Malformed node -- treat conservatively as non-transcendental
        return False
    exponent = node.children[1]
    return not _is_integer_exponent(exponent)


def _find_transcendental(node: ASTNode) -> Optional[tuple[str, int, int]]:
    """Depth-first search for the first transcendental call in *node*.

    Returns
    -------
    (name, line, col) of the first transcendental node found, or None.
    """
    # Direct hit
    if node.kind in _TRANSCENDENTAL_KINDS:
        return (node.value if node.value else node.kind.value, node.line, node.col)

    if node.kind == NodeKind.POW and _is_transcendental_pow(node):
        return ("pow", node.line, node.col)

    # Recurse into children
    for child in node.children:
        result = _find_transcendental(child)
        if result is not None:
            return result

    return None


def _make_warning(
    fn: EMLFunction,
    predicate: ASTNode,
    trans_name: str,
    trans_line: int,
    trans_col: int,
    source_file: str,
) -> LintWarning:
    """Build a ``LintWarning`` for a single offending requires clause."""
    # Use the transcendental node's location if available; fall back to
    # the predicate's location (which is the location of the enclosing op).
    line = trans_line if trans_line > 0 else predicate.line
    col = trans_col if trans_col > 0 else predicate.col

    loc = f"{source_file}:{line}:{col}" if source_file else f"{line}:{col}"

    message = (
        f"warning: {loc}: 'requires' clause uses transcendental function '{trans_name}'; "
        f"the refinement sub-language can't decide it. "
        f"Consider migrating to: "
        f"`assume (...)` -- if it's a hypothesis you trust, "
        f"or moving the check into the function body as a runtime assertion."
    )

    return LintWarning(
        message=message,
        line=line,
        col=col,
        fn_name=fn.name,
        transcendental_name=trans_name,
    )


# ── Public entry point ────────────────────────────────────────────────────────


def lint_transcendental_requires(
    mod: EMLModule,
) -> list[LintWarning]:
    """Walk every function's ``requires`` clauses and return lint warnings.

    Only ``requires`` predicates are inspected.  ``assume`` and ``ensures``
    clauses are ignored.

    Parameters
    ----------
    mod : EMLModule
        The parsed (and optionally unit-checked) module.

    Returns
    -------
    list[LintWarning]
        One entry per ``requires`` clause that contains a transcendental
        function.  Empty when no issues are found.
    """
    warnings: list[LintWarning] = []
    source_file = mod.source_file or ""

    for fn in mod.functions:
        for predicate in fn.requires:
            result = _find_transcendental(predicate)
            if result is not None:
                trans_name, trans_line, trans_col = result
                warnings.append(
                    _make_warning(
                        fn=fn,
                        predicate=predicate,
                        trans_name=trans_name,
                        trans_line=trans_line,
                        trans_col=trans_col,
                        source_file=source_file,
                    )
                )

    return warnings
