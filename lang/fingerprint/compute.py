"""Core fingerprinting algorithms — canonicalization + hashing.

The canonical form of an AST is a deterministic JSON-serialisable
shape. We then encode it with sorted keys and no whitespace, and
SHA-256 the UTF-8 bytes. Same source → same fingerprint, byte for
byte, on any machine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from lang.parser.ast_nodes import (
    Annotation,
    ASTNode,
    EMLConstant,
    EMLFunction,
    EMLImport,
    EMLModule,
    EMLTypeAlias,
    NodeKind,
    Param,
    WhereClause,
)


FINGERPRINT_SPEC = "monogate-fingerprint/v1"
"""Wire-protocol identifier. Every fingerprint stamps this string so
verifiers can route old/new schemas to the right validator without
guessing."""


class FingerprintError(Exception):
    """Raised when an AST contains a node we don't know how to canonicalise.

    This should never fire in production — every NodeKind the parser
    can emit is handled. If it does fire, treat it as a bug in this
    module rather than a user error.
    """


# ── Public dataclasses ──────────────────────────────────────────────


@dataclass
class FunctionFingerprint:
    """Fingerprint for a single ``fn`` declaration."""

    name: str
    tree_hash: str
    """SHA-256 of the canonical AST body (with parameter signatures
    folded in). Tamper-evident against any meaningful math change."""
    param_hash: str
    """SHA-256 of the sorted ``(name, type)`` parameter list."""
    verify_hash: Optional[str]
    """SHA-256 of the (requires, ensures, where) contracts. ``None`` if
    no contracts are declared."""
    profile: dict
    """Deterministic subset of the profiler output: chain_order,
    eml_depth, cost_class, fp16_drift_risk, node_count, dynamics."""
    machlib_cert_hash: Optional[str] = None
    """Hash of the MachLib proof certificate, when one exists. The
    fingerprinter doesn't compute this; it's slotted in by the
    MachLib resolver."""
    shape_class_id: Optional[int] = None
    """C-237 shape-class ID (0..75) — null until the genome
    classifier runs."""


@dataclass
class ModuleFingerprint:
    """Fingerprint for one ``.eml`` module."""

    spec: str
    """Wire-protocol identifier — always ``FINGERPRINT_SPEC``."""
    version: str
    """Schema version (semver) of *this* fingerprint document."""
    module: dict
    """``{"name": str, "source_file": str, "imports": [str, …]}``.
    ``source_file`` is the basename; absolute paths leak the build
    machine's filesystem layout and are deliberately stripped."""
    functions: list[FunctionFingerprint] = field(default_factory=list)
    module_hash: str = ""
    """SHA-256 over the canonical concatenation of every function's
    ``tree_hash`` plus the module identity. One number that names
    this entire ``.eml`` source."""

    def to_json(self, *, indent: Optional[int] = 2) -> str:
        """Serialise as JSON (pretty by default; pass ``indent=None``
        for the wire form)."""
        payload = {
            "spec":     self.spec,
            "version":  self.version,
            "module":   self.module,
            "functions": [asdict(fn) for fn in self.functions],
            "module_hash": self.module_hash,
        }
        if indent is None:
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return json.dumps(payload, sort_keys=True, indent=indent)


# ── Canonicalisation ────────────────────────────────────────────────


def canonicalize_node(node: Optional[ASTNode]) -> Any:
    """Reduce an :class:`ASTNode` to a deterministic JSON-serialisable
    shape.

    The shape is intentionally compact — tests in ``tests/`` lock in
    that any meaningful change produces a different output and any
    cosmetic change does not.
    """
    if node is None:
        return None
    if not isinstance(node, ASTNode):
        # Defensive: ensure the parser has handed us what it claims.
        raise FingerprintError(
            f"canonicalize_node: expected ASTNode, got {type(node).__name__}"
        )
    return {
        "k": node.kind.value,
        "v": _canonical_value(node.value),
        "t": node.type_annotation,
        "cc": _canonical_chain_constraint(node.chain_constraint),
        "c": [canonicalize_node(child) for child in node.children],
    }


def _canonical_value(value: Any) -> Any:
    """Reduce a node's ``value`` to a JSON-friendly atom.

    Floats, ints, strings, and ``None`` pass through; everything else
    becomes its ``repr`` so we stay deterministic even if the parser
    one day stores something exotic.
    """
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        # repr(float) is round-trip-stable in Python ≥ 3.1, so two
        # machines that read the same source produce the same string.
        return repr(value)
    return repr(value)


def _canonical_chain_constraint(cc: Optional[dict]) -> Optional[dict]:
    if cc is None:
        return None
    return {k: cc[k] for k in sorted(cc)}


def _canonical_param(p: Param) -> dict:
    return {"n": p.name, "t": p.type_name}


def _canonical_where(w: WhereClause) -> dict:
    return {
        "k": w.kind,
        "o": w.op,
        "v": canonicalize_node(w.value)
              if isinstance(w.value, ASTNode)
              else _canonical_value(w.value),
    }


def _canonical_annotation(a: Annotation) -> dict:
    # Annotations carry an args dict where keys may be ints (positional
    # args) or strs (keyword args). Coerce all keys to str so sorting
    # is well-defined and JSON encoding works.
    sorted_keys = sorted(a.args, key=str)
    return {
        "k": a.kind,
        "args": {str(k): _canonical_arg_value(a.args[k]) for k in sorted_keys},
    }


