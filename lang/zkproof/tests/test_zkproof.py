"""Tests for the ZK proof scaffolding (Phase 1 of the Verification Network).

Anchors three contracts:

  * Circuit lowering is deterministic — same canonical AST →
    same circuit hash, byte for byte.
  * Chain-order is computed correctly from the gate trace.
  * prove() + verify() round-trip; tampering with the proof,
    circuit, fingerprint, or inputs breaks the verifier.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lang.fingerprint import fingerprint_module
from lang.parser.ast_nodes import (
    ASTNode,
    EMLFunction,
    EMLModule,
    NodeKind,
    Param,
)
from lang.zkproof import (
    GATE_PARAMS,
    GateKind,
    StubEvaluator,
    canonical_circuit_hash,
    circuit_to_dict,
    compile_circuit,
    prove,
    verify,
)
from lang.zkproof.circuit import CircuitCompileError


# ── AST builders ──────────────────────────────────────────────────


def lit(v: float | int) -> ASTNode:
    return ASTNode(kind=NodeKind.LITERAL, value=v)


def var(name: str) -> ASTNode:
    return ASTNode(kind=NodeKind.VAR, value=name)


def binop(op: str, l: ASTNode, r: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BINOP, value=op, children=[l, r])


def block(*stmts: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.BLOCK, children=list(stmts))


def call_exp(arg: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.EXP, children=[arg])


def call_sin(arg: ASTNode) -> ASTNode:
    return ASTNode(kind=NodeKind.SIN, children=[arg])


def fn_quadratic() -> EMLFunction:
    """f(a, b, c, x) = a * x * x + b * x + c"""
    a, b, c, x = var("a"), var("b"), var("c"), var("x")
    body = block(binop("+",
                       binop("+",
                             binop("*", binop("*", a, x), x),
                             binop("*", b, x)),
                       c))
    return EMLFunction(
        name="quad",
        params=[Param(name="a", type_name="Real"),
                Param(name="b", type_name="Real"),
                Param(name="c", type_name="Real"),
                Param(name="x", type_name="Real")],
        return_type="Real",
        body=body,
    )


def fn_gaussian() -> EMLFunction:
    """f(x, mu, sigma) = exp(-(x - mu)^2 / (2 * sigma^2))"""
    x, mu, sigma = var("x"), var("mu"), var("sigma")
    dx = binop("-", x, mu)
    dx_sq = binop("*", dx, dx)
    two_sigma_sq = binop("*", lit(2.0), binop("*", sigma, sigma))
    inner = binop("/", ASTNode(kind=NodeKind.UNARYOP, value="-",
                               children=[dx_sq]), two_sigma_sq)
    body = block(call_exp(inner))
    return EMLFunction(
        name="gaussian",
        params=[Param(name="x", type_name="Real"),
                Param(name="mu", type_name="Real"),
                Param(name="sigma", type_name="Real")],
        return_type="Real",
        body=body,
    )


def fn_with_lets() -> EMLFunction:
    """f(x) = let y = x + 1; y * y"""
    body = block(
        ASTNode(kind=NodeKind.LET, value="y",
                children=[binop("+", var("x"), lit(1.0))]),
        binop("*", var("y"), var("y")),
    )
    return EMLFunction(
        name="square_plus_one",
        params=[Param(name="x", type_name="Real")],
        return_type="Real",
        body=body,
    )


# ── Circuit lowering ─────────────────────────────────────────────


def test_quadratic_lowers_to_known_gate_count() -> None:
    c = compile_circuit(fn_quadratic())
    # 4 INPUT + 3 MUL (a*x, that*x, b*x) + 2 ADD + 1 OUTPUT
    assert len(c.parameters) == 4
    assert c.gates[0].kind == GateKind.INPUT
    assert c.gates[-1].kind == GateKind.OUTPUT
    counts = _count_gates(c)
    assert counts[GateKind.INPUT] == 4
    assert counts[GateKind.MUL] == 3
    assert counts[GateKind.ADD] == 2
    assert counts[GateKind.OUTPUT] == 1


def test_quadratic_chain_order_is_zero() -> None:
    assert compile_circuit(fn_quadratic()).chain_order == 0


def test_gaussian_chain_order_is_one() -> None:
    assert compile_circuit(fn_gaussian()).chain_order == 1


def test_let_binds_intermediate_value() -> None:
    c = compile_circuit(fn_with_lets())
    # 1 INPUT (x) + 1 CONST (1.0) + 1 ADD (let y = x+1) + 1 MUL (y*y) + 1 OUTPUT
    assert len(c.gates) == 5
    counts = _count_gates(c)
    assert counts[GateKind.INPUT] == 1
    assert counts[GateKind.CONST] == 1
    assert counts[GateKind.ADD] == 1
    assert counts[GateKind.MUL] == 1


def test_circuit_hash_is_deterministic() -> None:
    h_a = canonical_circuit_hash(compile_circuit(fn_gaussian()))
    h_b = canonical_circuit_hash(compile_circuit(fn_gaussian()))
    assert h_a == h_b
    assert h_a.startswith("sha256:")
    assert len(h_a) == len("sha256:") + 64


def test_circuit_hash_changes_with_function_change() -> None:
    h_quad = canonical_circuit_hash(compile_circuit(fn_quadratic()))
    h_gauss = canonical_circuit_hash(compile_circuit(fn_gaussian()))
    assert h_quad != h_gauss


def test_circuit_to_dict_round_trips_through_json() -> None:
    import json as _json
    c = compile_circuit(fn_gaussian())
    d = circuit_to_dict(c)
    encoded = _json.dumps(d, sort_keys=True)
    parsed = _json.loads(encoded)
    assert parsed["fn"] == "gaussian"
    assert parsed["params"] == ["x", "mu", "sigma"]
    assert parsed["chain"] == 1


def test_unsupported_node_raises_circuit_compile_error() -> None:
    fn = EMLFunction(
        name="loop",
        params=[],
        return_type="Real",
        body=ASTNode(kind=NodeKind.WHILE, children=[
            ASTNode(kind=NodeKind.LITERAL, value=1.0),
            ASTNode(kind=NodeKind.BLOCK,   children=[]),
        ]),
    )
    with pytest.raises(CircuitCompileError, match="while"):
        compile_circuit(fn)


def test_tuple_return_rejected() -> None:
    fn = fn_quadratic()
    fn.return_tuple_types = ["Real", "Real"]
    fn.return_type = ""
    with pytest.raises(CircuitCompileError, match="tuple"):
        compile_circuit(fn)


# ── prove / verify ──────────────────────────────────────────────


def test_quadratic_round_trip() -> None:
    fn = fn_quadratic()
    circuit = compile_circuit(fn)
    fp_hash = "sha256:" + ("a" * 64)
    inputs = {"a": 2.0, "b": 3.0, "c": 1.0, "x": 4.0}
    proof = prove(circuit, inputs=inputs, fingerprint_module_hash=fp_hash)
    # 2*4*4 + 3*4 + 1 = 32 + 12 + 1 = 45
    assert proof.output == pytest.approx(45.0)
    result = verify(proof, circuit=circuit, fingerprint_module_hash=fp_hash)
    assert result.is_valid, result.reason


def test_gaussian_round_trip_matches_math_exp() -> None:
    fn = fn_gaussian()
    circuit = compile_circuit(fn)
    fp_hash = "sha256:" + ("b" * 64)
    inputs = {"x": 1.0, "mu": 0.0, "sigma": 1.0}
    proof = prove(circuit, inputs=inputs, fingerprint_module_hash=fp_hash)
    expected = math.exp(-0.5)
    assert proof.output == pytest.approx(expected)
    result = verify(proof, circuit=circuit, fingerprint_module_hash=fp_hash)
    assert result.is_valid


def test_verify_rejects_circuit_substitution() -> None:
    fn_a = fn_quadratic()
    fn_b = fn_gaussian()
    inputs_a = {"a": 1.0, "b": 1.0, "c": 1.0, "x": 1.0}
    fp_hash = "sha256:" + ("c" * 64)
    proof = prove(compile_circuit(fn_a),
                  inputs=inputs_a, fingerprint_module_hash=fp_hash)
    other_circuit = compile_circuit(fn_b)
    result = verify(proof, circuit=other_circuit,
                    fingerprint_module_hash=fp_hash)
    assert not result.is_valid
    assert "circuit_hash" in result.reason


def test_verify_rejects_fingerprint_substitution() -> None:
    fn = fn_quadratic()
    circuit = compile_circuit(fn)
    inputs = {"a": 1.0, "b": 1.0, "c": 1.0, "x": 2.0}
    proof = prove(circuit, inputs=inputs,
                  fingerprint_module_hash="sha256:" + ("d" * 64))
    result = verify(proof, circuit=circuit,
                    fingerprint_module_hash="sha256:" + ("e" * 64))
    assert not result.is_valid
    assert "fingerprint" in result.reason


def test_verify_rejects_tampered_output() -> None:
    fn = fn_quadratic()
    circuit = compile_circuit(fn)
    fp_hash = "sha256:" + ("f" * 64)
    inputs = {"a": 1.0, "b": 1.0, "c": 1.0, "x": 2.0}
    proof = prove(circuit, inputs=inputs, fingerprint_module_hash=fp_hash)
    tampered = ZkProof_with_output(proof, proof.output + 1.0)
    result = verify(tampered, circuit=circuit,
                    fingerprint_module_hash=fp_hash)
    assert not result.is_valid


def test_verify_rejects_tampered_inputs() -> None:
    fn = fn_quadratic()
    circuit = compile_circuit(fn)
    fp_hash = "sha256:" + ("9" * 64)
    inputs = {"a": 1.0, "b": 1.0, "c": 1.0, "x": 2.0}
    proof = prove(circuit, inputs=inputs, fingerprint_module_hash=fp_hash)
    proof.public_inputs["x"] = 99.0     # change input but keep stale output
    result = verify(proof, circuit=circuit,
                    fingerprint_module_hash=fp_hash)
    assert not result.is_valid


def test_proof_has_expected_metadata() -> None:
    fn = fn_gaussian()
    circuit = compile_circuit(fn)
    fp_hash = "sha256:" + ("0" * 64)
    proof = prove(circuit,
                  inputs={"x": 0.0, "mu": 0.0, "sigma": 1.0},
                  fingerprint_module_hash=fp_hash)
    assert proof.spec == "monogate-zkproof/v1-stub"
    assert proof.function_name == "gaussian"
    assert proof.chain_order == 1
    assert proof.n_gates == len(circuit.gates)


def test_proof_to_dict_round_trips_through_json() -> None:
    import json as _json
    circuit = compile_circuit(fn_gaussian())
    proof = prove(circuit,
                  inputs={"x": 1.0, "mu": 0.0, "sigma": 1.0},
                  fingerprint_module_hash="sha256:" + ("1" * 64))
    parsed = _json.loads(proof.to_json(indent=None))
    assert parsed["spec"] == "monogate-zkproof/v1-stub"
    assert parsed["function_name"] == "gaussian"
    assert parsed["chain_order"] == 1


# ── Stub evaluator ───────────────────────────────────────────────


def test_stub_evaluator_produces_witness_per_gate() -> None:
    circuit = compile_circuit(fn_quadratic())
    out, witness = StubEvaluator().evaluate(
        circuit, {"a": 2.0, "b": 0.0, "c": 0.0, "x": 5.0},
    )
    assert out == 50.0   # 2 * 5 * 5
    assert len(witness) == len(circuit.gates)
    # Last witness = output value.
    assert witness[circuit.output_index] == out


# ── Integration with fingerprint module ─────────────────────────


def test_circuit_hash_independent_of_fingerprint_hash() -> None:
    fn = fn_gaussian()
    circuit = compile_circuit(fn)
    mod = EMLModule(name="m", functions=[fn], source_file="m.eml")
    fp = fingerprint_module(mod)
    # Fingerprint hash and circuit hash are different things — they
    # carry different information and live on different schemas.
    assert canonical_circuit_hash(circuit) != fp.module_hash
    assert canonical_circuit_hash(circuit) != fp.functions[0].tree_hash


# ── Helpers ─────────────────────────────────────────────────────


def _count_gates(c) -> dict:
    counts: dict = {}
    for g in c.gates:
        counts[g.kind] = counts.get(g.kind, 0) + 1
    return counts


def ZkProof_with_output(p, new_output):
    """Tamper the output without recomputing the transcript — exposes
    whether the verifier catches inconsistent proof bodies."""
    from copy import deepcopy
    out = deepcopy(p)
    out.output = new_output
    return out
