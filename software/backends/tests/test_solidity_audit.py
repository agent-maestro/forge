"""Tests for the Solidity audit-bundle packager
(`software.backends.solidity_audit`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.profiler import Profiler
from software.backends.solidity_audit import (
    AUDIT_BUNDLE_VERSION,
    write_audit_bundle,
)
from software.backends.solidity_backend import SolidityBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


def _bundle(filename: str, tmp_path: Path,
            machlib_root: Path | None = None):
    eml_path = EXAMPLES_DIR / filename
    mod = parse_file(eml_path)
    Profiler().profile_module(mod)
    return write_audit_bundle(
        mod,
        eml_source_path=eml_path,
        out_root=tmp_path / f"{eml_path.stem}_audit",
        backend=SolidityBackend(),
        machlib_root=machlib_root,
    )


# ── Layout ───────────────────────────────────────────────────────────


def test_bundle_writes_canonical_files(tmp_path: Path):
    """Every audit bundle must include the deployable, the spec, the
    source, the AUDITOR.md guide, and the manifest."""
    bundle = _bundle("hello.eml", tmp_path)
    rels = {p.relative_to(bundle.root).as_posix() for p in bundle.files}
    assert "contract.sol" in rels
    assert "spec.json" in rels
    assert "source.eml" in rels
    assert "AUDITOR.md" in rels
    assert "manifest.json" in rels


def test_proofs_directory_exists_even_with_no_verified_functions(
    tmp_path: Path,
):
    """`hello.eml` has no @verify annotations. The proofs/ dir should
    still exist (so auditor tooling can rely on the layout) even
    though it'll be empty."""
    bundle = _bundle("hello.eml", tmp_path)
    assert (bundle.root / "proofs").is_dir()


# ── Manifest ─────────────────────────────────────────────────────────


def test_manifest_carries_version_and_compiler(tmp_path: Path):
    bundle = _bundle("hello.eml", tmp_path)
    m = bundle.manifest
    assert m["audit_bundle_version"] == AUDIT_BUNDLE_VERSION
    assert m["compiler"]["name"] == "monogate-forge"
    assert m["compiler"]["backend"] == "solidity"
    assert m["module"] == "hello"
    assert m["contract"] == "Hello"


def test_manifest_artifact_hashes_match_disk(tmp_path: Path):
    """For every artifact entry, the recorded sha256 must equal what
    you get by hashing the file on disk."""
    bundle = _bundle("hello.eml", tmp_path)
    for entry in bundle.manifest["artifacts"]:
        rel = entry["path"]
        if rel == "manifest.json":
            # Manifest itself is hashed *after* it's written, so its
            # entry doesn't appear in the artifacts list -- skip if
            # it ever does.
            continue
        actual = hashlib.sha256(
            (bundle.root / rel).read_bytes()
        ).hexdigest()
        assert entry["sha256"] == actual, (
            f"hash mismatch for {rel}"
        )
        assert entry["size"] == (bundle.root / rel).stat().st_size


def test_manifest_records_source_hash(tmp_path: Path):
    """The original .eml source file's hash must appear in the manifest
    so an auditor can prove the bundle was built from a specific input."""
    eml_path = EXAMPLES_DIR / "hello.eml"
    bundle = _bundle("hello.eml", tmp_path)
    expected = hashlib.sha256(eml_path.read_bytes()).hexdigest()
    assert bundle.manifest["source"]["sha256"] == expected


# ── Reproducibility ──────────────────────────────────────────────────


def test_two_bundle_builds_produce_identical_artifact_hashes(
    tmp_path: Path,
):
    """Building the same EML module twice must yield byte-identical
    artifacts (modulo manifest entries that wrap them, which are
    hashes themselves and so deterministic too)."""
    a = _bundle("motor_control.eml", tmp_path / "a")
    b = _bundle("motor_control.eml", tmp_path / "b")
    a_hashes = {e["path"]: e["sha256"] for e in a.manifest["artifacts"]}
    b_hashes = {e["path"]: e["sha256"] for e in b.manifest["artifacts"]}
    assert a_hashes == b_hashes


# ── Lean theorem resolution ──────────────────────────────────────────