def _canonical_arg_value(v: Any) -> Any:
    if isinstance(v, ASTNode):
        return canonicalize_node(v)
    if isinstance(v, list):
        return [_canonical_arg_value(item) for item in v]
    if isinstance(v, dict):
        sorted_keys = sorted(v, key=str)
        return {str(k): _canonical_arg_value(v[k]) for k in sorted_keys}
    return _canonical_value(v)


def canonicalize_function(fn: EMLFunction) -> dict:
    """Reduce a function declaration to a deterministic shape.

    Includes name, params, return type, where-clauses, contracts,
    and body. Source-location and profile metadata are excluded —
    the profile becomes the *separately-hashed* metadata field of the
    fingerprint, not part of the tree hash.
    """
    return {
        "name":   fn.name,
        "params": [_canonical_param(p) for p in fn.params],
        "ret":    fn.return_type if not fn.return_tuple_types
                   else f"tuple({','.join(fn.return_tuple_types)})",
        "ret_constraint": _canonical_chain_constraint(fn.return_constraint),
        "where":  [_canonical_where(w) for w in fn.where_clauses],
        "body":   canonicalize_node(fn.body),
        "is_extern": fn.is_extern,
    }


def _canonical_contracts(fn: EMLFunction) -> dict:
    """Pull out the parts that constitute the @verify contract surface.

    Where-clauses double as preconditions on parameter domains and
    return chain order, so they belong here too.
    """
    return {
        "requires": [canonicalize_node(r) for r in fn.requires],
        "ensures":  [canonicalize_node(e) for e in fn.ensures],
        "where":    [_canonical_where(w) for w in fn.where_clauses],
        "annotations_verify": [
            _canonical_annotation(a) for a in fn.annotations
            if a.kind == "verify"
        ],
    }


# ── Hashing helpers ─────────────────────────────────────────────────


def sha256_hex(canonical: Any) -> str:
    """Hash any JSON-serialisable canonical structure.

    Always uses ``sort_keys=True`` and the most compact separators so
    the byte representation is identical across runs.
    """
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


# ── Public entry points ─────────────────────────────────────────────


# Profile keys we keep — these are the deterministic ones. FPGA
# estimates (mac_units, exp_units, …) depend on synthesis target
# config and are explicitly out of the fingerprint surface.
_PROFILE_KEYS = (
    "chain_order",
    "eml_depth",
    "cost_class",
    "fp16_drift_risk",
    "node_count",
    "max_path_r",
    "status",
)


def _trim_profile(profile: Optional[dict]) -> dict:
    if not profile:
        return {}
    out = {k: profile[k] for k in _PROFILE_KEYS if k in profile}
    dyn = profile.get("dynamics") or {}
    out["dynamics"] = {
        "oscillations":  dyn.get("oscillations", 0),
        "decays":        dyn.get("decays", 0),
        "predicted_r":   dyn.get("predicted_r", 0),
    }
    return out


def fingerprint_function(fn: EMLFunction) -> FunctionFingerprint:
    """Compute the fingerprint of one function."""
    body_canon = canonicalize_function(fn)
    contracts_canon = _canonical_contracts(fn)
    has_contracts = (
        bool(contracts_canon["requires"])
        or bool(contracts_canon["ensures"])
        or bool(contracts_canon["where"])
        or bool(contracts_canon["annotations_verify"])
    )
    return FunctionFingerprint(
        name=fn.name,
        tree_hash=sha256_hex(body_canon),
        param_hash=sha256_hex([_canonical_param(p) for p in fn.params]),
        verify_hash=sha256_hex(contracts_canon) if has_contracts else None,
        profile=_trim_profile(fn.profile),
    )


_FINGERPRINT_SCHEMA_VERSION = "0.1.0"


def fingerprint_module(mod: EMLModule) -> ModuleFingerprint:
    """Compute the fingerprint of an entire ``.eml`` module."""
    fns = [fingerprint_function(fn) for fn in mod.functions]

    module_identity = {
        "name":    mod.name or "",
        "imports": sorted(imp.joined for imp in mod.imports),
        "constants": [
            {"n": c.name, "t": c.type_name, "v": canonicalize_node(c.value)}
            for c in sorted(mod.constants, key=lambda x: x.name)
        ],
        "types": [
            {
                "n": t.name,
                "b": t.base_type,
                "c": _canonical_chain_constraint(t.constraint),
            }
            for t in sorted(mod.types, key=lambda x: x.name)
        ],
        "fn_hashes": [
            {"n": fn.name,
             "tree": fn.tree_hash,
             "params": fn.param_hash,
             "verify": fn.verify_hash}
            for fn in fns
        ],
    }
    module_hash = sha256_hex(module_identity)

    # Strip the absolute path from source_file — we want determinism
    # across machines, and `/home/build/x/y/foo.eml` would defeat that.
    source_basename = ""
    if mod.source_file and mod.source_file != "<unknown>":
        from os.path import basename
        source_basename = basename(mod.source_file)

    return ModuleFingerprint(
        spec=FINGERPRINT_SPEC,
        version=_FINGERPRINT_SCHEMA_VERSION,
        module={
            "name":        mod.name or "",
            "source_file": source_basename,
            "imports":     sorted(imp.joined for imp in mod.imports),
        },
        functions=fns,
        module_hash=module_hash,
    )
