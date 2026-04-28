"""AST node definitions for EML-lang.

Mirrors the design in `lang/spec/EML_LANG_DESIGN.md` section 1.2,
extended with the constructs the 10 demo .eml files actually use:
tuple return types, `let mut`, assignment, `while`, boolean ops.

Every node carries source-location info (line, col) for error
messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class NodeKind(Enum):
    # Literals + variables
    LITERAL = "literal"
    VAR = "var"

    # Operations
    BINOP = "binop"           # arithmetic + comparison + boolean (op stored on node.value)
    UNARYOP = "unaryop"       # -x, !x
    CALL = "call"             # user function call (node.value = name)
    TUPLE = "tuple"           # (e1, e2, ...) -- for tuple returns

    # Built-in transcendentals (each lifts chain order)
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
    ASIN = "asin"
    ACOS = "acos"
    ATAN = "atan"
    SINH = "sinh"
    COSH = "cosh"
    TANH = "tanh"

    # Statements
    LET = "let"               # immutable; node.value = name, children=[expr]
    LET_MUT = "let_mut"       # mutable; same shape
    ASSIGN = "assign"         # to mut binding; node.value = name, children=[expr]
    WHILE = "while"           # children=[cond, body_block]
    BLOCK = "block"           # children=[stmts...; final_expr]
    EXPR_STMT = "expr_stmt"   # children=[expr]


# Built-in function names — used by the lexer for keyword classification
# and by the parser to dispatch to the right NodeKind.
BUILTIN_NAMES: frozenset[str] = frozenset({
    "exp", "ln", "sin", "cos", "tan", "sqrt", "pow", "eml",
    "abs", "clamp", "asin", "acos", "atan", "sinh", "cosh", "tanh",
})

BUILTIN_TO_KIND: dict[str, NodeKind] = {
    "exp": NodeKind.EXP, "ln": NodeKind.LN,
    "sin": NodeKind.SIN, "cos": NodeKind.COS, "tan": NodeKind.TAN,
    "sqrt": NodeKind.SQRT, "pow": NodeKind.POW, "eml": NodeKind.EML,
    "abs": NodeKind.ABS, "clamp": NodeKind.CLAMP,
    "asin": NodeKind.ASIN, "acos": NodeKind.ACOS, "atan": NodeKind.ATAN,
    "sinh": NodeKind.SINH, "cosh": NodeKind.COSH, "tanh": NodeKind.TANH,
}


@dataclass
class ASTNode:
    """A node in the typed AST.

    `value` is per-NodeKind: literal value, variable / call / let name,
    binop / unaryop string, etc.

    `children` are sub-expressions or sub-statements.

    `chain_constraint` is set on type-annotated nodes such as function
    return types; the type checker enforces these against the inferred
    chain order.

    `line` / `col` are the source location of the head token (1-indexed).
    """
    kind: NodeKind
    value: Any = None
    children: list["ASTNode"] = field(default_factory=list)
    type_annotation: Optional[str] = None
    chain_constraint: Optional[dict] = None
    line: int = 0
    col: int = 0


# ── Top-level declarations ────────────────────────────────────────────


@dataclass
class Param:
    """A function parameter."""
    name: str
    type_name: str        # "Real" / "f64" / "u8" / etc. Or alias.
    line: int = 0
    col: int = 0


@dataclass
class Annotation:
    """`@target(...)` or `@verify(...)`."""
    kind: str             # "target" | "verify"
    args: dict            # parsed arg list -- positional under int keys, kw by name
    line: int = 0
    col: int = 0


@dataclass
class WhereClause:
    """One entry in a function's `where` list."""
    kind: str             # "chain_order" | "domain" | "precision"
    op: Optional[str] = None        # "<=" / "<" / "==" / ">=" / ">" / "!="
    value: Any = None     # int for chain_order, ASTNode for domain, float for precision
    line: int = 0
    col: int = 0


@dataclass
class EMLFunction:
    """A top-level `fn` declaration."""
    name: str
    params: list[Param]
    return_type: str
    """Plain type name. For tuples, use `return_tuple_types` (and this
    field will be the empty string)."""
    return_tuple_types: list[str] = field(default_factory=list)
    """When the function returns a tuple, this is the list of element
    types and `return_type` is "" -- mutually exclusive with `return_type`."""
    return_constraint: Optional[dict] = None
    """Per the alias-level `where chain_order <op> N` constraint, if
    the return type is an alias such as `StableSignal`. {"op": "<=",
    "value": 2}."""
    where_clauses: list[WhereClause] = field(default_factory=list)
    body: Optional[ASTNode] = None
    """A BLOCK node containing the function body."""
    annotations: list[Annotation] = field(default_factory=list)
    requires: list[ASTNode] = field(default_factory=list)
    ensures: list[ASTNode] = field(default_factory=list)
    line: int = 0
    col: int = 0

    profile: Optional[dict] = None
    """Populated by Profiler in Phase 1.3. Keys: chain_order,
    max_path_r, eml_depth, cost_class, dynamics, node_count,
    stability_warnings, fp16_drift_risk, fpga_estimate."""


@dataclass
class EMLConstant:
    """A `const NAME: TYPE = EXPR` declaration."""
    name: str
    type_name: str
    value: ASTNode
    line: int = 0
    col: int = 0


@dataclass
class EMLTypeAlias:
    """A `type NAME = TYPE [where CONSTRAINT]` declaration."""
    name: str
    base_type: str
    constraint: Optional[dict] = None  # {"op": "<=", "value": 2}
    line: int = 0
    col: int = 0


@dataclass
class EMLModule:
    """The result of parsing one `.eml` file."""
    name: str
    """The `module <name>;` identifier, or "" if no module declaration."""
    constants: list[EMLConstant] = field(default_factory=list)
    types: list[EMLTypeAlias] = field(default_factory=list)
    functions: list[EMLFunction] = field(default_factory=list)
    source_file: str = "<unknown>"
