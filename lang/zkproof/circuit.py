"""EML AST → fixed-gate ZK circuit description.

The EML language has 16 transcendental + arithmetic primitives plus a
small set of binary/unary operators. Each one becomes a single gate
in our circuit IR. This file:

  1. Names the canonical gate set (``GateKind``).
  2. Describes a circuit as a flat list of gates with input wire
     indices (SSA-style).
  3. Lowers an :class:`EMLFunction` body into a circuit. The lowering
     is deterministic — variable assignment order, traversal order,
     wire numbering — so the circuit hash is reproducible across
     machines, just like the fingerprint.

Determinism contract: ``compile_circuit`` is a pure function of the
function's canonical AST (which is what the fingerprint module
already hashes). Two machines that compile the same source produce
the same circuit, byte for byte.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind


# ── Gate set ────────────────────────────────────────────────────────


class GateKind(str, Enum):
    """The canonical gate vocabulary of every EML circuit.

    Splitting into ARITHMETIC (cheap, depth 1) vs TRANSCENDENTAL
    (expensive, depth 2-4 in the underlying field arithmetic) makes
    chain-order accounting fall out of circuit construction.
    """

    # Arithmetic — chain-order increment 0
    CONST = "CONST"   # c            (0 inputs, public)
    INPUT = "INPUT"   # parameter    (0 inputs, public)
    ADD   = "ADD"     # a + b
    SUB   = "SUB"     # a - b
    MUL   = "MUL"     # a * b
    DIV   = "DIV"     # a / b
    MOD   = "MOD"     # a % b
    NEG   = "NEG"     # -a
    POW   = "POW"     # a ^ b   (kept as a generic gate; chain += 1 only when b non-integral)

    # Transcendentals — chain-order increment 1
    EXP   = "EXP"
    LN    = "LN"
    SIN   = "SIN"
    COS   = "COS"
    TAN   = "TAN"
    SQRT  = "SQRT"
    ASIN  = "ASIN"
    ACOS  = "ACOS"
    ATAN  = "ATAN"
    SINH  = "SINH"
    COSH  = "COSH"
    TANH  = "TANH"

    # Helpers — chain-order increment 0 (clamp/abs/min/max are constant-rank)
    ABS   = "ABS"
    CLAMP = "CLAMP"   # 3 inputs (x, lo, hi)
    MIN   = "MIN"
    MAX   = "MAX"

    # Output — marks the wire whose value the circuit returns.
    OUTPUT = "OUTPUT"


# Per-gate arity + chain-order delta. Drives both the circuit
# lowering and the validator.
GATE_PARAMS = {
    GateKind.CONST:  {"arity": 0, "chain_delta": 0},
    GateKind.INPUT:  {"arity": 0, "chain_delta": 0},
    GateKind.ADD:    {"arity": 2, "chain_delta": 0},
    GateKind.SUB:    {"arity": 2, "chain_delta": 0},
    GateKind.MUL:    {"arity": 2, "chain_delta": 0},
    GateKind.DIV:    {"arity": 2, "chain_delta": 0},
    GateKind.MOD:    {"arity": 2, "chain_delta": 0},
    GateKind.NEG:    {"arity": 1, "chain_delta": 0},
    GateKind.POW:    {"arity": 2, "chain_delta": 0},
    GateKind.EXP:    {"arity": 1, "chain_delta": 1},
    GateKind.LN:     {"arity": 1, "chain_delta": 1},
    GateKind.SIN:    {"arity": 1, "chain_delta": 1},
    GateKind.COS:    {"arity": 1, "chain_delta": 1},
    GateKind.TAN:    {"arity": 1, "chain_delta": 1},
    GateKind.SQRT:   {"arity": 1, "chain_delta": 1},
    GateKind.ASIN:   {"arity": 1, "chain_delta": 1},
    GateKind.ACOS:   {"arity": 1, "chain_delta": 1},
    GateKind.ATAN:   {"arity": 1, "chain_delta": 1},
    GateKind.SINH:   {"arity": 1, "chain_delta": 1},
    GateKind.COSH:   {"arity": 1, "chain_delta": 1},
    GateKind.TANH:   {"arity": 1, "chain_delta": 1},
    GateKind.ABS:    {"arity": 1, "chain_delta": 0},
    GateKind.CLAMP:  {"arity": 3, "chain_delta": 0},
    GateKind.MIN:    {"arity": 2, "chain_delta": 0},
    GateKind.MAX:    {"arity": 2, "chain_delta": 0},
    GateKind.OUTPUT: {"arity": 1, "chain_delta": 0},
}


# Map AST NodeKind -> GateKind for the primitive-call nodes.
_NODE_TO_GATE = {
    NodeKind.EXP:   GateKind.EXP,
    NodeKind.LN:    GateKind.LN,
    NodeKind.SIN:   GateKind.SIN,
    NodeKind.COS:   GateKind.COS,
    NodeKind.TAN:   GateKind.TAN,
    NodeKind.SQRT:  GateKind.SQRT,
    NodeKind.POW:   GateKind.POW,
    NodeKind.ASIN:  GateKind.ASIN,
    NodeKind.ACOS:  GateKind.ACOS,
    NodeKind.ATAN:  GateKind.ATAN,
    NodeKind.SINH:  GateKind.SINH,
    NodeKind.COSH:  GateKind.COSH,
    NodeKind.TANH:  GateKind.TANH,
    NodeKind.ABS:   GateKind.ABS,
    NodeKind.CLAMP: GateKind.CLAMP,
}


_BINOP_TO_GATE = {
    "+": GateKind.ADD,
    "-": GateKind.SUB,
    "*": GateKind.MUL,
    "/": GateKind.DIV,
    "%": GateKind.MOD,
    "^": GateKind.POW,
}


# ── Data classes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Gate:
    """One gate in the circuit. ``inputs`` are wire indices (positions
    in :attr:`ZkCircuit.gates`). ``value`` is the constant payload for
    CONST gates and the parameter name for INPUT gates."""

    kind: GateKind
    inputs: tuple[int, ...]
    value: Any = None

    def to_dict(self) -> dict:
        return {
            "k": self.kind.value,
            "i": list(self.inputs),
            "v": _serialise_value(self.value),
        }


def _serialise_value(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, bool)):
        return v
    if isinstance(v, float):
        # repr is round-trip stable in Python ≥ 3.1.
        return repr(v)
    return repr(v)


@dataclass
class ZkCircuit:
    """Flat list of gates plus circuit-level metadata. The ``gates``
    list is in topological order — every input wire references an
    earlier index. The last gate is always an ``OUTPUT`` whose single
    input is the wire carrying the function's return value."""

    function_name: str
    parameters: List[str]            # names, in declaration order
    gates: List[Gate] = field(default_factory=list)
    chain_order: int = 0
    public_input_indices: List[int] = field(default_factory=list)
    output_index: Optional[int] = None
    """Wire index whose value is the circuit's output."""

    def to_dict(self) -> dict:
        return {
            "fn":         self.function_name,
            "params":     list(self.parameters),
            "gates":      [g.to_dict() for g in self.gates],
            "chain":      self.chain_order,
            "public_in":  list(self.public_input_indices),
            "out":        self.output_index,
        }


