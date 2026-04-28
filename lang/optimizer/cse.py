"""Common sub-expression elimination.

Reuses the SymPy CSE pass against the canonical AST -> SymPy
conversion. Saves redundant computation when a sub-expression
appears multiple times.

SCAFFOLD.
"""

from __future__ import annotations

from lang.parser.ast_nodes import ASTNode


def apply_cse(node: ASTNode) -> ASTNode:
    """Hoist repeated sub-expressions into `let` bindings."""
    return node
