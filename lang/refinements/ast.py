"""Phase C: Refinement AST node.

``Refinement`` is defined in ``lang.parser.ast_nodes`` (to avoid circular
imports) and re-exported here for callers that import from ``lang.refinements``.
"""

from lang.parser.ast_nodes import Refinement  # noqa: F401

__all__ = ["Refinement"]
