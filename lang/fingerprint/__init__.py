"""Computation fingerprinting — Phase 0 of the Monogate Verification Network.

A *computation fingerprint* is the deterministic identity of an EML
function. It composes:

  1. A canonical hash of the function body's typed AST (tamper-evident
     against any meaningful change to the math).
  2. A canonical hash of the parameter signature (name + type).
  3. A canonical hash of the @verify requires/ensures contracts.
  4. The deterministic subset of the profiler's metadata (chain order,
     cost class, depth, drift risk, dynamics counts).
  5. A slot for the MachLib proof certificate hash.
  6. A slot for the C-237 shape-class ID (which of the 76 classes
     this function belongs to).

Module-level fingerprints fold the per-function fingerprints into a
single ``module_hash`` so that one EML source produces one identity
that backends can embed.

Determinism contract:

  * Same source → same fingerprint, on any machine, any Python
    version, any wall clock.
  * Whitespace, comments, line numbers, column numbers, and absolute
    file paths are ignored.
  * Variable names *are* part of the fingerprint — they appear in
    @verify contracts and downstream ZK circuits, so renaming `x`
    to `input` is a real change.

Tamper-evidence contract:

  * Any change to an operator, literal, type, where-clause, contract,
    or function name produces a different ``tree_hash`` (and therefore
    a different ``module_hash``).
  * The hash function is SHA-256.

This module deliberately has *no* runtime dependency on the rest of
Forge beyond ``lang/parser`` — fingerprints can be computed by any
tool that owns an ``EMLModule``.
"""

from __future__ import annotations

from .compute import (
    FINGERPRINT_SPEC,
    FingerprintError,
    FunctionFingerprint,
    ModuleFingerprint,
    canonicalize_function,
    canonicalize_node,
    fingerprint_function,
    fingerprint_module,
    sha256_hex,
)
from .embed import embed_fingerprint, has_embed_support

__all__ = [
    "FINGERPRINT_SPEC",
    "FingerprintError",
    "FunctionFingerprint",
    "ModuleFingerprint",
    "canonicalize_function",
    "canonicalize_node",
    "fingerprint_function",
    "fingerprint_module",
    "sha256_hex",
    "embed_fingerprint",
    "has_embed_support",
]
