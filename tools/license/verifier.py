"""Verify a Forge license token (Ed25519-signed payload).

Token format
------------
    v1.<base64url(payload_json)>.<base64url(signature)>

Payload is JSON:
    {
      "email":   "user@example.com",
      "tier":    "free" | "pro",
      "iat":     "2026-05-01",       (issued, ISO date)
      "exp":     "2027-05-01",       (expires, ISO date — optional)
      "nonce":   "<random hex>"      (optional, for revocation)
    }

The verifier checks:
- The signature matches the embedded public key
- `tier` is "free" or "pro"
- `exp`, if present, is in the future

A missing license is NOT an error -- callers fall back to the
Free tier. An invalid license IS an error so a tampered token
fails loudly instead of silently downgrading.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


# Public key in base64url (raw 32 bytes Ed25519). The matching
# private key is held by the issuer at monogateforge.com and is
# NOT shipped in any wheel. Rotation is a CLI release away.
PUBLIC_KEY_B64 = "iDqeS44SGhVALHevTY6J8XLctHayJpIt82o2QhQmK0I="


# Tier definitions. Targets not listed default to Free so a
# brand-new backend (e.g. a research target) doesn't accidentally
# get gated until we explicitly tier it.
FREE_TARGETS: frozenset[str] = frozenset({
    "c", "cpp", "rust", "python", "go", "java", "kotlin",
    "lean", "matlab",
    # Web / mobile / desktop runtimes — added to Free tier
    # 2026-05-02 to broaden the on-ramp for application
    # developers. WebAssembly belongs alongside JS for the
    # browser/edge story.
    "javascript", "wasm", "csharp",
})

PRO_TARGETS: frozenset[str] = frozenset({
    # Hardware
    "verilog", "systemverilog", "vhdl", "chisel",
    # Safety-critical / automotive
    "ada", "autosar", "aadl", "ros2",
    # Compiler IRs
    "llvm",
    # Formal verification (beyond Lean)
    "coq", "isabelle",
    # Blockchain
    "solidity",
    # GPU shaders
    "hlsl", "glsl", "glsles", "wgsl", "metal",
    # Mobile (Apple)
    "swift",
    # Gaming
    "luau", "gdscript",
})


class LicenseError(Exception):
    """Invalid license token (bad signature, expired, or malformed)."""


@dataclass(frozen=True)
class License:
    """Parsed + verified license payload."""
    email: str
    tier: str  # "free" | "pro"
    issued_at: str
    expires_at: str | None = None
    nonce: str | None = None

    def is_expired(self, today: date | None = None) -> bool:
        if not self.expires_at:
            return False
        ref = today or date.today()
        try:
            return date.fromisoformat(self.expires_at) < ref
        except ValueError:
            return True


# ─── token I/O ────────────────────────────────────────────────────

def load_license() -> License | None:
    """Look in env var, then config file. Returns None when no
    license is present (caller falls back to Free tier). Raises
    LicenseError when a token is present but invalid."""
    raw = os.environ.get("MONOGATE_LICENSE", "").strip()
    if not raw:
        cfg = Path.home() / ".monogate" / "license"
        if cfg.is_file():
            raw = cfg.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    return verify_token(raw)


def verify_token(token: str) -> License:
    """Parse + signature-check + expiry-check a license token.
    Raises LicenseError on any failure."""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1":
        raise LicenseError("malformed token (expected v1.<payload>.<sig>)")
    try:
        payload_bytes = _b64url_decode(parts[1])
        sig_bytes = _b64url_decode(parts[2])
    except Exception as e:
        raise LicenseError(f"malformed base64: {e}")

    if not _ed25519_verify(payload_bytes, sig_bytes):
        raise LicenseError("signature does not match Forge public key")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as e:
        raise LicenseError(f"payload is not valid JSON: {e}")

    tier = payload.get("tier")
    if tier not in ("free", "pro"):
        raise LicenseError(f"unknown tier {tier!r}")

    license_ = License(
        email=str(payload.get("email", "")),
        tier=tier,
        issued_at=str(payload.get("iat", "")),
        expires_at=payload.get("exp"),
        nonce=payload.get("nonce"),
    )
    if license_.is_expired():
        raise LicenseError(
            f"license expired on {license_.expires_at} -- renew at "
            f"https://monogateforge.com/get-started")
    return license_


# ─── tier gate ────────────────────────────────────────────────────

def target_allowed(target: str, license_: License | None) -> bool:
    """True iff `target` is permitted under the resolved license.

    No license means Free tier -- only FREE_TARGETS pass. A Pro
    license unlocks PRO_TARGETS in addition. The 'all' meta-target
    is always allowed; the dispatcher iterates and re-checks each
    underlying target individually so it skips Pro entries when the
    user is on Free.
    """
    if target == "all":
        return True
    if target in FREE_TARGETS:
        return True
    if target in PRO_TARGETS:
        return license_ is not None and license_.tier == "pro"
    # Unknown target: fail open so a new backend doesn't silently
    # break the dispatcher; the CLI will catch the bad name later.
    return True


# ─── crypto primitives ────────────────────────────────────────────

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _ed25519_verify(message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature against the embedded public key.
    Returns False on any failure (bad signature, malformed key,
    library missing); never raises."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
        from cryptography.exceptions import InvalidSignature
        pk = Ed25519PublicKey.from_public_bytes(
            _b64url_decode(PUBLIC_KEY_B64),
        )
        try:
            pk.verify(signature, message)
            return True
        except InvalidSignature:
            return False
    except ImportError:
        # cryptography not installed -- treat as unverifiable so
        # the user sees a clear error rather than a silent allow.
        raise LicenseError(
            "license verification requires the `cryptography` package"
        )
