"""Formal-spec sidecar exporter for the Solidity backend.

Produces a machine-readable JSON that mirrors every contract the
Solidity backend emits. The spec is what an auditor diffs against
the on-chain bytecode: it captures the EML `requires` / `ensures`
clauses, the Lean theorem reference, the Pfaffian profile, and the
gas estimate in a stable shape that does not depend on Solidity
formatting quirks.

  forge --target solidity --spec-bundle path/foo.eml
    ⇒ writes both `path/foo.sol` and `path/foo.spec.json`

The .sol file is the deployable artifact; the .spec.json is the
audit hook. They live side-by-side so a CI pipeline can verify
that any change to the .sol carries a matching change to the spec
(`git diff --stat foo.sol foo.spec.json`).

Spec versioning
---------------
``spec_version`` is bumped on every breaking shape change. v1 is
the initial release; readers should reject unknown major versions
rather than guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from lang.parser.ast_nodes import (
    Annotation,
    EMLFunction,
    EMLModule,
)

from software.backends.solidity_backend import (
    CompileError,
    SolidityBackend,
    _contract_name,
    _sol_type,
    _to_camel,
)
from software.backends.solidity_gas import (
    estimate_function_gas,
)


SPEC_VERSION = "1"
COMPILER_NAME = "monogate-forge"


def _compiler_version() -> str:
    """Resolve the package version, falling back to "unknown" when
    monogate-forge is run from a checkout that hasn't been installed."""
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("monogate-forge")
        except PackageNotFoundError:
            return "0.0.0+src"
    except Exception:
        return "unknown"


@dataclass(frozen=True)
class SpecBundle:
    """A .sol source paired with its .spec.json audit sidecar."""
    solidity_source: str
    spec: dict[str, Any]

    def spec_json(self, *, indent: int | None = 2) -> str:
        """Render the spec as a deterministic JSON string. Keys are
        sorted so a diff stays stable across Python dict orderings."""
        return json.dumps(self.spec, indent=indent, sort_keys=True)


# ── Public API ──────────────────────────────────────────────────────


def build_bundle(
    mod: EMLModule, *, backend: SolidityBackend | None = None,
) -> SpecBundle:
    """Compile ``mod`` once and return both the .sol source and the
    structured spec sidecar. Reusing one backend instance keeps the
    NatSpec-emitted gas numbers and the spec-sidecar gas numbers in
    lock-step (they are computed from the same `estimate_function_gas`
    function, so divergence would mean someone mis-edited one path)."""
    backend = backend or SolidityBackend()
    sol_src = backend.compile(mod)
    spec = build_spec(mod, backend=backend)
    return SpecBundle(solidity_source=sol_src, spec=spec)


def build_spec(
    mod: EMLModule, *, backend: SolidityBackend | None = None,
) -> dict[str, Any]:
    """Build the structured spec dict for a parsed EML module."""
    backend = backend or SolidityBackend()
    return {
        "spec_version": SPEC_VERSION,
        "compiler": {
            "name": COMPILER_NAME,
            "version": _compiler_version(),
            "backend": backend.name,
        },
        "module": mod.name,
        "source_file": mod.source_file,
        "contract": _contract_name(mod),
        "constants": [
            {"name": c.name, "type": c.type_name}
            for c in mod.constants
        ],
        "functions": [
            _function_spec(fn, backend=backend)
            for fn in mod.functions
            if not fn.is_extern
        ],
    }


# ── Per-function spec ───────────────────────────────────────────────


def _function_spec(
    fn: EMLFunction, *, backend: SolidityBackend,
) -> dict[str, Any]:
    is_verified = any(_is_lean_verify(a) for a in fn.annotations)
    spec: dict[str, Any] = {
        "name": fn.name,
        "solidity_name": _to_camel(fn.name),
        "visibility": "external" if is_verified else "internal",
        "params": [
            {
                "name": p.name,
                "solidity_name": _to_camel(p.name),
                "eml_type": p.type_name,
                "solidity_type": _sol_type(p.type_name),
            }
            for p in fn.params
        ],
        "returns": _returns_spec(fn),
        "verified": is_verified,
        "preconditions": _precondition_specs(fn, backend),
        "postconditions": _postcondition_specs(fn, backend),
    }
    if is_verified:
        spec["verification"] = _verification_spec(fn)
    if fn.profile is not None and fn.profile.get("status") != "complex_body":
        spec["pfaffian_profile"] = {
            k: fn.profile[k]
            for k in ("chain_order", "cost_class",
                      "fp16_drift_risk", "node_count", "eml_depth")
            if k in fn.profile
        }
    if fn.body is not None:
        spec["gas_estimate"] = estimate_function_gas(fn)
    return spec


def _returns_spec(fn: EMLFunction) -> dict[str, Any]:
    if fn.return_tuple_types:
        return {
            "kind": "tuple",
            "eml_types": list(fn.return_tuple_types),
            "solidity_types": [_sol_type(t) for t in fn.return_tuple_types],
        }
    return {
        "kind": "scalar",
        "eml_type": fn.return_type or "Real",
        "solidity_type": _sol_type(fn.return_type or "Real"),
    }


def _verification_spec(fn: EMLFunction) -> dict[str, str]:
    annot = next(
        (a for a in fn.annotations if _is_lean_verify(a)),
        None,
    )
    if annot is None:
        return {"system": "lean", "theorem": fn.name, "library": "MachLib"}
    return {
        "system": "lean",
        "theorem": str(annot.args.get("theorem", fn.name)),
        "library": "MachLib",
    }


def _precondition_specs(
    fn: EMLFunction, backend: SolidityBackend,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in fn.requires:
        try:
            cond = backend._emit_expr(r)
        except CompileError as e:
            out.append({
                "eml_source_line": str(r.line),
                "status": "unsupported",
                "error": str(e),
            })
            continue
        out.append({
            "solidity_require": cond,
            "guard_message": f"{fn.name}: requires {cond}",
            "eml_source_line": str(r.line),
        })
    return out


def _postcondition_specs(
    fn: EMLFunction, backend: SolidityBackend,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in fn.ensures:
        try:
            cond = backend._emit_expr(r, result_subst="result")
        except CompileError as e:
            out.append({
                "eml_source_line": str(r.line),
                "status": "unsupported",
                "error": str(e),
            })
            continue
        out.append({
            "expression": cond,
            "natspec_dev": f"ensures: {cond}",
            "eml_source_line": str(r.line),
        })
    return out


def _is_lean_verify(a: Annotation) -> bool:
    if a.kind != "verify":
        return False
    return a.args.get(0) == "lean"
