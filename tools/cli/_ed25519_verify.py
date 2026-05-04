"""Pure-stdlib Ed25519 signature verification.

Self-contained so the user-facing transparency-log verifier
(`zk_log_verify.py`, `witness.py`) keeps zero external dependencies.
Implements RFC 8032 §5.1.7 — verify only, no signing.

This is the textbook reference algorithm: small, easy to audit,
fast enough for the witness use case (verifying one STH every
few seconds is trivial). For high-throughput signing or batch
verification, switch to a native crypto library.

Threat model: this code only verifies signatures we know we'll
hash + check on, so we don't need constant-time arithmetic. We do
need to reject malleable / non-canonical encodings the way RFC
8032 specifies, which the implementation below does.
"""

from __future__ import annotations

import hashlib
from typing import Tuple

# Ed25519 domain parameters (RFC 8032 §5.1).
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493  # order of subgroup
_D = (-121665 * pow(121666, -1, _P)) % _P
# B is the standard base point; encoded form is 0x5866...c0a4
_B_Y = 4 * pow(5, -1, _P) % _P


def _modp_inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _x_recover(y: int, sign: int) -> int:
    """Recover the x coordinate from y and the parity bit."""
    xx = (y * y - 1) * _modp_inv(_D * y * y + 1) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        # Adjust by sqrt(-1).
        x = (x * pow(2, (_P - 1) // 4, _P)) % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("invalid point — no square root for x^2")
    if x % 2 != sign:
        x = _P - x
    return x


_B_X = _x_recover(_B_Y, 0)
_B = (_B_X % _P, _B_Y % _P, 1, (_B_X * _B_Y) % _P)


def _point_add(P, Q):
    (x1, y1, z1, t1) = P
    (x2, y2, z2, t2) = Q
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    d = z1 * 2 * z2 % _P
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_mul(s: int, P):
    Q = (0, 1, 1, 0)  # the neutral (identity) element
    while s > 0:
        if s & 1:
            Q = _point_add(Q, P)
        P = _point_add(P, P)
        s >>= 1
    return Q


def _point_equal(P, Q) -> bool:
    if (P[0] * Q[2] - Q[0] * P[2]) % _P != 0:
        return False
    if (P[1] * Q[2] - Q[1] * P[2]) % _P != 0:
        return False
    return True


def _decode_int(b: bytes) -> int:
    return int.from_bytes(b, "little")


def _decode_point(b: bytes):
    if len(b) != 32:
        raise ValueError("ed25519 point must be exactly 32 bytes")
    y = _decode_int(b) & ((1 << 255) - 1)
    sign = b[31] >> 7
    x = _x_recover(y, sign)
    if x == 0 and sign != 0:
        raise ValueError("invalid point — non-canonical x sign")
    return (x, y, 1, (x * y) % _P)


def _sha512(*chunks: bytes) -> bytes:
    h = hashlib.sha512()
    for c in chunks:
        h.update(c)
    return h.digest()


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Return True iff `signature` is a valid Ed25519 signature on
    `message` under `public_key`. Both keys are 32 bytes, signature
    is 64 bytes — the raw byte forms RFC 8032 prescribes."""
    if len(public_key) != 32:
        raise ValueError(f"public key must be 32 bytes, got {len(public_key)}")
    if len(signature) != 64:
        raise ValueError(f"signature must be 64 bytes, got {len(signature)}")

    try:
        A = _decode_point(public_key)
        R = _decode_point(signature[:32])
    except ValueError:
        return False
    s = _decode_int(signature[32:])
    if s >= _L:
        # RFC 8032 §5.1.7 step 1 — reject non-canonical s.
        return False

    h = _decode_int(_sha512(signature[:32], public_key, message)) % _L
    sB = _point_mul(s, _B)
    hA = _point_mul(h, A)
    return _point_equal(sB, _point_add(R, hA))
