"""SuperBEST routing -- selects which 23-family operator to emit
for each EML node so total node count is minimized.

Patents #01 (SuperBEST), #02 (hybrid routing), #08 (cost-branch
selection). The default optimizer for every backend.

SCAFFOLD. Real implementation lands in Phase 1.3 / Phase 2.1.
"""

from __future__ import annotations

from lang.parser.ast_nodes import ASTNode


def route_superbest(node: ASTNode) -> ASTNode:
    """Rewrite an AST subtree using SuperBEST routing.

    Returns a new AST whose semantics match the input but whose
    node count is minimal under the 23-operator family +
    declared chain-order constraints.

    Today: identity (passes the AST through unchanged). Will be
    replaced with the real router in Phase 2.1 once the AST and
    eml-cost SuperBEST table are wired together.
    """
    return node
