"""Tests for the real Plonky2 backend (lang/zkproof/plonky2_runner.py
and the Rust binary it shells to).

These skip cleanly when the binary hasn't been built so contributors
without a Rust toolchain still see a green test run; they only become
meaningful after `cargo build --release` in plonky2_backend/.
"""

from __future__ import annotations

import pytest

from lang.parser.ast_nodes import ASTNode, EMLFunction, NodeKind, Param
from lang.zkproof import (
    compile_circuit,
    prove,
    verify,
)
from lang.zkproof import plonky2_runner


pytestmark = [
    pytest.mark.skipif(
        not plonky2_runner.available(),
        reason="monogate-zk binary not built (run cargo build --release in "
               "lang/zkproof/plonky2_backend/)",
    ),
    # Excluded from default CI via `pytest -m 'not slow'`. Real proof
    # generation is ~10ms but cargo-building the prover crate first
    # adds minutes; nightly workflow runs the full set.
    pytest.mark.slow,
]


def _arithmetic_fn() -> EMLFunction:
    """f(x) = 2*x + 3 — pure arithmetic, fully Plonky2-supportable."""
    return EMLFunction(
        name="linear", params=[Param(name="x", type_name="Real")],
        body=ASTNode(NodeKind.BLOCK, children=[
            ASTNode(NodeKind.BINOP, value="+", children=[
                ASTNode(NodeKind.BINOP, value="*", children=[
                    ASTNode(NodeKind.LITERAL, value=2.0),
                    ASTNode(NodeKind.VAR, value="x"),
                ]),
                ASTNode(NodeKind.LITERAL, value=3.0),
            ]),
        ]),
        return_type="Real",
    )


def _polynomial_fn() -> EMLFunction:
    """f(a, b, c, x) = a*x*x + b*x + c — exercises 2-deep MUL chain."""
    body = ASTNode(NodeKind.BLOCK, children=[
        ASTNode(NodeKind.BINOP, value="+", children=[
            ASTNode(NodeKind.BINOP, value="+", children=[
                ASTNode(NodeKind.BINOP, value="*", children=[
                    ASTNode(NodeKind.BINOP, value="*", children=[
                        ASTNode(NodeKind.VAR, value="a"),
                        ASTNode(NodeKind.VAR, value="x"),
                    ]),
                    ASTNode(NodeKind.VAR, value="x"),
                ]),
                ASTNode(NodeKind.BINOP, value="*", children=[
                    ASTNode(NodeKind.VAR, value="b"),
                    ASTNode(NodeKind.VAR, value="x"),
                ]),
            ]),
            ASTNode(NodeKind.VAR, value="c"),
        ]),
    ])
    return EMLFunction(
        name="poly",
        params=[Param(name=n, type_name="Real")
                for n in ("a", "b", "c", "x")],
        body=body, return_type="Real",
    )


def _transcendental_fn() -> EMLFunction:
    """f(x) = exp(x) — exercises an unsupported gate."""
    return EMLFunction(
        name="my_exp", params=[Param(name="x", type_name="Real")],
        body=ASTNode(NodeKind.BLOCK, children=[
            ASTNode(NodeKind.EXP, children=[
                ASTNode(NodeKind.VAR, value="x"),
            ]),
        ]),
        return_type="Real",
    )


# ── Capability discovery ─────────────────────────────────────────


def test_capabilities_advertises_v1_spec() -> None:
    caps = plonky2_runner.capabilities()
    assert caps is not None
    assert caps.spec == "monogate-zkproof/v1"
    assert caps.field == "Goldilocks"
    assert "ADD" in caps.supported_gates
    assert "MUL" in caps.supported_gates
    assert "EXP" in caps.deferred_gates
    assert caps.fixed_point_bits >= 8


def test_can_prove_arithmetic_only() -> None:
    arith = compile_circuit(_arithmetic_fn())
    assert plonky2_runner.can_prove(arith)


def test_cannot_prove_transcendental() -> None:
    trans = compile_circuit(_transcendental_fn())
    assert not plonky2_runner.can_prove(trans)


# ── End-to-end prove + verify ────────────────────────────────────


def test_arithmetic_routes_through_plonky2_under_auto() -> None:
    circuit = compile_circuit(_arithmetic_fn())
    proof = prove(circuit, inputs={"x": 1.5},
                  fingerprint_module_hash="sha256:abc")
    assert proof.spec == "monogate-zkproof/v1"
    # Plonky2 proofs are bytes, hex-encoded — well over a kilobyte even
    # for a tiny circuit.
    assert len(proof.transcript_hash) > 1000
    assert abs(proof.output - 6.0) < 0.01

    res = verify(proof, circuit=circuit,
                 fingerprint_module_hash="sha256:abc")
    assert res.is_valid, res.reason


