"""EVM gas estimator for Solidity-emitted EML functions.

Walks the EML AST summing per-node gas costs, returns a single
integer estimate per function. Used by the Solidity backend to
inject a NatSpec @dev line above each emitted function so a
caller can see "this function costs ~1.9k gas" without needing
to deploy + run Foundry's gas-bench.

Cost model
----------
- Cheap ops (PUSH/POP/MLOAD/ADD/SUB/comparisons): 3 gas
- MUL/DIV/SDIV/MOD: 5 gas
- POW (iterative, rough): 60 gas
- Builtin transcendentals are annotated with the PRBMath SD59x18
  override cost — the stub emitted by the backend reverts, so
  the estimate assumes the override pattern is in place. Numbers
  come from the PRBMath gas table at
  https://github.com/PaulRBerg/prb-math (commit-pinned to a
  recent tag; see the GAS_REFERENCES dict at the bottom).
- Function entry/exit (JUMP + selector dispatch): 100 gas

Rounded to the nearest 50 gas in the user-facing string so the
estimate doesn't pretend to be tighter than it is. Foundry's own
gas-bench is the canonical signal once the user is at deploy
time; this estimator's job is to surface the right order of
magnitude during editing.
"""

from __future__ import annotations


from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind


# ─── per-node gas costs ───────────────────────────────────────────

# Base function dispatch + selector cost. EVM charges 21000 base
# gas per transaction; that's a property of the call, not the
# function, so we exclude it. JUMPDEST + JUMP for internal calls
# is ~100; the selector dispatch on `external` callsites adds
# another ~200. Stay conservative and round up.
FUNCTION_OVERHEAD = 200

# Arithmetic / boolean op costs by binop string. EVM opcodes:
#   ADD/SUB/AND/OR/XOR/LT/GT/EQ/ISZERO  = 3 gas
#   MUL/DIV/SDIV/MOD/SMOD               = 5 gas
#   SIGNEXTEND                          = 5 gas
#   LE/GE/NE compile to two opcodes (LT/GT/EQ + ISZERO)
_BINOP_COST: dict[str, int] = {
    "+": 3, "-": 3,
    "*": 5, "/": 5, "%": 5,
    "<": 3, ">": 3, "==": 3,
    "<=": 6, ">=": 6, "!=": 6,
    "&&": 3, "||": 3,
}

# Built-in transcendentals -- assume PRBMath SD59x18 override.
# Stub costs (revert) would dominate everything else; the
# realistic deployment uses the override pattern, so we model
# that.
_BUILTIN_COST: dict[NodeKind, int] = {
    NodeKind.EXP:   3500,
    NodeKind.LN:    6000,
    NodeKind.SIN:   5000,
    NodeKind.COS:   5000,
    NodeKind.TAN:   7000,
    NodeKind.SQRT:  1000,
    NodeKind.POW:  10000,
    NodeKind.ABS:     30,
    NodeKind.CLAMP:   60,   # min(max(x, lo), hi) -- 2 compares + 2 selects
    NodeKind.ASIN:  7000,
    NodeKind.ACOS:  7000,
    NodeKind.ATAN:  6000,
    NodeKind.SINH:  7000,
    NodeKind.COSH:  7000,
    NodeKind.TANH:  7000,
    NodeKind.EML:   3500,   # `eml` is the canonical exp-family op
}

# Cheap stack / memory ops. Literals push a value onto the stack
# (3 gas); variables read from memory or stack (3 gas). Local
# bindings cost an MSTORE/MLOAD round-trip we model at 6.
_LITERAL_COST = 3
_VAR_COST = 3
_LET_COST = 6
_CALL_COST = 100      # internal function call (JUMP)
_RETURN_COST = 3

# User-callable names that the EML parser leaves as CALL nodes
# (rather than the BUILTIN_TO_KIND dispatch) but which a Solidity
# implementation will route through PRBMath. Charged at the
# matching transcendental cost. Names sourced from
# lang/spec/stdlib/math.eml + ml.eml.
_NAMED_TRANSCENDENTAL_COST: dict[str, int] = {
    "log":     6000,   # natural log alias for ln
    "log2":    6000,
    "log10":   6000,
    "log_b":   7000,
    "exp2":    3500,
    "exp10":   3500,
    "hypot2":   500,   # sqrt of polynomial -- ~sqrt cost
    "hypot3":   600,
    "lerp":      30,   # affine combination
    "sigmoid": 7000,   # 1/(1+exp(-x))
    "softplus":7000,   # ln(1+exp(x))
    "tanh":    7000,   # also a NodeKind.TANH builtin, but ml stdlib has shadow
    "gelu":   12000,   # tanh + arithmetic, expensive
    "swish":   8000,   # sigmoid + mul
    "relu":      30,   # max(0, x)
    "leaky_relu":50,
}


