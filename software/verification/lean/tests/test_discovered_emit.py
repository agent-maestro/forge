"""Tests for the discovered_emit sidecar helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_source
from lang.profiler import Profiler
from software.verification.lean.discovered_emit import (
    discovered_dir,
    redact_source_path,
    resolve_machlib_root,
    write_discovered_lean,
)


# ── redact_source_path ────────────────────────────────────────────

def test_redact_rewrites_industries_path():
    inp = ("-- Source file:   industries/automotive/control/pid.eml\n"
           "import MachLib.EML\n"
           "theorem pid_well_typed : True := sorry\n")
    out = redact_source_path(inp, "pid")
    assert "industries" not in out
    assert "-- Source file:   <private>/pid.eml" in out
    assert "import MachLib.EML" in out  # body untouched
    assert "theorem pid_well_typed" in out


def test_redact_idempotent():
    inp = "-- Source file:   industries/x.eml\n"
    once = redact_source_path(inp, "x")
    twice = redact_source_path(once, "x")
    assert once == twice


def test_redact_preserves_trailing_newline():
    with_nl = "-- Source file:   industries/x.eml\nbody\n"
    without_nl = "-- Source file:   industries/x.eml\nbody"
    assert redact_source_path(with_nl, "x").endswith("\n")
    assert not redact_source_path(without_nl, "x").endswith("\n")


# ── resolve_machlib_root ──────────────────────────────────────────

def test_resolve_explicit_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("MACHLIB_ROOT", str(tmp_path / "env_root"))
    explicit = tmp_path / "explicit"
    assert resolve_machlib_root(explicit) == explicit


def test_resolve_falls_back_to_env(monkeypatch, tmp_path):
    env_root = tmp_path / "env_root"
    monkeypatch.setenv("MACHLIB_ROOT", str(env_root))
    assert resolve_machlib_root(None) == env_root


def test_resolve_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("MACHLIB_ROOT", raising=False)
    expected = Path.home() / "monogate" / "machlib"
    assert resolve_machlib_root(None) == expected


# ── write_discovered_lean ─────────────────────────────────────────

@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


def _make_machlib_root(base: Path) -> Path:
    """Create the minimum dir structure write_discovered_lean expects."""
    root = base / "machlib"
    (root / "foundations" / "MachLib" / "Discovered").mkdir(parents=True)
    return root


_VERIFY_SRC = '''module t;
@verify(lean, theorem = "f_nonneg")
fn f(x: Real) -> Real
    requires x >= 0.0
    ensures result >= 0.0
{
    x + 1.0
}'''


def test_write_no_verify_returns_none(profiler, tmp_path):
    src = "module t;\nfn f(x: Real) -> Real { x + 1.0 }"
    mod = parse_source(src, "<test>")
    profiler.profile_module(mod)
    machlib_root = _make_machlib_root(tmp_path)

    result = write_discovered_lean(
        mod, basename="f", machlib_root=machlib_root,
    )
    assert result is None
    assert list(discovered_dir(machlib_root).iterdir()) == []


def test_write_with_verify_creates_file(profiler, tmp_path):
    mod = parse_source(_VERIFY_SRC, "<test>")
    profiler.profile_module(mod)
    machlib_root = _make_machlib_root(tmp_path)

    result = write_discovered_lean(
        mod, basename="f", machlib_root=machlib_root,
    )
    assert result is not None
    assert result == discovered_dir(machlib_root) / "f.lean"
    assert result.exists()
    assert result.read_text(encoding="utf-8")  # non-empty


def test_write_redacts_source_path(profiler, tmp_path):
    mod = parse_source(_VERIFY_SRC, "<test>")
    profiler.profile_module(mod)
    machlib_root = _make_machlib_root(tmp_path)

    write_discovered_lean(
        mod, basename="my_kernel", machlib_root=machlib_root,
    )
    out = (discovered_dir(machlib_root) / "my_kernel.lean").read_text(
        encoding="utf-8",
    )
    if "-- Source file:" in out:
        assert "-- Source file:   <private>/my_kernel.eml" in out
        for line in out.splitlines():
            if line.startswith("-- Source file:"):
                assert "industries" not in line
                assert "<private>" in line


def test_write_dry_run_does_not_touch_disk(profiler, tmp_path):
    mod = parse_source(_VERIFY_SRC, "<test>")
    profiler.profile_module(mod)
    machlib_root = _make_machlib_root(tmp_path)

    result = write_discovered_lean(
        mod, basename="f", machlib_root=machlib_root, dry_run=True,
    )
    assert result == discovered_dir(machlib_root) / "f.lean"
    assert not result.exists()


def test_write_raises_when_root_missing(profiler, tmp_path):
    mod = parse_source(_VERIFY_SRC, "<test>")
    profiler.profile_module(mod)
    bogus_root = tmp_path / "does" / "not" / "exist"

    with pytest.raises(FileNotFoundError):
        write_discovered_lean(
            mod, basename="f", machlib_root=bogus_root,
        )


def test_write_creates_discovered_subdir_if_missing(profiler, tmp_path):
    """Discovered/ subdir auto-created; only the root must pre-exist."""
    mod = parse_source(_VERIFY_SRC, "<test>")
    profiler.profile_module(mod)
    root = tmp_path / "machlib"
    root.mkdir()  # only the root, no foundations/MachLib/Discovered/

    result = write_discovered_lean(
        mod, basename="f", machlib_root=root,
    )
    assert result is not None
    assert result.exists()
    assert (root / "foundations" / "MachLib" / "Discovered").is_dir()
