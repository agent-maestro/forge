"""Core dataclass + helpers for `forge.blocks`.

Public surface (re-exported from `forge.blocks.__init__`):

  Block                  -- the pre-computed block dataclass
  make_block(name, src)  -- parse + profile + allocate at import time
  compose(a, b)          -- pipe-compose two blocks
  register(block)        -- add to the global registry
  get(name)              -- registry lookup
  list_blocks()          -- registry view
  BlockCompositionError  -- raised on shape / arity mismatches
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, List, Optional

from lang.parser.ast_nodes import ASTNode, EMLFunction, EMLModule, NodeKind
from lang.parser.parser import parse_source
from lang.profiler.profiler import Profiler


# ── Errors ────────────────────────────────────────────────────


class BlockCompositionError(Exception):
    """Raised when two blocks can't be composed (shape/arity/type mismatch)."""


# ── The dataclass ─────────────────────────────────────────────


@dataclass(frozen=True)
class Block:
    """A pre-verified EML computation block.

    Every field on this dataclass is computed once at module-import
    time and cached. The compiler's per-call work for an instance of
    a Block is a dict lookup -- no parsing, no profiling, no
    optimization, no allocation.

    Field reference
    ===============

    ``name``               human-readable identifier (e.g. "sigmoid")
    ``eml_tree``           the parsed AST body (a BLOCK NodeKind)
    ``chain_order``        Pfaffian chain order from the profiler
    ``node_count``         post-optimizer node count
    ``cost_class``         eml-cost classification (e.g. "p1-d2-w0-c0")
    ``arity``              number of inputs the block consumes
    ``parameters``         names of the block's parameters in order
    ``lean_theorem``       Lean 4 theorem statement string ("" if none)
    ``fpga_allocation``    flattened AllocationPlan (LUTs/DSPs/cycles)
    ``source``             original .eml source string (for debug + emit)
    ``function``           EMLFunction wrapper (for backend consumption)

    Composition
    ===========

    ``a >> b`` returns a new Block whose body substitutes ``b``'s
    single input with ``a``'s body. Chain order is ``max(a, b)``;
    node count is the sum.
    """

    name: str
    eml_tree: ASTNode
    chain_order: int
    node_count: int
    cost_class: str
    arity: int = 1
    parameters: tuple[str, ...] = ()
    lean_theorem: str = ""
    fpga_allocation: dict = field(default_factory=dict)
    source: str = ""
    function: Optional[EMLFunction] = None

    # ── Operators ─────────────────────────────────────────────

    def __rshift__(self, other: "Block") -> "Block":
        return compose(self, other)

    # ── Helpers ───────────────────────────────────────────────

    def to_module(self) -> EMLModule:
        """Wrap this block's `function` back into a single-fn EMLModule
        so any standard backend (CBackend, RustBackend, etc.) can emit
        it without seeing the underlying block plumbing.
        """
        if self.function is None:
            raise BlockCompositionError(
                f"Block {self.name!r} has no underlying function "
                f"(was it composed?)"
            )
        return EMLModule(
            name=self.name,
            functions=[self.function],
            source_file=f"<block:{self.name}>",
        )


# ── Registry ──────────────────────────────────────────────────


_REGISTRY: dict[str, Block] = {}


def register(block: Block) -> Block:
    """Add `block` to the global registry under its `name`. Idempotent
    on the same Block instance; rejects collisions with a different
    block carrying the same name."""
    existing = _REGISTRY.get(block.name)
    if existing is not None and existing is not block:
        raise ValueError(
            f"forge.blocks: duplicate registration for {block.name!r} "
            f"(existing {existing} vs {block})"
        )
    _REGISTRY[block.name] = block
    return block