# ─── public API ───────────────────────────────────────────────────

def estimate_function_gas(fn: EMLFunction) -> int:
    """Return the estimated EVM gas cost of one EML function as
    rendered by the Solidity backend. Includes function-entry
    overhead + every node in the body. Does NOT include the
    21000-gas transaction base or the per-byte calldata cost.
    """
    if fn.body is None:
        return FUNCTION_OVERHEAD
    return FUNCTION_OVERHEAD + _walk(fn.body)


def format_gas_estimate(gas: int) -> str:
    """Render a gas count for human consumption.

    Rounds to a sensible bucket so we don't pretend to be more
    accurate than the model warrants:
      < 1k  → exact
      < 10k → nearest 50
      else  → nearest 500 (and shown as "Xk")
    """
    if gas < 1000:
        return f"~{gas} gas"
    if gas < 10_000:
        rounded = round(gas / 50) * 50
        return f"~{rounded:,} gas"
    rounded = round(gas / 500) * 500
    return f"~{rounded // 1000}k gas"


# ─── recursive walker ────────────────────────────────────────────

def _walk(node: ASTNode) -> int:
    """Sum the gas cost of ``node`` and every descendant."""
    cost = _node_self_cost(node)
    for child in node.children:
        cost += _walk(child)
    return cost


def _node_self_cost(node: ASTNode) -> int:
    """Cost of one node, ignoring its children. The recursive
    walker handles children separately so each node is counted
    once."""
    kind = node.kind

    if kind == NodeKind.LITERAL:
        return _LITERAL_COST
    if kind == NodeKind.VAR:
        return _VAR_COST
    if kind == NodeKind.BINOP:
        return _BINOP_COST.get(str(node.value), 5)
    if kind == NodeKind.UNARYOP:
        # Both `-x` (NEG = SUB from 0) and `!x` (ISZERO) are 3 gas.
        return 3
    if kind == NodeKind.CALL:
        # Some stdlib names (log, hypot2, sigmoid, ...) come through
        # as CALL nodes but route to a transcendental implementation
        # in Solidity. Charge the proper cost when we recognize them;
        # default to the generic per-call overhead otherwise.
        return _NAMED_TRANSCENDENTAL_COST.get(
            str(node.value), _CALL_COST,
        )
    if kind == NodeKind.TUPLE:
        return 0  # tuple construction is free in Solidity returns
    if kind in _BUILTIN_COST:
        return _BUILTIN_COST[kind]
    if kind in (NodeKind.LET, NodeKind.LET_MUT, NodeKind.ASSIGN):
        return _LET_COST
    if kind == NodeKind.WHILE:
        # Loop overhead -- two jumps per iteration. We can't know
        # iteration count statically so we model 10 iters as a
        # rough upper bound for the per-fn estimate. Caller can
        # adjust with @dev override if their loop is huge.
        return 100
    if kind in (NodeKind.BLOCK, NodeKind.EXPR_STMT):
        return 0
    # Unknown node kind -- charge a small constant rather than
    # zero so a new AST node we forgot to model doesn't make the
    # estimate look impossibly cheap.
    return 5


# Reference values for the audit trail. Not consumed by the code
# above; kept here so a future contributor (or auditor) can see
# where the BUILTIN_COST numbers came from.
GAS_REFERENCES: dict[str, str] = {
    "PRBMath SD59x18 v4.x": (
        "exp ~3500, ln ~6000, sin ~5000, sqrt ~1000, pow ~10000. "
        "https://github.com/PaulRBerg/prb-math/blob/main/test/sd59x18/"
    ),
    "Solidity Yellow Paper": (
        "ADD/SUB/AND/OR/XOR/LT/GT/EQ/ISZERO=3, MUL/DIV/SDIV/MOD=5. "
        "https://ethereum.github.io/yellowpaper/paper.pdf"
    ),
}
