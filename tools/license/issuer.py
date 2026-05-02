"""Issue Forge license tokens.

NOT shipped to end users. Run from the issuance backend (the
service that handles signups + payments at monogateforge.com).

The private key MUST live outside the repo. Pass it via env:

    MONOGATE_FORGE_SIGNING_KEY=<base64url-32-bytes> \\
    python tools/license/issuer.py \\
        --email user@example.com \\
        --tier pro \\
        --expires 2027-05-01

Output is a single token line: `v1.<payload>.<sig>`. Store with
the user's account; deliver via email or licensing portal.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
from datetime import date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge-issue-license")
    parser.add_argument("--email", required=True)
    parser.add_argument("--tier", required=True, choices=["free", "pro"])
    parser.add_argument(
        "--expires",
        help="Expiration date (ISO YYYY-MM-DD). Omit for no expiry.",
    )
    args = parser.parse_args(argv)

    sk_b64 = os.environ.get("MONOGATE_FORGE_SIGNING_KEY", "").strip()
    if not sk_b64:
        print("MONOGATE_FORGE_SIGNING_KEY env var is required",
              file=sys.stderr)
        return 1

    payload: dict[str, str] = {
        "email": args.email,
        "tier": args.tier,
        "iat": date.today().isoformat(),
        "nonce": secrets.token_hex(8),
    }
    if args.expires:
        payload["exp"] = args.expires

    payload_bytes = json.dumps(
        payload, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")

    sig = _sign(payload_bytes, sk_b64)

    token = ".".join([
        "v1",
        _b64url_encode(payload_bytes),
        _b64url_encode(sig),
    ])
    print(token)
    return 0


def _sign(message: bytes, sk_b64: str) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )
    sk = Ed25519PrivateKey.from_private_bytes(_b64url_decode(sk_b64))
    return sk.sign(message)


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


if __name__ == "__main__":
    raise SystemExit(main())
