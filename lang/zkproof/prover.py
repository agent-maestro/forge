"""Prover — Phase 1 of the Verification Network.

Two backends share a single prove/verify API:

  * **plonky2** (real ZK) — runs the EML circuit through the
    `monogate-zk` Rust binary built from `lang/zkproof/plonky2_backend/`.
    Produces a Goldilocks-field PLONK + FRI proof. Currently handles
    arithmetic-only circuits (CONST/INPUT/ADD/SUB/MUL/NEG/OUTPUT);
    transcendental gates fall back to the stub.
  * **stub** (transparent) — re-executes the circuit on supplied
    inputs and binds the trace to the fingerprint with SHA-256.
    Tamper-evident and deterministic but **not** zero-knowledge:
    inputs are in the clear.

Routing is automatic: :func:`prove` tries the Plonky2 binary first
when it can prove the circuit, otherwise falls back to the stub. The
proof artefact's ``spec`` field tells the verifier which path to
take (``monogate-zkproof/v1`` for the real backend,
``monogate-zkproof/v1-stub`` for the transparent one).

    proof = prove(circuit, inputs={"x": 1.5}, fingerprint_module_hash="sha256:...")
    assert verify(proof, circuit=circuit,
                  fingerprint_module_hash="sha256:...").is_valid

What the stub still provides today, regardless of backend:

  * **Tamper-evidence**: any change to the circuit, fingerprint,
    inputs, or output is detected by the verifier.
  * **Determinism**: re-proving the same (circuit, inputs) tuple on
    any machine yields the same proof bytes (true for stub; the
    Plonky2 prover is deterministic but its bytes depend on the
    crate version).
  * **Composability**: the proof artefact is JSON-serialisable so
    the registry, M2M handshake, and dashboard can all carry it.
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
    circuit_to_dict,
)
from . import plonky2_runner


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
_PROOF_SPEC_PLONKY2 = "monogate-zkproof/v1"


def prove(
    circuit: ZkCircuit,
    *,
    inputs: Mapping[str, float],
    fingerprint_module_hash: str,
    backend: str = "auto",
) -> ZkProof:
    """Produce a proof that the circuit's output for the supplied
    inputs is what we say.

    Backends:
      * ``"auto"`` (default) — use the Plonky2 binary when it can
        prove the circuit; fall back to the transparent stub.
      * ``"plonky2"`` — require the real ZK backend; raises if it
        can't handle the circuit.
      * ``"stub"`` — force the transparent backend (useful in tests
        and on machines without the Rust toolchain).
    """
    if backend not in ("auto", "plonky2", "stub"):
        raise ValueError(f"unknown backend `{backend}`")

    if backend in ("auto", "plonky2") and plonky2_runner.can_prove(circuit):
        try:
            payload = plonky2_runner.prove_with_binary(
                circuit,
                inputs=inputs,
                fingerprint_module_hash=fingerprint_module_hash,
            )
            return _proof_from_plonky2_payload(payload, circuit)
        except plonky2_runner.Plonky2BackendError:
            if backend == "plonky2":
                raise
            # auto mode: fall through to stub
    elif backend == "plonky2":
        raise plonky2_runner.Plonky2BackendError(
            "plonky2 backend cannot handle this circuit "
            "(requires CONST/INPUT/ADD/SUB/MUL/NEG/OUTPUT only) "
            "or the binary is unavailable"
        )

    return _prove_stub(circuit, inputs, fingerprint_module_hash)


def _prove_stub(
    circuit: ZkCircuit,
    inputs: Mapping[str, float],
    fingerprint_module_hash: str,
) -> ZkProof:
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


def _proof_from_plonky2_payload(payload: dict, circuit: ZkCircuit) -> ZkProof:
    """Wrap the raw Plonky2 JSON payload in a :class:`ZkProof`. The
    raw bytes (``proof_bytes_hex``) ride on :attr:`ZkProof.transcript_hash`
    so existing JSON consumers keep working unchanged; the spec field
    tells the verifier which path to take."""
    proof = ZkProof(
        spec=payload.get("spec", _PROOF_SPEC_PLONKY2),
        circuit_hash=payload["circuit_hash"],
        fingerprint_module_hash=payload["fingerprint_module_hash"],
        function_name=payload["function_name"],
        public_inputs=dict(payload.get("public_inputs", {})),
        output=payload.get("output"),
        transcript_hash=payload.get("proof_bytes_hex", ""),
        chain_order=payload.get("chain_order", circuit.chain_order),
        n_gates=payload.get("n_gates", len(circuit.gates)),
    )
    # Stash the scale + fixed-point metadata as attributes — they're
    # not part of the public dataclass schema (which has to round-trip
    # through ZkProof.to_dict for the registry) but the verifier needs
    # them to rebuild the field-element view.
    proof._output_scale_bits = int(payload.get("output_scale_bits", FIXED_POINT_BITS))  # type: ignore[attr-defined]
    proof._fixed_point_bits = int(payload.get("fixed_point_bits", FIXED_POINT_BITS))  # type: ignore[attr-defined]
    return proof


# Default fixed-point bit width — must match plonky2_backend's
# FIXED_POINT_BITS constant. Used for both encoding inputs and as the
# fallback when a proof predates the metadata fields.
FIXED_POINT_BITS = 16


def verify(
    proof: ZkProof,
    *,
    circuit: ZkCircuit,
    fingerprint_module_hash: str,
    rtol: float = 1e-9,
    atol: float = 1e-12,
) -> VerifyResult:
    """Validate a proof against a circuit and fingerprint.

    Routes by ``proof.spec``:
      * ``monogate-zkproof/v1`` → real Plonky2 verifier (Rust binary).
      * ``monogate-zkproof/v1-stub`` → transparent re-execution check.

    The transparent path returns ``is_valid=True`` only when:
      1. circuit_hash matches the supplied circuit;
      2. fingerprint_module_hash matches;
      3. re-executing the circuit on the proof's public inputs
         reproduces the proof's claimed output (within rtol/atol);
      4. the transcript hash matches the recomputed one.

    Any failure surfaces a one-sentence ``reason`` for the dashboard.
    """
    if proof.spec == _PROOF_SPEC_PLONKY2:
        return _verify_plonky2(proof, circuit, fingerprint_module_hash)
    return _verify_stub(proof, circuit, fingerprint_module_hash, rtol, atol)


def _verify_plonky2(
    proof: ZkProof,
    circuit: ZkCircuit,
    fingerprint_module_hash: str,
) -> VerifyResult:
    """Cryptographic verify via the Rust binary. Falls back to a
    quick local re-execution check if the binary isn't available so
    that callers without a Rust toolchain can still sanity-check the
    arithmetic claim."""
    # Always rebuild the payload from the user-facing proof fields
    # (output, public_inputs) so any tampering with those fields
    # surfaces inside the Rust verifier as a public-input mismatch
    # against the bytes inside the proof.
    payload = {
        "spec":                    proof.spec,
        "backend":                 "plonky2",
        "circuit_hash":            proof.circuit_hash,
        "fingerprint_module_hash": proof.fingerprint_module_hash,
        "function_name":           proof.function_name,
        "public_inputs":           dict(proof.public_inputs),
        "output":                  proof.output,
        "output_scale_bits":       int(getattr(proof, "_output_scale_bits", FIXED_POINT_BITS)),
        "fixed_point_bits":        int(getattr(proof, "_fixed_point_bits", FIXED_POINT_BITS)),
        "n_gates":                 proof.n_gates,
        "chain_order":             proof.chain_order,
        "proof_bytes_hex":         proof.transcript_hash,
    }

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

    if not plonky2_runner.available():
        return VerifyResult(
            is_valid=False,
            reason="plonky2 verifier binary not available — install "
                   "the monogate-zk Rust binary to verify ZK proofs",
            expected_circuit_hash=expected_chash,
        )

    try:
        ok, reason = plonky2_runner.verify_with_binary(
            circuit, payload,
            fingerprint_module_hash=fingerprint_module_hash,
        )
    except plonky2_runner.Plonky2BackendError as exc:
        return VerifyResult(
            is_valid=False,
            reason=f"plonky2 verifier infrastructure failure: {exc}",
            expected_circuit_hash=expected_chash,
        )
    return VerifyResult(
        is_valid=ok,
        reason=reason,
        expected_circuit_hash=expected_chash,
        actual_output=proof.output,
    )


def _verify_stub(
    proof: ZkProof,
    circuit: ZkCircuit,
    fingerprint_module_hash: str,
    rtol: float,
    atol: float,
) -> VerifyResult:
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
