"""Phase E.4: Refinement -> Isabelle/HOL hypothesis emitter.

Converts a ``Refinement`` (binder + predicate ASTNode) into an Isabelle
hypothesis string, ready to splice into a theorem signature.

Key decisions (mirroring Phase D Lean pattern):
  1. **Binder alpha-renaming**: The refinement ``Real{p | P(p)}`` on
     parameter ``x`` substitutes ``p`` with ``x`` in ``P`` before
     emitting. No fresh Isabelle binder is introduced.
  2. **abs rewrite**: ``abs(binder) <= k`` is lowered to
     ``(-k <= x \\<and> x <= k)`` and ``abs(binder) < k`` to
     ``(-k < x \\<and> x < k)`` per the HOL order axiom convention.
     The split form works directly with linarith.
  3. **Conjunction shape**: A predicate ``P && Q`` on the same binder
     is emitted as a single conjunction ``(P[binder:=x] \\<and> Q[binder:=x])``.
  4. **No external library deps**: all emitted terms use only operations
     available in Isabelle/HOL's Complex_Main.
"""

from __future__ import annotations

from lang.parser.ast_nodes import ASTNode, NodeKind, Refinement


# ── ASTNode substitution ──────────────────────────────────────────────


def _substitute_var(node: ASTNode, old_name: str, new_name: str) -> ASTNode:
    """Return a new ASTNode tree with every VAR named ``old_name`` replaced
    by a VAR named ``new_name``. Immutable: the original tree is not modified.
    """
    if node.kind == NodeKind.VAR and node.value == old_name:
        return ASTNode(
            kind=NodeKind.VAR,
            value=new_name,
            children=[],
            type_annotation=node.type_annotation,
            chain_constraint=node.chain_constraint,
            line=node.line,
            col=node.col,
        )
    new_children = [_substitute_var(c, old_name, new_name) for c in node.children]
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )


# ── Isabelle expression emitter (predicate sub-language) ─────────────
# Handles the refinement predicate sub-language:
# <, <=, ==, !=, >=, >, &&, ||, !, +, -, *, /, abs.
# No transcendentals.


def _emit_pred(node: ASTNode) -> str:
    """Render a refinement-predicate ASTNode as an Isabelle expression string.

    Handles the abs-rewrite: ``abs(x) <= k`` is lowered to the
    conjunction ``(-k <= x \\<and> x <= k)`` so the HOL order axioms
    and linarith apply directly.
    """
    kind = node.kind

    # ── abs(x) OP k rewrite ──────────────────────────────────────────
    # Must be checked before the generic BINOP arm.
    if kind == NodeKind.BINOP and node.value in ("<=", "<"):
        left, right = node.children[0], node.children[1]
        if left.kind == NodeKind.ABS and len(left.children) == 1:
            inner = _emit_pred(left.children[0])
            k_str = _emit_pred(right)
            op = node.value
            if op == "<=":
                return f"(-{k_str} <= {inner} \\<and> {inner} <= {k_str})"
            else:  # "<"
                return f"(-{k_str} < {inner} \\<and> {inner} < {k_str})"

    if kind == NodeKind.LITERAL:
        v = node.value
        if isinstance(v, bool):
            return "True" if v else "False"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            if v == 0.0:
                return "0"
            if v == 1.0:
                return "1"
            s = repr(v)
            if "." not in s and "e" not in s and "E" not in s:
                s += ".0"
            return s
        raise ValueError(f"Unsupported literal: {v!r}")

    if kind == NodeKind.VAR:
        return str(node.value)

    if kind == NodeKind.UNARYOP:
        sub = _emit_pred(node.children[0])
        if node.value == "-":
            return f"(- {sub})"
        if node.value == "!":
            return f"(\\<not> {sub})"
        raise ValueError(f"Unsupported unary op: {node.value!r}")

    if kind == NodeKind.BINOP:
        left = _emit_pred(node.children[0])
        right = _emit_pred(node.children[1])
        op = node.value
        isa_op = {
            "&&": "\\<and>",
            "||": "\\<or>",
            "!=": "\\<noteq>",
            "==": "=",
        }.get(op, op)
        return f"({left} {isa_op} {right})"

    if kind == NodeKind.ABS:
        inner = _emit_pred(node.children[0])
        return f"(abs {inner})"

    # min / max allowed in predicate sub-language
    if kind == NodeKind.CALL:
        args = " ".join(_emit_pred(c) for c in node.children)
        return f"({node.value} {args})"

    raise ValueError(f"Unsupported node kind in Isabelle refinement predicate: {kind}")


# ── Public API ────────────────────────────────────────────────────────


def refinement_to_hypothesis(refinement: Refinement, var_name: str) -> str:
    """Convert a ``Refinement`` to an Isabelle assumption string.

    The refinement's binder is alpha-renamed to ``var_name`` before
    emission (decision 1: substitute the binder in-place, do not
    introduce a fresh Isabelle binder).

    Parameters
    ----------
    refinement : Refinement
        The Phase C refinement annotation (binder + predicate).
    var_name : str
        The EML parameter name that this refinement annotates.

    Returns
    -------
    str
        An Isabelle proposition string, suitable for use as an
        assumption: ``(h_<var_name>: "<prop>")``.

    Examples
    --------
    >>> ref = Refinement(binder="p", predicate=<0.0 <= p && p <= 1.0>)
    >>> refinement_to_hypothesis(ref, "x")
    '(h_x: "(0 <= x \\\\<and> x <= 1)")'
    """
    renamed_pred = _substitute_var(refinement.predicate, refinement.binder, var_name)
    prop = _emit_pred(renamed_pred)
    return f'(h_{var_name}: "{prop}")'