def test_missing_proof_writes_stub_with_search_path(
    tmp_path: Path,
):
    """motor_control's `pid_bounded` theorem isn't currently in
    MachLib. The bundler should drop a `<theorem>.MISSING.txt` stub
    that explains where it should live, rather than silently
    skipping it."""
    bundle = _bundle(
        "motor_control.eml", tmp_path,
        # Force the search root to a known-empty dir so the test is
        # deterministic regardless of whether the dev has MachLib
        # checked out alongside.
        machlib_root=tmp_path / "empty_machlib_root",
    )
    proof_files = list((bundle.root / "proofs").iterdir())
    # At least one MISSING stub was emitted for the verified function.
    missing = [p for p in proof_files if p.name.endswith(".MISSING.txt")]
    assert missing, (
        f"expected a MISSING.txt for motor_control's verified fn, "
        f"got {[p.name for p in proof_files]}"
    )
    # The stub should mention the search root that was tried + how
    # to fix the path.
    body = missing[0].read_text(encoding="utf-8")
    assert "MACHLIB_ROOT" in body
    assert "--machlib-root" in body


def test_existing_proof_file_is_copied(tmp_path: Path):
    """When a `<theorem>.lean` file exists in the configured MachLib
    root, the bundler copies it into `proofs/` verbatim."""
    fake_machlib = tmp_path / "fake_machlib"
    fake_machlib.mkdir()
    proof_text = (
        "-- pid_bounded.lean (test fixture)\n"
        "theorem pid_bounded : True := trivial\n"
    )
    (fake_machlib / "pid_bounded.lean").write_text(
        proof_text, encoding="utf-8",
    )
    bundle = _bundle(
        "motor_control.eml", tmp_path / "out",
        machlib_root=fake_machlib,
    )
    copied = bundle.root / "proofs" / "pid_bounded.lean"
    assert copied.is_file()
    assert copied.read_text(encoding="utf-8") == proof_text


# ── AUDITOR.md content ──────────────────────────────────────────────


def test_auditor_md_lists_functions_and_proofs(tmp_path: Path):
    bundle = _bundle(
        "motor_control.eml", tmp_path,
        machlib_root=tmp_path / "empty",
    )
    md = (bundle.root / "AUDITOR.md").read_text(encoding="utf-8")
    assert "Audit bundle:" in md
    # Contract name comes from the manifest -- match whatever the
    # backend chose so the test isn't pinned to a particular casing.
    assert bundle.manifest["contract"] in md
    # Listed at least one function with a gas estimate.
    assert "gas)" in md
    # Verified function entry mentions its proof file.
    assert "proved by `proofs/" in md


# ── Source & contract files ──────────────────────────────────────────


def test_source_eml_is_byte_identical_to_input(tmp_path: Path):
    bundle = _bundle("hello.eml", tmp_path)
    original = (EXAMPLES_DIR / "hello.eml").read_bytes()
    copy = (bundle.root / "source.eml").read_bytes()
    assert original == copy


def test_contract_sol_is_valid_solidity_scaffold(tmp_path: Path):
    bundle = _bundle("hello.eml", tmp_path)
    sol = (bundle.root / "contract.sol").read_text(encoding="utf-8")
    assert "// SPDX-License-Identifier: MIT" in sol
    assert "pragma solidity" in sol


# ── spec.json is the same as `solidity_spec.build_spec` ─────────────


def test_spec_json_in_bundle_matches_build_spec(tmp_path: Path):
    """Round-trip the spec produced by build_spec against the on-disk
    copy in the audit bundle to make sure they don't drift."""
    from software.backends.solidity_spec import build_spec
    eml_path = EXAMPLES_DIR / "motor_control.eml"
    mod = parse_file(eml_path)
    Profiler().profile_module(mod)
    backend = SolidityBackend()
    expected = build_spec(mod, backend=backend)
    bundle = write_audit_bundle(
        mod,
        eml_source_path=eml_path,
        out_root=tmp_path / "audit",
        backend=backend,
        machlib_root=tmp_path / "empty",
    )
    on_disk = json.loads((bundle.root / "spec.json").read_text("utf-8"))
    assert on_disk == expected
