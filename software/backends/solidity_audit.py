"""Audit-bundle packager for the Solidity backend.

Bundles the deployable .sol, the .spec.json sidecar, the EML source,
matching MachLib Lean proofs, and a manifest with sha256 of every
artifact into one directory an auditor can drop into a repo or
attach to a smart-contract audit report.

Layout
------
::

    <stem>_audit/
        contract.sol         # deployable Solidity (S-1 NatSpec gas
                             # annotations included)
        spec.json            # structured formal spec (S-2)
        source.eml           # the EML source the .sol was rendered from
        proofs/
            <theorem>.lean   # one file per @verify(lean,
                             # theorem=...) annotation; copied from
                             # MachLib if the theorem can be located,
                             # otherwise a MISSING.txt stub
        manifest.json        # sha256 + byte size of every artifact
                             # plus compiler version + spec_version
        AUDITOR.md           # one-page reading guide

The manifest gives auditors a single hash to pin in a report; the
proofs/ subfolder gives them the verifier-checked statements that
back the on-chain require()/ensures lines.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lang.parser.ast_nodes import EMLModule

from software.backends.solidity_backend import SolidityBackend
from software.backends.solidity_spec import (
    SPEC_VERSION,
    _compiler_version,
    build_spec,
)


AUDIT_BUNDLE_VERSION = "1"


# ── Result type ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class AuditBundle:
    """Files written + the manifest, returned for inspection / tests."""
    root: Path
    files: tuple[Path, ...]
    manifest: dict


# ── Public API ──────────────────────────────────────────────────────


def write_audit_bundle(
    mod: EMLModule,
    *,
    eml_source_path: Path,
    out_root: Path,
    backend: SolidityBackend | None = None,
    machlib_root: Path | None = None,
    with_prbmath: bool = True,
    with_foundry_tests: bool = True,
) -> AuditBundle:
    """Build and write a complete audit bundle for ``mod``.

    Parameters
    ----------
    mod
        The parsed (and profiled) EML module.
    eml_source_path
        Absolute path to the .eml source file. Copied verbatim into
        the bundle so any line-number reference in the spec resolves.
    out_root
        Directory to create. Will be wiped + recreated to keep the
        bundle reproducible.
    backend
        Optional shared backend instance — pass one if you want the
        gas numbers in the .sol and the .spec.json to come from a
        single in-process compile.
    machlib_root
        Where to look for proofs. Defaults to ``$MACHLIB_ROOT`` then
        to ``<repo>/../machlib/foundations/MachLib/Discovered``.
    with_prbmath
        Emit the ``<Contract>WithPRBMath.sol`` override that wires the
        parent's transcendental stubs to PRBMath SD59x18.
    with_foundry_tests
        Emit ``test/<Contract>Test.t.sol`` + ``foundry.toml``. Implies
        ``with_prbmath`` (the tests deploy the override contract).
    """
    backend = backend or SolidityBackend()
    out_root = out_root.resolve()
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    sol_src = backend.compile(mod)
    spec = build_spec(mod, backend=backend)
    used_builtins = set(backend._used_builtins)
    proofs_dir = out_root / "proofs"
    proofs_dir.mkdir()
    proof_results = _collect_proofs(
        spec=spec, mod=mod, proofs_dir=proofs_dir, machlib_root=machlib_root,
    )

    written: list[Path] = []
    written.append(_write(out_root / "contract.sol", sol_src))
    written.append(_write(
        out_root / "spec.json",
        json.dumps(spec, indent=2, sort_keys=True),
    ))
    written.append(_write_bytes(
        out_root / "source.eml",
        eml_source_path.read_bytes(),
    ))
    written.extend(proof_results)

    # PRBMath + TrigSD59x18 overrides (forces on when foundry tests
    # are requested).
    override_name: str | None = None
    if with_prbmath or with_foundry_tests:
        from software.backends.solidity_prbmath import emit_prbmath_override
        from software.backends.solidity_trig import emit_trig_library
        # TrigSD59x18 ships first so the override import resolves.
        trig = emit_trig_library(used_builtins)
        if trig is not None:
            written.append(_write(
                out_root / f"{trig.library_name}.sol",
                trig.source,
            ))
        override = emit_prbmath_override(
            parent_name=spec["contract"],
            used_builtins=used_builtins,
            parent_path="./contract.sol",
        )
        override_name = override.contract_name
        written.append(_write(
            out_root / f"{override.contract_name}.sol",
            override.source,
        ))

    # Foundry test scaffold + foundry.toml.
    if with_foundry_tests and override_name is not None:
        from software.backends.solidity_foundry import emit_foundry_scaffold
        scaffold = emit_foundry_scaffold(
            spec=spec,
            override_contract=override_name,
            override_path=f"../{override_name}.sol",
        )
        test_dir = out_root / "test"
        test_dir.mkdir(exist_ok=True)
        written.append(_write(
            test_dir / f"{scaffold.test_contract_name}.t.sol",
            scaffold.test_source,
        ))
        written.append(_write(
            out_root / "foundry.toml",
            scaffold.foundry_toml,
        ))

    written.append(_write(
        out_root / "AUDITOR.md",
        _auditor_md(spec=spec, proof_files=proof_results),
    ))

    manifest = _build_manifest(
        out_root=out_root,
        files=written,
        spec=spec,
        eml_source_path=eml_source_path,
    )
    written.append(_write(
        out_root / "manifest.json",
        json.dumps(manifest, indent=2, sort_keys=True),
    ))
    return AuditBundle(
        root=out_root, files=tuple(written), manifest=manifest,
    )


# ── Manifest ────────────────────────────────────────────────────────


def _build_manifest(
    *,
    out_root: Path,
    files: Iterable[Path],
    spec: dict,
    eml_source_path: Path,
) -> dict:
    artifacts = []
    for p in sorted(files):
        rel = p.relative_to(out_root).as_posix()
        artifacts.append({
            "path": rel,
            "sha256": _sha256(p),
            "size": p.stat().st_size,
        })
    return {
        "audit_bundle_version": AUDIT_BUNDLE_VERSION,
        "spec_version": SPEC_VERSION,
        "compiler": {
            "name": "monogate-forge",
            "version": _compiler_version(),
            "backend": "solidity",
        },
        "module": spec.get("module", ""),
        "contract": spec.get("contract", ""),
        "source": {
            "path": eml_source_path.name,
            "sha256": _sha256(eml_source_path),
        },
        "artifacts": artifacts,
    }


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


# ── Lean proof resolution ───────────────────────────────────────────


def _collect_proofs(
    *,
    spec: dict,
    mod: EMLModule,
    proofs_dir: Path,
    machlib_root: Path | None,
) -> list[Path]:
    """For each @verify(lean,...) function, copy its theorem file out
    of MachLib into the bundle's proofs/ subfolder. When the theorem
    can't be located, write a `<theorem>.MISSING.txt` stub so the
    bundle still has a placeholder + audit trail."""
    written: list[Path] = []
    seen_files: set[Path] = set()
    root = _resolve_machlib_root(machlib_root, mod=mod)
    for fn in spec.get("functions", []):
        if not fn.get("verified"):
            continue
        theorem = fn.get("verification", {}).get("theorem", fn["name"])
        candidate = _find_theorem_file(
            theorem=theorem, mod_name=spec.get("module", ""), root=root,
        )
        if candidate is None:
            stub_path = proofs_dir / f"{theorem}.MISSING.txt"
            if stub_path not in seen_files:
                _write(stub_path, _missing_proof_note(theorem, root))
                seen_files.add(stub_path)
                written.append(stub_path)
            continue
        dest = proofs_dir / candidate.name
        if dest in seen_files:
            continue
        _write_bytes(dest, candidate.read_bytes())
        seen_files.add(dest)
        written.append(dest)
    return written


def _resolve_machlib_root(
    explicit: Path | None, *, mod: EMLModule,
) -> Path | None:
    if explicit is not None:
        return explicit
    env = os.environ.get("MACHLIB_ROOT", "").strip()
    if env:
        return Path(env)
    # Sibling-repo convention: ../machlib/foundations/MachLib/Discovered
    here = Path(__file__).resolve()
    candidate = (
        here.parent.parent.parent.parent
        / "machlib" / "foundations" / "MachLib" / "Discovered"
    )
    return candidate if candidate.is_dir() else None


def _find_theorem_file(
    *, theorem: str, mod_name: str, root: Path | None,
) -> Path | None:
    """Best-effort resolution: look for a Lean file whose stem matches
    the theorem name, then the EML module name, in MachLib/Discovered."""
    if root is None or not root.is_dir():
        return None
    by_theorem = root / f"{theorem}.lean"
    if by_theorem.is_file():
        return by_theorem
    if mod_name:
        by_module = root / f"{mod_name}.lean"
        if by_module.is_file():
            return by_module
    # Fall back to a theorem-name search inside each .lean file --
    # MachLib pins theorems to their declaring file's stem, so this
    # is a last-resort catch-all for renames.
    needle = f"theorem {theorem}".encode("utf-8")
    for p in root.glob("*.lean"):
        try:
            if needle in p.read_bytes():
                return p
        except OSError:
            continue
    return None


def _missing_proof_note(theorem: str, root: Path | None) -> str:
    where = str(root) if root else "<MachLib root not configured>"
    return (
        f"# Missing proof: {theorem}\n\n"
        f"The Solidity contract claims `@verify(lean, theorem = "
        f"\"{theorem}\")` but the theorem file could not be located.\n\n"
        f"Search root used: {where}\n\n"
        f"Fix paths:\n"
        f"  - point `--machlib-root <PATH>` at a checkout of MachLib\n"
        f"  - or set the `MACHLIB_ROOT` environment variable\n"
        f"  - or land the proof at "
        f"`<MACHLIB_ROOT>/{theorem}.lean`\n"
    )


# ── AUDITOR.md ──────────────────────────────────────────────────────


def _auditor_md(*, spec: dict, proof_files: list[Path]) -> str:
    contract = spec.get("contract", "<contract>")
    module = spec.get("module", "<module>")
    fn_lines: list[str] = []
    for fn in spec.get("functions", []):
        marker = "external" if fn.get("verified") else "internal"
        gas = fn.get("gas_estimate", "?")
        suffix = ""
        if fn.get("verified"):
            theorem = fn.get("verification", {}).get("theorem", fn["name"])
            suffix = f" — proved by `proofs/{theorem}.lean`"
        fn_lines.append(
            f"- `{fn['solidity_name']}` ({marker}, ~{gas} gas){suffix}"
        )
    proof_section = "\n".join(
        f"- `proofs/{p.name}`" for p in proof_files
    ) or "- _(no @verify-annotated functions in this module)_"
    return _AUDITOR_TEMPLATE.format(
        contract=contract,
        module=module,
        fn_list="\n".join(fn_lines) or "- _(no functions)_",
        proof_list=proof_section,
    )


_AUDITOR_TEMPLATE = """# Audit bundle: {contract}

