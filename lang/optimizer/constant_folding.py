"""Constant folding -- evaluate any sub-expression whose inputs
are all numeric literals at compile time.

Reduces both runtime cost and downstream FPGA resource demand
(folded constants don't need MAC units).

SCAFFOLD.
"""

from __future__ import annotations

from lang.parser.ast_nodes import ASTNode


def fold_constants(node: ASTNode) -> ASTNode:
    """Bottom-up: replace constant-only sub-expressions with their
    literal value."""
    return node
