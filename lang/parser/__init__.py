"""EML-lang parser.

Phase 1.2 of monogate-forge. See `lang/spec/EML_LANG_DESIGN.md`
section "Phase 1.2 Parser implementation" for the spec this
module implements.

Public surface:
    parse_file(path) -> EMLModule
    parse_source(text, source_file=...) -> EMLModule
    Parser, ParseError                  -- for advanced consumers

AST types:
    NodeKind, ASTNode
    EMLFunction, EMLConstant, EMLTypeAlias, EMLModule
    Param, Annotation, WhereClause
"""

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    BUILTIN_NAMES,
    BUILTIN_TO_KIND,
    EMLConstant,
    EMLFunction,
    EMLModule,
    EMLTypeAlias,
    EMLUnitDecl,
    NodeKind,
    Param,
    WhereClause,
)
from lang.parser.lexer import LexError, Token, tokenize
from lang.parser.parser import ParseError, Parser, parse_file, parse_source

__all__ = [
    "Annotation",
    "ASTNode",
    "BUILTIN_NAMES",
    "BUILTIN_TO_KIND",
    "EMLConstant",
    "EMLFunction",
    "EMLModule",
    "EMLTypeAlias",
    "EMLUnitDecl",
    "LexError",
    "NodeKind",
    "Param",
    "ParseError",
    "Parser",
    "Token",
    "WhereClause",
    "parse_file",
    "parse_source",
    "tokenize",
]