def circuit_to_dict(c: ZkCircuit) -> dict:
    return c.to_dict()


def canonical_circuit_hash(c: ZkCircuit) -> str:
    """SHA-256 of the canonical JSON representation. Same source →
    same circuit → same hash, on any machine."""
    encoded = json.dumps(
        c.to_dict(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


# ── Lowering ────────────────────────────────────────────────────────


class CircuitCompileError(Exception):
    """The function uses a construct the ZK lowering doesn't support yet."""


@dataclass
class _Builder:
    circuit: ZkCircuit
    # Map from variable name (let / param) to current wire index.
    bindings: dict[str, int] = field(default_factory=dict)

    def add(self, gate: Gate) -> int:
        idx = len(self.circuit.gates)
        self.circuit.gates.append(gate)
        return idx


def compile_circuit(fn: EMLFunction) -> ZkCircuit:
    """Lower an EML function body into a ZK circuit description.

    Constructs:
      - One INPUT gate per parameter (in declaration order).
      - One CONST gate per literal occurrence.
      - One arithmetic / transcendental gate per AST operation.
      - One OUTPUT gate marking the return wire.

    Constraints:
      - Tail-expression returns only — no while / for / if statements
        in the lowering yet (those are E3+ for the prover anyway).
      - Tuple returns aren't lowered; the spec says ZK proofs target
        scalar functions first.

    Raises :class:`CircuitCompileError` when the body contains a
    construct that hasn't been wired yet, with a pointer to which
    NodeKind is missing.
    """
    if fn.return_tuple_types:
        raise CircuitCompileError(
            f"function `{fn.name}` returns a tuple; ZK lowering "
            f"targets scalar-returning functions in Phase 1"
        )
    if fn.is_extern:
        raise CircuitCompileError(
            f"`extern fn {fn.name}` has no body — nothing to compile"
        )
    if fn.body is None:
        raise CircuitCompileError(f"function `{fn.name}` has no body")

    circuit = ZkCircuit(
        function_name=fn.name,
        parameters=[p.name for p in fn.params],
    )
    builder = _Builder(circuit=circuit)

    # Parameters become INPUT gates with a stable (declaration-order) index.
    for p in fn.params:
        idx = builder.add(Gate(kind=GateKind.INPUT, inputs=(), value=p.name))
        builder.bindings[p.name] = idx
        circuit.public_input_indices.append(idx)

    return_wire = _lower_node(fn.body, builder)

    # OUTPUT is the last gate, by convention.
    out_idx = builder.add(Gate(
        kind=GateKind.OUTPUT, inputs=(return_wire,), value=None
    ))
    circuit.output_index = out_idx
    circuit.chain_order = _chain_order_of(circuit)
    return circuit


# ── Lowering helpers ────────────────────────────────────────────────


def _lower_node(node: ASTNode, b: _Builder) -> int:
    if not isinstance(node, ASTNode):
        raise CircuitCompileError(
            f"_lower_node: expected ASTNode, got {type(node).__name__}"
        )
    k = node.kind

    if k is NodeKind.LITERAL:
        return b.add(Gate(kind=GateKind.CONST, inputs=(), value=node.value))

    if k is NodeKind.VAR:
        name = node.value
        if name not in b.bindings:
            raise CircuitCompileError(
                f"unbound variable `{name}` (let must precede use; "
                f"forward refs aren't supported yet)"
            )
        return b.bindings[name]

    if k is NodeKind.UNARYOP:
        if node.value == "-":
            inner = _lower_node(node.children[0], b)
            return b.add(Gate(kind=GateKind.NEG, inputs=(inner,)))
        if node.value == "+":
            return _lower_node(node.children[0], b)
        raise CircuitCompileError(f"unary `{node.value}` unsupported")

    if k is NodeKind.BINOP:
        op = node.value
        if op not in _BINOP_TO_GATE:
            raise CircuitCompileError(
                f"binary `{op}` unsupported — ZK lowering only "
                f"covers arithmetic + power for now"
            )
        l = _lower_node(node.children[0], b)
        r = _lower_node(node.children[1], b)
        return b.add(Gate(kind=_BINOP_TO_GATE[op], inputs=(l, r)))

    # MIN/MAX don't have dedicated NodeKind values in the parser today —
    # they arrive as CALL nodes with value="min"/"max". The gate set
    # still reserves slots for them and the call-dispatch below handles
    # them.

    if k in _NODE_TO_GATE:
        gate_kind = _NODE_TO_GATE[k]
        return _call_to_gate(node, b, gate_kind)

    if k is NodeKind.CALL:
        # User-defined functions don't lower yet — they'd need
        # inlining or a separate sub-circuit, which is post-Phase-1.
        raise CircuitCompileError(
            f"call to user fn `{node.value}` unsupported; "
            f"inlining lands in a later phase"
        )

    if k is NodeKind.EML:
        # The EML primitive — passes its inner expression through
        # unchanged. Useful as a marker; no gate emitted.
        if not node.children:
            raise CircuitCompileError("`eml` primitive missing operand")
        return _lower_node(node.children[0], b)

    if k is NodeKind.LET or k is NodeKind.LET_MUT:
        rhs = _lower_node(node.children[0], b)
        b.bindings[str(node.value)] = rhs
        # `let` itself doesn't carry a value — the caller (BLOCK) will
        # ignore the return.
        return rhs

    if k is NodeKind.ASSIGN:
        rhs = _lower_node(node.children[0], b)
        if node.value not in b.bindings:
            raise CircuitCompileError(
                f"assignment to unbound `{node.value}`"
            )
        b.bindings[str(node.value)] = rhs
        return rhs

    if k is NodeKind.BLOCK:
        # Walk every statement; the value of the block is the value
        # of its last expression. Statements that aren't expressions
        # (let, assign) populate bindings as a side effect.
        last_wire: Optional[int] = None
        for child in node.children:
            last_wire = _lower_node(child, b)
        if last_wire is None:
            raise CircuitCompileError("block produced no value")
        return last_wire

    if k is NodeKind.EXPR_STMT:
        if not node.children:
            raise CircuitCompileError("expression-statement missing operand")
        return _lower_node(node.children[0], b)

    if k is NodeKind.WHILE:
        raise CircuitCompileError(
            "`while` loops aren't lowered to ZK in Phase 1 — they need "
            "either a known iteration bound (loop unrolling) or a "
            "dedicated recursive-circuit gadget (Phase 2)"
        )

    raise CircuitCompileError(f"NodeKind `{k.value}` not lowered yet")


def _call_to_gate(node: ASTNode, b: _Builder, gate_kind: GateKind) -> int:
    """Lower a built-in primitive call (EXP/SIN/CLAMP/...)."""
    arity = GATE_PARAMS[gate_kind]["arity"]
    if len(node.children) != arity:
        raise CircuitCompileError(
            f"`{gate_kind.value}` expects {arity} args, got "
            f"{len(node.children)}"
        )
    inputs = tuple(_lower_node(c, b) for c in node.children)
    return b.add(Gate(kind=gate_kind, inputs=inputs))


def _binary_call(node: ASTNode, b: _Builder, gate_kind: GateKind) -> int:
    if len(node.children) != 2:
        raise CircuitCompileError(
            f"`{gate_kind.value}` expects 2 args, got {len(node.children)}"
        )
    a = _lower_node(node.children[0], b)
    c = _lower_node(node.children[1], b)
    return b.add(Gate(kind=gate_kind, inputs=(a, c)))


def _chain_order_of(circuit: ZkCircuit) -> int:
    """Longest path of transcendental gates in the circuit. Mirrors
    what the profiler computes from the AST — they should agree."""
    depths: list[int] = [0] * len(circuit.gates)
    for i, g in enumerate(circuit.gates):
        max_in = max((depths[j] for j in g.inputs), default=0)
        depths[i] = max_in + GATE_PARAMS[g.kind]["chain_delta"]
    return max(depths, default=0)
