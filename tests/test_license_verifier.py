"""Tests for `tools.license.verifier` — license-loading discipline.

The verifier intentionally distinguishes three failure modes:

- **No license** → `load_license()` returns `None` (Free tier).
- **Expired license** → `load_license()` returns `None` AND prints a
  one-line stderr warning. Soft downgrade so routine subscription
  expiry doesn't break the CLI for paying users (or test suites that
  carry an expired token).
- **Tampered / malformed license** → `load_license()` raises
  `LicenseError`. Loud failure because that is misuse, not lapsed
  billing.

These tests pin all three paths and the subtype hierarchy.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make `tools.*` importable from the forge tree.
_FORGE_ROOT = Path(__file__).resolve().parent.parent
if str(_FORGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_FORGE_ROOT))

from tools.license import (  # noqa: E402
    License,
    LicenseError,
    LicenseExpiredError,
    load_license,
)
from tools.license.verifier import verify_token  # noqa: E402


# Known expired token (the one shipped at ~/.monogate/license during
# the 2026-06-10/11 audit). exp=2026-06-02, tier=pro.
EXPIRED_PRO_TOKEN = (
    "v1.eyJlbWFpbCI6ImFsbWFndWVyMTk4NkBnbWFpbC5jb20iLCJleHAiOiIyMDI2"
    "LTA2LTAyIiwiaWF0IjoiMjAyNi0wNS0wMiIsIm5vbmNlIjoiOGNiYTgyYWEyOTJl"
    "YmYxMyIsInRpZXIiOiJwcm8ifQ.Qa_yQOwXZi2Ynd4Wmj-f3jo7ngO3AB_gPTwz"
    "Zf3O2TxOhL9mNqZNJopns21aAavYTrhEgPIJp62vxXj4v59EAA"
)


@pytest.fixture
def isolate_license(monkeypatch, tmp_path):
    """Strip both the env-var and the config-file license sources for
    a clean per-test slate."""
    monkeypatch.delenv("MONOGATE_LICENSE", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


def test_no_license_returns_none(isolate_license):
    """Missing license → silent free-tier fallback."""
    assert load_license() is None


def test_expired_license_subtype():
    """`LicenseExpiredError` IS a `LicenseError` (single-except clause
    in callers that want loud-fail-on-anything should still catch it)."""
    assert issubclass(LicenseExpiredError, LicenseError)


def test_expired_license_via_verify_token_raises_expired():
    """`verify_token` raises the *expired* subclass on past-`exp`
    tokens — not the generic LicenseError. This is what `load_license`
    discriminates on."""
    with pytest.raises(LicenseExpiredError):
        verify_token(EXPIRED_PRO_TOKEN)


def test_expired_license_silently_downgrades(isolate_license, capsys):
    """`load_license` with an expired token returns None (Free tier)
    AND emits a one-line stderr warning."""
    cfg_dir = isolate_license / ".monogate"
    cfg_dir.mkdir()
    (cfg_dir / "license").write_text(EXPIRED_PRO_TOKEN)
    result = load_license()
    assert result is None
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert "expired" in captured.err.lower()
    assert "free tier" in captured.err.lower()


def test_malformed_token_still_raises_loud(isolate_license, capsys):
    """Garbage in the license slot still fails loudly — soft downgrade
    is for *expired*, not for *broken*."""
    cfg_dir = isolate_license / ".monogate"
    cfg_dir.mkdir()
    (cfg_dir / "license").write_text("not-a-real-token-at-all")
    with pytest.raises(LicenseError):
        load_license()


def test_env_var_takes_precedence(isolate_license, monkeypatch):
    """`MONOGATE_LICENSE` env var beats the config file. Setting it to
    an expired token reproduces the same silent-downgrade path."""
    monkeypatch.setenv("MONOGATE_LICENSE", EXPIRED_PRO_TOKEN)
    assert load_license() is None


def test_license_dataclass_round_trip():
    """Sanity check on the License dataclass — non-expired, well-formed
    payload yields a usable License."""
    lic = License(
        email="test@example.com",
        tier="pro",
        issued_at="2026-01-01",
        expires_at="2099-01-01",
    )
    assert not lic.is_expired()
    assert lic.tier == "pro"
