"""Stub prover — Phase 1 scaffolding for the Verification Network.

The real Phase 1 backend is a Plonky2 / Halo2 PLONK prover that
emits a 100-byte zero-knowledge proof per computation. That ships
later; what's wired today is a *transparent* prover that re-executes
the circuit on the supplied inputs and binds the trace to the
fingerprint with SHA-256.

The prover surface is shaped to match what the real ZK backend will
produce, so verifiers can compose against it now:

    proof = prove(circuit, fingerprint, inputs={"x": 1.5, "mu": 0, "sigma": 1})
    assert verify(proof, circuit, fingerprint).is_valid

The transparent prover does NOT hide inputs — that's the
zero-knowledge property the real backend brings. What it does
provide today:

  * **Tamper-evidence**: any change to the circuit, fingerprint,
    inputs, or output produces a different proof transcript hash.
  * **Determinism**: re-proving the same (circuit, inputs) tuple
    on any machine yields the same proof bytes.
  * **Composability**: the proof artefact is JSON-serialisable, so
    the registry, M2M handshake, and dashboard can all carry it.

When the real backend lands, the only callsites that change are
:func:`prove` and :func:`verify` — every consumer keeps working.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .circuit import (
    GATE_PARAMS,
    Gate,
    GateKind,
    ZkCircuit,
    canonical_circuit_hash,
)


# ── Public dataclass ──────────────────────────────────────────────


@dataclass
class ZkProof:
    """The artefact a prover produces. Today this carries the actual
    output and the per-gate trace hash; the real PLONK proof will
    replace `transcript_hash` with the polynomial-commitment proof
    and stop carrying inputs in the clear."""

    spec: str = "monogate-zkproof/v1-stub"
    """Wire-protocol identifier. The ``-stub`` suffix flags this is
    the transparent scaffolding; the real prover will emit
    ``monogate-zkproof/v1``."""
    circuit_hash: str = ""
    """SHA-256 of the canonical circuit (links proof to its program)."""
    fingerprint_module_hash: str = ""
    """SHA-256 of the producing module's fingerprint."""
    function_name: str = ""
    public_inputs: Dict[str, float] = field(default_factory=dict)
    output: Optional[float] = None
    transcript_hash: str = ""
    """SHA-256 of the per-gate trace (today: the witness directly;
    when PLONK lands: the Fiat-Shamir transcript)."""
    chain_order: int = 0
    n_gates: int = 0

    def to_dict(self) -> dict:
        return {
            "spec":                    self.spec,
            "circuit_hash":            self.circuit_hash,
            "fingerprint_module_hash": self.fingerprint_module_hash,
            "function_name":           self.function_name,
            "public_inputs":           dict(self.public_inputs),
            "output":                  self.output,
            "transcript_hash":         self.transcript_hash,
            "chain_order":             self.chain_order,
            "n_gates":                 self.n_gates,
        }

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        if indent is None:
            return json.dumps(self.to_dict(), sort_keys=True,
                              separators=(",", ":"))
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent)


@dataclass
class VerifyResult:
    """What :func:`verify` returns. ``ok`` is the headline; the rest
    are reasons the verifier can show a human."""

    is_valid: bool
    reason: str = ""
    expected_circuit_hash: str = ""
    expected_output: Optional[float] = None
    actual_output: Optional[float] = None


# ── Stub evaluator ────────────────────────────────────────────────


class StubEvaluator:
    """Walks the circuit gate-by-gate and computes the output from
    public inputs. This is the *transparent* part — a real prover
    would compute the same trace inside the field arithmetic of the
    chosen ZK backend and never expose the witness."""

    def evaluate(
        self,
        circuit: ZkCircuit,
        inputs: Mapping[str, float],
    ) -> tuple[float, list[float]]:
        wires: list[float] = []
        for gate in circuit.gates:
            wires.append(self._evaluate_gate(gate, wires, inputs))
        if circuit.output_index is None:
            raise ValueError("circuit has no OUTPUT gate")
        return wires[circuit.output_index], wires

    def _evaluate_gate(
        self,
        gate: Gate,
        wires: list[float],
        inputs: Mapping[str, float],
    ) -> float:
        k = gate.kind
        ins = [wires[i] for i in gate.inputs]

        if k is GateKind.CONST:
            return float(gate.value)
        if k is GateKind.INPUT:
            name = str(gate.value)
            if name not in inputs:
                raise KeyError(f"missing input `{name}`")
            return float(inputs[name])

        if k is GateKind.ADD:    return ins[0] + ins[1]
        if k is GateKind.SUB:    return ins[0] - ins[1]
        if k is GateKind.MUL:    return ins[0] * ins[1]
        if k is GateKind.DIV:    return ins[0] / ins[1]
        if k is GateKind.MOD:    return math.fmod(ins[0], ins[1])
        if k is GateKind.NEG:    return -ins[0]
        if k is GateKind.POW:    return math.pow(ins[0], ins[1])

        if k is GateKind.EXP:    return math.exp(ins[0])
        if k is GateKind.LN:     return math.log(ins[0])
        if k is GateKind.SIN:    return math.sin(ins[0])
        if k is GateKind.COS:    return math.cos(ins[0])
        if k is GateKind.TAN:    return math.tan(ins[0])
        if k is GateKind.SQRT:   return math.sqrt(ins[0])
        if k is GateKind.ASIN:   return math.asin(ins[0])
        if k is GateKind.ACOS:   return math.acos(ins[0])
        if k is GateKind.ATAN:   return math.atan(ins[0])
        if k is GateKind.SINH:   return math.sinh(ins[0])
        if k is GateKind.COSH:   return math.cosh(ins[0])
        if k is GateKind.TANH:   return math.tanh(ins[0])

        if k is GateKind.ABS:    return abs(ins[0])
        if k is GateKind.MIN:    return min(ins[0], ins[1])
        if k is GateKind.MAX:    return max(ins[0], ins[1])
        if k is GateKind.CLAMP:  return max(ins[1], min(ins[2], ins[0]))

        if k is GateKind.OUTPUT:
            return ins[0]

        raise ValueError(f"unknown gate kind {k.value!r}")


