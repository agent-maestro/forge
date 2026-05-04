"""Unit tests for the witness client + ed25519 verifier.

Doesn't require a running registry — exercises the pure-function
verifiers (consistency-proof check, signature check, ed25519 verify
against RFC 8032 vectors) in isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CLI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CLI_DIR))

from _ed25519_verify import verify as ed25519_verify  # noqa: E402
from log_witness import (  # noqa: E402
    _node_hash,
    _verify_consistency,
    _verify_signature,
)


# ── RFC 8032 §7.1 known-answer vectors ──────────────────────────


@pytest.mark.parametrize(
    "pk_hex, msg_hex, sig_hex",
    [
        # Test 1 — empty message
        (
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
            "",
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
        ),
        # Test 2 — single-byte
        (
            "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
            "72",
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
        ),
        # Test 3 — 2 bytes
        (
            "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
            "af82",
            "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
        ),
    ],
)
def test_ed25519_rfc8032_vectors(pk_hex: str, msg_hex: str, sig_hex: str) -> None:
    pk = bytes.fromhex(pk_hex)
    msg = bytes.fromhex(msg_hex) if msg_hex else b""
    sig = bytes.fromhex(sig_hex)
    assert ed25519_verify(pk, msg, sig)


def test_ed25519_rejects_tampered_signature() -> None:
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytearray(bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    ))
    sig[0] ^= 0x01
    assert not ed25519_verify(pk, b"", bytes(sig))


def test_ed25519_rejects_tampered_message() -> None:
    pk = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
    sig = bytes.fromhex(
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
    )
    assert not ed25519_verify(pk, b"\x73", sig)  # wrong byte


# ── Consistency-proof verifier ──────────────────────────────────


def _leaf(b: bytes) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(b"\x00" + b).hexdigest()


def _build_root(leaves: list[str]) -> str:
    """Reference Merkle root, mirrors merkleRoot() in TS for the test."""
    if not leaves:
        import hashlib
        return "sha256:" + hashlib.sha256(b"").hexdigest()
    if len(leaves) == 1:
        return leaves[0]
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    return _node_hash(_build_root(leaves[:k]), _build_root(leaves[k:]))


def _consistency_proof(leaves: list[str], m: int) -> list[str]:
    """Reference consistency-proof generator (mirror of TS)."""
    n = len(leaves)
    if m == 0 or m == n:
        return []
    return _sub_proof(leaves[:n], m, True)


def _sub_proof(leaves: list[str], m: int, b: bool) -> list[str]:
    if m == len(leaves):
        return [] if b else [_build_root(leaves)]
    k = 1
    while k * 2 < len(leaves):
        k *= 2
    if m <= k:
        return _sub_proof(leaves[:k], m, b) + [_build_root(leaves[k:])]
    return _sub_proof(leaves[k:], m - k, False) + [_build_root(leaves[:k])]


def test_consistency_proof_accepts_valid_extension() -> None:
    leaves = [_leaf(bytes([i])) for i in range(7)]
    for m in range(1, 7):
        for n in range(m + 1, 8):
            proof = _consistency_proof(leaves[:n], m)
            ok, reason = _verify_consistency(
                old_root=_build_root(leaves[:m]),
                old_size=m,
                new_root=_build_root(leaves[:n]),
                new_size=n,
                proof=proof,
            )
            assert ok, f"m={m} n={n}: {reason}"


def test_consistency_proof_rejects_rewritten_root() -> None:
    leaves = [_leaf(bytes([i])) for i in range(5)]
    proof = _consistency_proof(leaves, 3)
    bad_new_root = "sha256:" + ("e" * 64)
    ok, _ = _verify_consistency(
        old_root=_build_root(leaves[:3]),
        old_size=3,
        new_root=bad_new_root,
        new_size=5,
        proof=proof,
    )
    assert not ok


def test_consistency_proof_rejects_size_regression() -> None:
    ok, reason = _verify_consistency(
        old_root="sha256:" + ("a" * 64),
        old_size=5,
        new_root="sha256:" + ("b" * 64),
        new_size=3,
        proof=[],
    )
    assert not ok
    assert "bad sizes" in reason


# ── STH signature wrapper ───────────────────────────────────────


def test_signature_verify_rejects_missing_signature() -> None:
    sth = {"signed_payload": "anything", "signature": ""}
    ok, reason = _verify_signature(sth, "00" * 32)
    assert not ok
    assert "no signature" in reason


def test_signature_verify_rejects_unknown_suite() -> None:
    sth = {"signed_payload": "x", "signature": "rsa:abc"}
    ok, reason = _verify_signature(sth, "00" * 32)
    assert not ok
    assert "unsupported" in reason
