"""Shared pytest fixtures for monogate-forge tests."""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repo root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def example_files(repo_root: Path) -> list[Path]:
    """All .eml example files under lang/spec/grammar/examples/."""
    return sorted((repo_root / "lang" / "spec" / "grammar" / "examples")
                  .glob("*.eml"))


@pytest.fixture(scope="session")
def stdlib_files(repo_root: Path) -> list[Path]:
    """All .eml standard library files."""
    return sorted((repo_root / "lang" / "spec" / "stdlib").glob("*.eml"))