# ── prove / verify ────────────────────────────────────────────────


_PROOF_SPEC_STUB = "monogate-zkproof/v1-stub"


def prove(
    circuit: ZkCircuit,
    *,
    inputs: Mapping[str, float],
    fingerprint_module_hash: str,
) -> ZkProof:
    """Produce a (today: transparent, tomorrow: zero-knowledge) proof
    that the circuit's output for the supplied inputs is what we say."""
    evaluator = StubEvaluator()
    out, witness = evaluator.evaluate(circuit, inputs)
    transcript = _hash_transcript(witness, inputs, fingerprint_module_hash)
    return ZkProof(
        spec=_PROOF_SPEC_STUB,
        circuit_hash=canonical_circuit_hash(circuit),
        fingerprint_module_hash=fingerprint_module_hash,
        function_name=circuit.function_name,
        public_inputs=dict(inputs),
        output=out,
        transcript_hash=transcript,
        chain_order=circuit.chain_order,
        n_gates=len(circuit.gates),
    )


def verify(
    proof: ZkProof,
    *,
    circuit: ZkCircuit,
    fingerprint_module_hash: str,
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> VerifyResult:
    """Independent re-execution + transcript check. Returns
    ``VerifyResult.is_valid = True`` only when:

      1. The circuit hash in the proof matches the supplied circuit.
      2. The fingerprint hash matches.
      3. Re-executing the circuit on the proof's public inputs
         reproduces the proof's claimed output (to ``rtol`` / ``atol``).
      4. The transcript hash matches the recomputed one.

    Any failure produces an ``is_valid=False`` with a one-sentence
    ``reason`` that the verification dashboard can surface to a human.
    """
    expected_chash = canonical_circuit_hash(circuit)
    if proof.circuit_hash != expected_chash:
        return VerifyResult(
            is_valid=False,
            reason="circuit_hash mismatch — proof was produced from a "
                   "different circuit",
            expected_circuit_hash=expected_chash,
        )

    if proof.fingerprint_module_hash != fingerprint_module_hash:
        return VerifyResult(
            is_valid=False,
            reason="fingerprint_module_hash mismatch — proof was produced "
                   "from a different module fingerprint",
            expected_circuit_hash=expected_chash,
        )

    evaluator = StubEvaluator()
    try:
        actual_out, witness = evaluator.evaluate(circuit, proof.public_inputs)
    except Exception as exc:  # noqa: BLE001 — stub re-execution may fail
        return VerifyResult(
            is_valid=False,
            reason=f"re-execution failed: {exc}",
            expected_circuit_hash=expected_chash,
        )

    if proof.output is None:
        return VerifyResult(
            is_valid=False,
            reason="proof carries no output to compare against",
            expected_circuit_hash=expected_chash,
            actual_output=actual_out,
        )

    if not _close(proof.output, actual_out, rtol=rtol, atol=atol):
        return VerifyResult(
            is_valid=False,
            reason=f"output mismatch — re-executed to {actual_out!r}, "
                   f"proof claimed {proof.output!r}",
            expected_circuit_hash=expected_chash,
            expected_output=actual_out,
            actual_output=proof.output,
        )

    expected_transcript = _hash_transcript(
        witness, proof.public_inputs, fingerprint_module_hash,
    )
    if proof.transcript_hash != expected_transcript:
        return VerifyResult(
            is_valid=False,
            reason="transcript hash mismatch — proof body was tampered with",
            expected_circuit_hash=expected_chash,
            expected_output=actual_out,
            actual_output=proof.output,
        )

    return VerifyResult(
        is_valid=True,
        reason="ok",
        expected_circuit_hash=expected_chash,
        expected_output=actual_out,
        actual_output=proof.output,
    )


# ── Helpers ───────────────────────────────────────────────────────


def _hash_transcript(
    witness: Iterable[float],
    inputs: Mapping[str, float],
    fingerprint_module_hash: str,
) -> str:
    """Deterministic hash over the trace + inputs + fingerprint hash.

    When the real PLONK prover ships, this is replaced by the
    Fiat-Shamir transcript of the polynomial commitment scheme — but
    every consumer of `transcript_hash` keeps working unchanged.
    """
    payload = {
        "fp": fingerprint_module_hash,
        "in": {k: repr(float(v)) for k, v in sorted(inputs.items())},
        "tr": [_hash_value(v) for v in witness],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _hash_value(v: float) -> str:
    """Single-float hash byte block. Round-trip-stable repr() means
    NaN / inf hash distinctly from finite values."""
    return repr(float(v))


def _close(a: float, b: float, *, rtol: float, atol: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isinf(a) and math.isinf(b) and (a > 0) == (b > 0):
        return True
    denom = max(abs(a), abs(b), atol)
    return abs(a - b) <= max(atol, rtol * denom)
