"""AST node definitions for EML-lang.

Mirrors the design in `lang/spec/EML_LANG_DESIGN.md` section 1.2.
SCAFFOLD -- structure is final, behavior is TODO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeKind(Enum):
    CONST = "const"      # constant declaration
    VAR = "var"          # variable reference
    BINOP = "binop"      # binary arithmetic / comparison
    UNARYOP = "unaryop"  # unary negation
    CALL = "call"        # user function call
    LITERAL = "literal"  # numeric literal

    # Built-in transcendentals -- each lifts chain order
    EML = "eml"
    EXP = "exp"
    LN = "ln"
    SIN = "sin"
    COS = "cos"
    TAN = "tan"
    SQRT = "sqrt"
    POW = "pow"
    ABS = "abs"
    CLAMP = "clamp"

    # Statement kinds
    LET = "let"
    BLOCK = "block"


@dataclass
class ASTNode:
    """A node in the typed AST.

    `chain_constraint` is set on type-annotated nodes such as
    function return types and `let` bindings; the type checker
    enforces these against the inferred chain order.
    """
    kind: NodeKind
    value: Any = None
    children: list["ASTNode"] = field(default_factory=list)
    type_annotation: Optional[str] = None
    chain_constraint: Optional[dict] = None
    line: int = 0
    col: int = 0


@dataclass
class EMLFunction:
    """A top-level function declaration.

    `profile` is filled in by `lang.profiler.Profiler` after parsing.
    """
    name: str
    params: list[dict]
    """List of {"name": str, "type": str}."""
    return_type: str
    return_constraint: Optional[dict] = None
    """e.g. {"op": "<=", "value": 2}."""
    body: Optional[ASTNode] = None
    annotations: list[dict] = field(default_factory=list)
    """Each: {"kind": "target"|"verify", "args": {...}}."""
    requires: list[ASTNode] = field(default_factory=list)
    ensures: list[ASTNode] = field(default_factory=list)

    profile: Optional[dict] = None
    """Populated by Profiler. Keys: chain_order, max_path_r,
    eml_depth, cost_class, dynamics, node_count, stability_warnings,
    fp16_drift_risk, fpga_estimate."""


@dataclass
class EMLConstant:
    """A `const NAME: TYPE = EXPR` declaration."""
    name: str
    type_name: str
    value: ASTNode


@dataclass
class EMLTypeAlias:
    """A `type NAME = TYPE where CONSTRAINT` declaration."""
    name: str
    base_type: str
    constraint: Optional[dict] = None
    """e.g. {"op": "<=", "value": 2}."""