def get(name: str) -> Block:
    """Look up a registered block. Raises KeyError if not registered."""
    if name not in _REGISTRY:
        raise KeyError(
            f"forge.blocks: no block named {name!r}. "
            f"Registered: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[name]


def list_blocks() -> List[Block]:
    """Return every registered block sorted by name."""
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


# ── Builder ───────────────────────────────────────────────────


def make_block(
    name: str,
    source: str,
    *,
    parameters: Optional[Iterable[str]] = None,
    lean_theorem: str = "",
    fpga_target: str = "xilinx.artix7",
    skip_allocation: bool = False,
) -> Block:
    """Parse, profile, optimize, allocate, and register an EML source
    string as a Block.

    Called at module-import time. Subsequent uses of the returned
    Block are O(1) -- no parsing, no profiling.

    `source` must define exactly one function. Its body becomes
    `eml_tree`, its parameters become `parameters` (override with the
    keyword if you want a different public spelling).

    `skip_allocation=True` skips the FPGA allocator -- useful for
    blocks that don't have an `@target(fpga, ...)` annotation, where
    the allocator would otherwise refuse to run.
    """
    mod = parse_source(source, source_file=f"<block:{name}>")
    Profiler().profile_module(mod)

    if len(mod.functions) != 1:
        raise ValueError(
            f"forge.blocks: block {name!r} must define exactly one "
            f"function (got {len(mod.functions)})"
        )
    fn = mod.functions[0]
    profile = fn.profile or {}

    # Run the optimizer once so the cached node count reflects the
    # post-optimization tree -- the compile path skips re-running it.
    from lang.optimizer import optimize_module
    optimized_mod = optimize_module(mod)
    fn = optimized_mod.functions[0]
    profile = fn.profile or profile

    fpga_alloc: dict = {}
    if not skip_allocation:
        fpga_alloc = _maybe_allocate(optimized_mod, fpga_target)

    param_names = (
        tuple(parameters) if parameters is not None
        else tuple(p.name for p in fn.params)
    )

    block = Block(
        name=name,
        eml_tree=fn.body if fn.body is not None else _empty_block(),
        chain_order=int(profile.get("chain_order", 0) or 0),
        node_count=int(profile.get("node_count", 0) or 0),
        cost_class=str(profile.get("cost_class", "?") or "?"),
        arity=len(fn.params),
        parameters=param_names,
        lean_theorem=lean_theorem,
        fpga_allocation=fpga_alloc,
        source=source,
        function=fn,
    )
    return register(block)


def _maybe_allocate(mod: EMLModule, target: str) -> dict:
    """Run the FPGA allocator if any function carries
    `@target(fpga, ...)`; otherwise return an empty dict."""
    has_fpga = any(
        a.kind == "target" and a.args.get(0) == "fpga"
        for fn in mod.functions
        for a in fn.annotations
    )
    if not has_fpga:
        return {}
    from hardware.allocator import FPGAAllocator
    plan = FPGAAllocator().allocate(mod, constraints={"target": target})
    return {
        "target_device":  plan.target_device,
        "luts":           plan.estimated_luts,
        "dsps":           plan.estimated_dsps,
        "bram_kb":        plan.estimated_bram_kb,
        "pipeline_depth": plan.pipeline_depth,
        "clock_mhz":      plan.clock_mhz,
        "throughput_msps": plan.throughput_msps,
        "transcendental_units": [
            {
                "op":              u.op,
                "count":           u.count,
                "sharing":         u.sharing,
                "precision_bits":  u.precision_bits,
            }
            for u in plan.transcendental_units
        ],
    }


def _empty_block() -> ASTNode:
    return ASTNode(kind=NodeKind.BLOCK, value=None, children=[])


# ── Composition ───────────────────────────────────────────────


def compose(a: Block, b: Block) -> Block:
    """Pipe-compose two blocks: ``a >> b`` is "feed a's output into b".

    Constraints
    ===========

    - ``b`` must have arity 1 (single input). Higher arities require
      a different combinator (e.g. parallel branches feeding a join).
    - ``a`` and ``b`` must each have a `function` attached so the
      composed block can be re-emitted; this is true for every block
      built via ``make_block``.

    Result
    ======

    The returned Block:

    - has ``chain_order = max(a.chain_order, b.chain_order)``
      (the type rule the compose-time check enforces).
    - has ``node_count = a.node_count + b.node_count``.
    - has ``arity = a.arity`` (composed block exposes a's inputs).
    - has ``parameters = a.parameters``.
    - is **not** auto-registered; call ``register(...)`` if you want
      it in the global registry.
    """
    if not isinstance(a, Block) or not isinstance(b, Block):
        raise BlockCompositionError(
            f"compose: expected Block instances, got {type(a)} and {type(b)}"
        )
    if b.arity != 1:
        raise BlockCompositionError(
            f"compose: rhs block {b.name!r} has arity {b.arity}; "
            f"compose only supports rhs arity 1 (use a join combinator "
            f"for multi-input rhs)."
        )

    a_expr = _final_expression(a.eml_tree, a.name)
    b_expr = _final_expression(b.eml_tree, b.name)
    substituted = _substitute_var(b_expr, b.parameters[0], a_expr)

    new_body = ASTNode(
        kind=NodeKind.BLOCK,
        value=None,
        children=[substituted],
    )
    new_chain = max(a.chain_order, b.chain_order)
    new_nodes = a.node_count + b.node_count

    composed = Block(
        name=f"{a.name}>>{b.name}",
        eml_tree=new_body,
        chain_order=new_chain,
        node_count=new_nodes,
        cost_class="composed",
        arity=a.arity,
        parameters=a.parameters,
        lean_theorem="",   # the composition's theorem must be derived separately
        fpga_allocation={},
        source=f"// composed: {a.name} >> {b.name}\n",
        function=_wrap_in_function(
            name=f"{a.name}_then_{b.name}".replace(">>", "_then_"),
            body=new_body,
            params=a.function.params if a.function is not None else [],
        ),
    )
    return composed


def _final_expression(body: ASTNode, block_name: str) -> ASTNode:
    """Extract the final return expression from a block body. Composition
    requires single-expression bodies -- LET bindings and control flow
    aren't supported in the rhs of compose because their evaluation
    semantics don't lift cleanly through substitution.
    """
    if body.kind != NodeKind.BLOCK:
        return body
    expression_children = [
        c for c in body.children
        if c.kind not in (
            NodeKind.LET, NodeKind.LET_MUT, NodeKind.ASSIGN,
            NodeKind.WHILE, NodeKind.EXPR_STMT,
        )
    ]
    if len(body.children) != len(expression_children):
        raise BlockCompositionError(
            f"compose: block {block_name!r} has LET / WHILE / ASSIGN "
            f"in its body -- compose only supports single-expression "
            f"blocks. Wrap the multi-statement block in a helper or "
            f"build the composition by hand."
        )
    if not expression_children:
        raise BlockCompositionError(
            f"compose: block {block_name!r} has no return expression"
        )
    return expression_children[-1]


def _substitute_var(
    node: ASTNode, var_name: str, replacement: ASTNode,
) -> ASTNode:
    """Replace every ``VAR(var_name)`` in ``node`` with a deep copy of
    ``replacement``. Pure-functional walk -- the input tree is not
    mutated."""
    if node.kind == NodeKind.VAR and node.value == var_name:
        return _deep_copy(replacement)
    new_children = [
        _substitute_var(c, var_name, replacement) for c in node.children
    ]
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=new_children,
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )


def _deep_copy(node: ASTNode) -> ASTNode:
    return ASTNode(
        kind=node.kind,
        value=node.value,
        children=[_deep_copy(c) for c in node.children],
        type_annotation=node.type_annotation,
        chain_constraint=node.chain_constraint,
        line=node.line,
        col=node.col,
    )


def _wrap_in_function(
    name: str,
    body: ASTNode,
    params: list,
) -> EMLFunction:
    """Wrap a composed body back into an EMLFunction so the result is
    consumable by every standard backend."""
    return EMLFunction(
        name=name,
        params=list(params),
        return_type="Real",
        body=body,
    )


# ── Convenience API ───────────────────────────────────────────


def replace_metadata(block: Block, **kwargs) -> Block:
    """Return a new Block with overridden metadata fields. Useful for
    pinning a different FPGA target on a shipped block without
    re-allocating from scratch."""
    return replace(block, **kwargs)
