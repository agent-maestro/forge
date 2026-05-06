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
class EMLUnitDecl:
    """A `unit NAME = <unit_expr>;` declaration.

    `base_exponents` is an 8-tuple of integer exponents in SI base-unit
    order: (m, kg, s, A, K, mol, cd, rad).  For example:
      - Hz = s^-1          -> (0, 0, -1, 0, 0, 0, 0, 0)
      - N  = kg*m*s^-2     -> (1, 1, -2, 0, 0, 0, 0, 0)

    `scale` is a float multiplier relative to the canonical base
    combination.  For SI-coherent units (Hz, N, Pa, …) scale == 1.0.
    For prefixed or non-SI units (km, kHz, deg) scale != 1.0.
    """
    name: str
    base_exponents: tuple  # length-8 tuple of ints: (m, kg, s, A, K, mol, cd, rad)
    scale: float = 1.0
    line: int = 0
    col: int = 0


@dataclass
class Param:
    """A function parameter."""
    name: str
    type_name: str        # "Real" / "f64" / "u8" / etc. Or alias.
    unit_expr: Optional[str] = None
    """Source text of the bracketed unit annotation, e.g. "Hz", "m/s^2",
    or None when no [unit] suffix is present."""
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
    return_unit_expr: Optional[str] = None
    """Source text of the return type's bracketed unit annotation,
    e.g. "Hz", "m/s^2", or None when no [unit] suffix is present."""

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

    imported_from: Optional[str] = None
    """When the function reached this module via `use stdlib::X;`,
    the resolver populates this with the joined path of the source
    module (e.g. "stdlib::control"). Local functions leave it None.
    The tree-shaker uses this to decide what's safe to drop."""

    is_extern: bool = False
    """When True the function is an opaque external declaration
    (`extern fn name(args) -> T`). Has no body; profiler / inliner /
    tree-shaker treat it as a leaf. Used by industry verticals
    (crypto, hardware) to declare primitives whose implementation
    lives outside EML-lang's reach."""


@dataclass
class EMLConstant:
    """A `const NAME: TYPE = EXPR` declaration."""
    name: str
    type_name: str
    value: ASTNode
    unit_expr: Optional[str] = None
    """Source text of the bracketed unit annotation, e.g. "Hz", or None."""
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
class EMLImport:
    """A `use stdlib::name;` declaration.

    `path` is the dotted path components in declaration order, e.g.
    ["stdlib", "math"] for `use stdlib::math;`. The loader resolves
    this to a file path via its search-path table.

    `only` is the optional selective-import list:
      `use stdlib::math;`                 -> only=None    (import all)
      `use stdlib::math::{lerp, hypot2};` -> only=["lerp", "hypot2"]
    The resolver uses this to filter merged constants / types /
    functions; names not in `only` stay in the imported module
    but don't enter the importing module's namespace.

    `aliases` maps original-name -> aliased-name for the
    `name as alias` form:
      `use stdlib::math::{lerp as interp, hypot2};`
        -> only=["lerp", "hypot2"], aliases={"lerp": "interp"}
    Names without an alias keep their original spelling.
    """
    path: list[str]
    only: list[str] | None = None
    aliases: dict[str, str] | None = None
    line: int = 0
    col: int = 0

    @property
    def joined(self) -> str:
        return "::".join(self.path)


@dataclass
class EMLModule:
    """The result of parsing one `.eml` file."""
    name: str
    """The `module <name>;` identifier, or "" if no module declaration."""
    imports: list[EMLImport] = field(default_factory=list)
    unit_decls: list[EMLUnitDecl] = field(default_factory=list)
    """Phase A: `unit NAME = <expr>;` declarations, in source order."""
    constants: list[EMLConstant] = field(default_factory=list)
    types: list[EMLTypeAlias] = field(default_factory=list)
    functions: list[EMLFunction] = field(default_factory=list)
    source_file: str = "<unknown>"
