"""Python ↔ Rust bridge for the real Plonky2 ZK backend.

Subprocess-shells out to the ``monogate-zk`` binary built from
``plonky2_backend/``. The binary speaks JSON in / JSON out so this
file can stay a thin orchestration layer and the Python prover module
can decide per-circuit whether to use the real backend or the
transparent stub.

Discovery order for the binary:

  1. ``MONOGATE_ZK_BIN`` env var, if set.
  2. ``plonky2_backend/target/release/monogate-zk`` next to this file
     (the canonical dev location).
  3. ``monogate-zk`` on ``$PATH``.

If none of those resolve, :func:`available` returns False and the
caller is expected to fall back to the transparent stub.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .circuit import ZkCircuit, circuit_to_dict


_BACKEND_DIR = Path(__file__).resolve().parent / "plonky2_backend"
_DEFAULT_BINARY = _BACKEND_DIR / "target" / "release" / "monogate-zk"


# ── Discovery + capabilities ──────────────────────────────────────


def binary_path() -> Optional[Path]:
    """Resolve the path to the monogate-zk binary, or None when it
    hasn't been built yet."""
    env = os.environ.get("MONOGATE_ZK_BIN")
    if env:
        p = Path(env).expanduser()
        return p if p.is_file() and os.access(p, os.X_OK) else None
    if _DEFAULT_BINARY.is_file() and os.access(_DEFAULT_BINARY, os.X_OK):
        return _DEFAULT_BINARY
    on_path = shutil.which("monogate-zk")
    return Path(on_path) if on_path else None


def available() -> bool:
    """True iff the binary exists and is executable. Cheap to call."""
    return binary_path() is not None


@dataclass(frozen=True)
class Capabilities:
    spec: str
    backend: str
    field: str
    fixed_point_bits: int
    supported_gates: tuple[str, ...]
    deferred_gates: tuple[str, ...]


def capabilities() -> Optional[Capabilities]:
    """Ask the binary what it can prove. None when the binary isn't
    available — caller falls back to the transparent stub."""
    bin_ = binary_path()
    if bin_ is None:
        return None
    try:
        completed = subprocess.run(
            [str(bin_), "capabilities"],
            check=True, capture_output=True, text=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError):
        return None
    payload = json.loads(completed.stdout)
    return Capabilities(
        spec=payload["spec"],
        backend=payload["backend"],
        field=payload["field"],
        fixed_point_bits=int(payload["fixed_point_bits"]),
        supported_gates=tuple(payload["supported_gates"]),
        deferred_gates=tuple(payload["deferred_gates"]),
    )


def can_prove(circuit: ZkCircuit) -> bool:
    """Cheap pre-check: every gate in `circuit` must be in the
    binary's supported set. Saves the cost of starting a subprocess
    for circuits we know will be rejected."""
    caps = capabilities()
    if caps is None:
        return False
    supported = set(caps.supported_gates)
    return all(g.kind.value in supported for g in circuit.gates)


# ── Prove / Verify ────────────────────────────────────────────────


class Plonky2BackendError(RuntimeError):
    """Raised when the binary is missing or returns an error."""


def prove_with_binary(
    circuit: ZkCircuit,
    *,
    inputs: Mapping[str, float],
    fingerprint_module_hash: str,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """Invoke `monogate-zk prove`. Returns the parsed proof JSON.

    Raises :class:`Plonky2BackendError` when the binary is missing,
    times out, or rejects the circuit. The caller decides whether to
    fall back to the transparent stub.
    """
    bin_ = binary_path()
    if bin_ is None:
        raise Plonky2BackendError(
            "monogate-zk binary not found. Build it with "
            "`cargo build --release` in lang/zkproof/plonky2_backend/, "
            "or set MONOGATE_ZK_BIN."
        )

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        circuit_path = tdp / "circuit.json"
        proof_path = tdp / "proof.json"
        circuit_path.write_text(json.dumps(circuit_to_dict(circuit)),
                                encoding="utf-8")
        inputs_json = json.dumps({k: float(v) for k, v in inputs.items()})
        try:
            completed = subprocess.run(
                [
                    str(bin_), "prove",
                    "--circuit", str(circuit_path),
                    "--inputs", inputs_json,
                    "--fingerprint", fingerprint_module_hash,
                    "--out", str(proof_path),
                ],
                check=False, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise Plonky2BackendError(
                f"prove timed out after {timeout}s"
            ) from e
        if completed.returncode != 0:
            raise Plonky2BackendError(
                f"prove failed (exit {completed.returncode}): "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        if not proof_path.is_file():
            raise Plonky2BackendError(
                "prove succeeded but produced no proof file"
            )
        return json.loads(proof_path.read_text(encoding="utf-8"))


def verify_with_binary(
    circuit: ZkCircuit,
    proof: Mapping[str, Any],
    *,
    fingerprint_module_hash: str,
    timeout: float = 60.0,
) -> tuple[bool, str]:
    """Invoke `monogate-zk verify`. Returns (is_valid, reason).

    Raises :class:`Plonky2BackendError` only for infrastructure
    failures (binary missing, timeout). A valid binary that says
    "the proof doesn't verify" returns ``(False, "reason")``.
    """
    bin_ = binary_path()
    if bin_ is None:
        raise Plonky2BackendError(
            "monogate-zk binary not found"
        )

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        circuit_path = tdp / "circuit.json"
        proof_path = tdp / "proof.json"
        circuit_path.write_text(json.dumps(circuit_to_dict(circuit)),
                                encoding="utf-8")
        proof_path.write_text(json.dumps(proof), encoding="utf-8")
        try:
            completed = subprocess.run(
                [
                    str(bin_), "verify",
                    "--circuit", str(circuit_path),
                    "--proof", str(proof_path),
                    "--fingerprint", fingerprint_module_hash,
                ],
                check=False, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise Plonky2BackendError(
                f"verify timed out after {timeout}s"
            ) from e

    # The CLI prints `{"is_valid": ..., "reason": ...}` on stdout
    # regardless of exit code; exit code mirrors validity.
    out = completed.stdout.strip()
    if not out:
        raise Plonky2BackendError(
            f"verify produced no output (exit {completed.returncode}): "
            f"{completed.stderr.strip()}"
        )
    try:
        env = json.loads(out)
    except json.JSONDecodeError as e:
        raise Plonky2BackendError(
            f"verify produced unparseable output: {out!r}"
        ) from e
    return bool(env.get("is_valid")), str(env.get("reason", ""))


__all__ = [
    "Capabilities",
    "Plonky2BackendError",
    "available",
    "binary_path",
    "can_prove",
    "capabilities",
    "prove_with_binary",
    "verify_with_binary",
]