This folder is a self-contained record of the Solidity contract
compiled from EML module `{module}`.

## Files

- `contract.sol` — the parent Solidity. NatSpec headers carry
  the per-function gas estimate and Pfaffian profile. Transcendental
  helpers (`_exp`, `_ln`, etc.) are virtual stubs that revert.
- `{contract}WithPRBMath.sol` — deployable child contract that
  overrides each transcendental via PRBMath SD59x18 (exp/ln/sqrt/abs/
  pow) and the bundled `TrigSD59x18` library (sin/cos/tan/asin/acos/
  atan + hyperbolics). This is the contract you ship.
- `TrigSD59x18.sol` — circular-trig + hyperbolic library, only
  emitted when the parent uses any of the 9 trig builtins. Taylor
  series for circular trig; PRBMath `exp` compositions for
  hyperbolics. ~14-digit precision; ~30-80k gas per call.
- `spec.json` — structured formal spec. One entry per function with
  preconditions (Solidity-rendered + EML source line), postconditions,
  Lean theorem references, gas estimate.
- `source.eml` — the EML source, included verbatim. All
  `eml_source_line` references in `spec.json` resolve here.
- `proofs/*.lean` — Lean theorem files copied out of MachLib for
  every `@verify(lean, theorem = X)` annotation. Missing theorems
  show up as `<theorem>.MISSING.txt` stubs.
