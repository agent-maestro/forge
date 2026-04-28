"""EML-lang parser.

Phase 1 of monogate-forge. See `lang/spec/EML_LANG_DESIGN.md`
section "Phase 1.2 Parser implementation" for the spec this
module implements.

Public surface (when complete):
    parse_file(path) -> list[EMLFunction]
    parse_source(text) -> list[EMLFunction]
"""

from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    NodeKind,
)

__all__ = ["ASTNode", "EMLFunction", "NodeKind"]
