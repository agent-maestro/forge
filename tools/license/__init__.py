"""Forge license verification.

Open-core gate. The CLI is free to install; the Free tier
(12 application + Lean backends — C / C++ / Rust / Python / Go /
Java / Kotlin / C# / JavaScript / WebAssembly / MATLAB / Lean 4)
works without any license. Pro tier backends (FPGA, GPU shaders,
safety-critical, Coq/Isabelle, Solidity, Apple Swift, gaming)
check for a signed license token at runtime.

License resolution order (first hit wins):
1. `MONOGATE_LICENSE` environment variable
2. `~/.monogate/license` file

Token format: `v1.<base64url(json)>.<base64url(ed25519 sig)>`
The verifier in tools.license.verifier checks the signature
against an Ed25519 public key embedded in the CLI; the matching
private key is held only by the issuer at monogateforge.com.
"""

from .verifier import (
    FREE_TARGETS, PRO_TARGETS, License, LicenseError,
    load_license, target_allowed,
)

__all__ = [
    "FREE_TARGETS", "PRO_TARGETS", "License", "LicenseError",
    "load_license", "target_allowed",
]