def test_transcendental_falls_back_to_stub_under_auto() -> None:
    circuit = compile_circuit(_transcendental_fn())
    proof = prove(circuit, inputs={"x": 0.5},
                  fingerprint_module_hash="sha256:abc")
    assert proof.spec == "monogate-zkproof/v1-stub"

    res = verify(proof, circuit=circuit,
                 fingerprint_module_hash="sha256:abc")
    assert res.is_valid, res.reason


def test_explicit_plonky2_backend_rejects_transcendental() -> None:
    circuit = compile_circuit(_transcendental_fn())
    with pytest.raises(plonky2_runner.Plonky2BackendError):
        prove(circuit, inputs={"x": 0.5},
              fingerprint_module_hash="sha256:abc",
              backend="plonky2")


def test_explicit_stub_backend_skips_plonky2() -> None:
    circuit = compile_circuit(_arithmetic_fn())
    proof = prove(circuit, inputs={"x": 1.5},
                  fingerprint_module_hash="sha256:abc",
                  backend="stub")
    assert proof.spec == "monogate-zkproof/v1-stub"


# ── Tamper detection through the real verifier ───────────────────


def test_plonky2_verify_rejects_tampered_output() -> None:
    circuit = compile_circuit(_polynomial_fn())
    proof = prove(circuit,
                  inputs={"a": 1.0, "b": 2.0, "c": 3.0, "x": 1.5},
                  fingerprint_module_hash="sha256:abc")
    assert proof.spec == "monogate-zkproof/v1"
    proof.output = (proof.output or 0.0) + 100.0
    res = verify(proof, circuit=circuit,
                 fingerprint_module_hash="sha256:abc")
    assert not res.is_valid
    assert "output" in res.reason.lower() or "match" in res.reason.lower()


def test_plonky2_verify_rejects_tampered_input() -> None:
    circuit = compile_circuit(_polynomial_fn())
    proof = prove(circuit,
                  inputs={"a": 1.0, "b": 2.0, "c": 3.0, "x": 1.5},
                  fingerprint_module_hash="sha256:abc")
    assert proof.spec == "monogate-zkproof/v1"
    proof.public_inputs["x"] = 99.0
    res = verify(proof, circuit=circuit,
                 fingerprint_module_hash="sha256:abc")
    assert not res.is_valid


def test_plonky2_verify_rejects_wrong_circuit() -> None:
    a = compile_circuit(_arithmetic_fn())
    b = compile_circuit(_polynomial_fn())
    proof = prove(a, inputs={"x": 1.5},
                  fingerprint_module_hash="sha256:abc")
    res = verify(proof, circuit=b,
                 fingerprint_module_hash="sha256:abc")
    assert not res.is_valid
    assert "circuit" in res.reason.lower()


def test_plonky2_verify_rejects_wrong_fingerprint() -> None:
    circuit = compile_circuit(_arithmetic_fn())
    proof = prove(circuit, inputs={"x": 1.5},
                  fingerprint_module_hash="sha256:aaa")
    res = verify(proof, circuit=circuit,
                 fingerprint_module_hash="sha256:bbb")
    assert not res.is_valid
    assert "fingerprint" in res.reason.lower()


# ── Determinism + JSON round-trip ────────────────────────────────


def test_proof_json_round_trips_through_registry_pipeline() -> None:
    """The transparency-log path takes proof.to_json(), POSTs it,
    later fetches it back and re-verifies. Make sure that survives
    a Plonky2 proof too."""
    import json
    circuit = compile_circuit(_arithmetic_fn())
    proof = prove(circuit, inputs={"x": 2.0},
                  fingerprint_module_hash="sha256:abc")
    blob = json.loads(proof.to_json(indent=None))
    assert blob["spec"] == "monogate-zkproof/v1"
    # Reconstruct the proof from the JSON (the registry doesn't keep
    # the Python instance) and re-verify.
    from lang.zkproof.prover import ZkProof
    rebuilt = ZkProof(
        spec=blob["spec"],
        circuit_hash=blob["circuit_hash"],
        fingerprint_module_hash=blob["fingerprint_module_hash"],
        function_name=blob["function_name"],
        public_inputs=blob["public_inputs"],
        output=blob["output"],
        transcript_hash=blob["transcript_hash"],
        chain_order=blob["chain_order"],
        n_gates=blob["n_gates"],
    )
    res = verify(rebuilt, circuit=circuit,
                 fingerprint_module_hash="sha256:abc")
    assert res.is_valid, res.reason
