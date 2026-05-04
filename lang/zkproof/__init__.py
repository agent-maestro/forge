"""ZK proof scaffolding for EML — Phase 1 of the Verification Network.

This module is the *scaffolding* — it lays down the data structures,
the EML-→-circuit lowering, and a transparent-evaluator stub prover
so the rest of the verification network can compose against a stable
interface. The full Plonky2 / Halo2 backend lands later; today the
prover is a deterministic re-execution that produces a transcript-
plus-fingerprint blob that any holder can re-verify.

Why scaffolding first: the EML grammar is constrained to a fixed
operator set (16 primitives). The ZK circuit for a tree of those
operators is a fixed structure known at compile time — no loops, no
conditional branching, no memory access patterns to hide. That makes
EML proofs orders of magnitude smaller than general-purpose ZK-EVM
proofs, but it also means we can build the *contract surface* now
and slot in a real PLONK / Halo2 prover later without touching the
rest of the network.

The contract surface:

  * :class:`ZkCircuit` — pure-data description of the circuit a
    function lowers to (gates + wires + public inputs + outputs).
  * :class:`ZkProof` — what a real prover produces; today it's
    {circuit_hash, fingerprint_module_hash, public_inputs,
    output, transcript_hash} signed with a transparent stub.
  * :func:`compile_circuit` — EML function → ZkCircuit, keyed off
    the same canonical AST the fingerprinter uses (so same source
    → same circuit hash, byte for byte).
  * :func:`prove` / :func:`verify` — round-trip producer/consumer.
    The stub prover re-executes the circuit on the supplied inputs
    via :class:`StubEvaluator` and binds the trace to the
    fingerprint with SHA-256.
"""

from __future__ import annotations

from .circuit import (
    GATE_PARAMS,
    CircuitCompileError,
    Gate,
    GateKind,
    ZkCircuit,
    canonical_circuit_hash,
    circuit_to_dict,
    compile_circuit,
)
from .prover import StubEvaluator, VerifyResult, ZkProof, prove, verify
from . import plonky2_runner

__all__ = [
    "GATE_PARAMS",
    "CircuitCompileError",
    "Gate",
    "GateKind",
    "StubEvaluator",
    "VerifyResult",
    "ZkCircuit",
    "ZkProof",
    "canonical_circuit_hash",
    "circuit_to_dict",
    "compile_circuit",
    "plonky2_runner",
    "prove",
    "verify",
]
