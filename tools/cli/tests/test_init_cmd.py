"""Tests for `eml-compile init`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.cli.init_cmd import init_project


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_init_creates_canonical_layout(tmp_path: Path):
    target = tmp_path / "myapp"
    rc = init_project(target, name="myapp")
    assert rc == 0
    assert (target / "pyproject.toml").exists()
    assert (target / "main.eml").exists()
    assert (target / ".vscode" / "settings.json").exists()
    assert (target / ".gitignore").exists()


def test_init_pyproject_substitutes_name(tmp_path: Path):
    target = tmp_path / "acme"
    init_project(target, name="acme")
    py = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "acme"' in py


def test_init_main_eml_has_balanced_braces(tmp_path: Path):
    """The starter EML must parse cleanly via the live parser."""
    target = tmp_path / "starter"
    init_project(target, name="starter")
    src = (target / "main.eml").read_text(encoding="utf-8")
    # Single curly braces only -- no `{{` from a templating accident.
    assert "{{" not in src
    assert "}}" not in src
    # And the parser must accept it.
    from lang.parser.parser import parse_file
    mod = parse_file(str(target / "main.eml"))
    assert any(fn.name == "hello" for fn in mod.functions)


def test_init_skips_existing_files(tmp_path: Path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "main.eml").write_text("// pre-existing\n", encoding="utf-8")
    rc = init_project(target, name="existing")
    assert rc == 0
    # Skipped, not overwritten.
    assert (target / "main.eml").read_text(encoding="utf-8") == "// pre-existing\n"


def test_init_force_overwrites(tmp_path: Path):
    target = tmp_path / "force_test"
    target.mkdir()
    (target / "main.eml").write_text("// old\n", encoding="utf-8")
    init_project(target, name="force_test", force=True)
    assert (target / "main.eml").read_text(encoding="utf-8") != "// old\n"


def test_vscode_settings_is_valid_json(tmp_path: Path):
    target = tmp_path / "vsc"
    init_project(target, name="vsc")
    settings = (target / ".vscode" / "settings.json").read_text(encoding="utf-8")
    parsed = json.loads(settings)
    assert parsed["[eml]"]["editor.formatOnSave"] is True


def test_init_via_subcommand_dispatch(tmp_path: Path):
    """`eml-compile init <dir>` dispatches through main()."""
    target = tmp_path / "viacli"
    proc = subprocess.run(
        [sys.executable, "tools/cli/main.py", "init", str(target),
         "--name", "viacli"],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert (target / "main.eml").exists()