- `test/{contract}Test.t.sol` + `foundry.toml` — Foundry scaffold.
  Verified functions get `testFuzz_*` tests that `vm.assume()` every
  precondition, call the function, and `assertTrue` every
  postcondition. Internal helpers get gas-snapshot tests.
- `manifest.json` — `sha256` + byte size of every artifact. Pin
  the manifest's hash in your audit report; verify it locally with
  `sha256sum -c` on the listed paths.

## Functions

{fn_list}

## Proofs

{proof_list}

## How to verify the bundle

1. Re-run `forge --target solidity --audit-bundle` against
   `source.eml` and confirm the new bundle is byte-identical
   (compare `manifest.json` hashes).
2. For each function in `spec.json` with `verified: true`, open
   `proofs/<theorem>.lean` and confirm the theorem statement matches
   the Solidity preconditions/postconditions.
3. Drop the bundle into a Foundry project, run
   `forge install foundry-rs/forge-std PaulRBerg/prb-math`, then
   `forge test` to exercise every fuzz test + gas snapshot.
4. Deploy `{contract}WithPRBMath.sol` (NOT the parent) — the parent
   contains revert stubs for transcendentals; the override wires
   them to PRBMath.
"""


# ── File-write helpers ──────────────────────────────────────────────


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _write_bytes(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path
