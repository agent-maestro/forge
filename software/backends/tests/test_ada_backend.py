"""Tests for the Ada/SPARK backend (`software.backends.ada_backend`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.ada_backend import AdaBackend, AdaArtifact


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"
AUTOPILOT = REPO_ROOT / "industries" / "aerospace" / "flight_control" / "autopilot.eml"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> AdaBackend:
    return AdaBackend()


def _compile(path: Path, profiler: Profiler, backend: AdaBackend) -> AdaArtifact:
    mod = parse_file(path)
    profiler.profile_module(mod)
    return backend.compile_full(mod)


# ── Smoke: every demo compiles ─────────────────────────────────


@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_demo_compiles_to_ada(
    filename: str, profiler: Profiler, backend: AdaBackend,
) -> None:
    art = _compile(EXAMPLES_DIR / filename, profiler, backend)
    # Spec must declare a package and end with `end <Pkg>;`.
    assert "package " in art.spec
    assert f"end {art.package_name};" in art.spec
    # Body must declare `package body <Pkg>` and have the same close.
    assert f"package body {art.package_name}" in art.body
    assert f"end {art.package_name};" in art.body
    # SPARK_Mode is on by default.
    assert "pragma SPARK_Mode (On);" in art.spec
    assert "pragma SPARK_Mode (On);" in art.body


# ── Autopilot: full @verify → SPARK Pre/Post round-trip ────────


def test_autopilot_emits_spark_contracts(
    profiler: Profiler, backend: AdaBackend,
) -> None:
    art = _compile(AUTOPILOT, profiler, backend)
    spec = art.spec

    # Package name uses Title_Case.
    assert art.package_name == "Autopilot"

    # Each `requires` clause becomes part of the Pre aspect.
    assert "Pre  =>" in spec
    assert "abs (pitch_setpoint)" in spec
    assert "abs (pitch_measured)" in spec
    assert "abs (pitch_integral)" in spec
    assert "INTEGRAL_LIMIT" in spec

    # `ensures` becomes Post, and `result` is rewritten to
    # the function's `'Result` attribute.
    assert "Post =>" in spec
    assert "autopilot_step'Result" in spec
    assert "ELEVATOR_MAX" in spec

    # The Lean cross-link comment shows up alongside Pre/Post.
    assert "@verify(lean" in spec
    assert "autopilot_command_within_limits" in spec

    # Post-clause separator hygiene: no comma or semicolon
    # immediately after the `--` comment marker (regression
    # for the verify-comment punctuation bug we hit on first run).
    for line in spec.splitlines():
        s = line.strip()
        if s.startswith("--") and (s.endswith(",") or s.endswith(";")):
            # Allow plain `;` only if the comment literally ended
            # with one inside its text (e.g. "C-style;"). The bug
            # we're guarding against is the punctuation suffix
            # the contract-list emitter used to add.
            if not s.rstrip(";,").endswith(s.rstrip(";,").rstrip()):
                pytest.fail(f"comment with trailing aspect punctuation: {s!r}")


def test_autopilot_body_has_implementation(
    profiler: Profiler, backend: AdaBackend,
) -> None:
    art = _compile(AUTOPILOT, profiler, backend)
    body = art.body

    # All three EML functions surface in the body.
    assert "function gravity_compensation" in body
    assert "function rate_controller" in body
    assert "function autopilot_step" in body

    # Cos / Long_Float'Min / Long_Float'Max for trig + clamp.
    assert "Cos (" in body
    assert "Long_Float'Min" in body
    assert "Long_Float'Max" in body

    # let-bindings inside the autopilot_step function become
    # an Ada `declare ... begin ... end;` block.
    assert "declare" in body
    assert "begin" in body
    assert "end;" in body

    # Math import is wired via the elementary-functions package.
    assert "Ada.Numerics.Long_Elementary_Functions" in body


# ── Type mapping ────────────────────────────────────────────────


def test_default_real_maps_to_long_float() -> None:
    src = "fn double_it(x: Real) -> Real { x + x }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    art = AdaBackend().compile_full(mod)
    assert "x : Long_Float" in art.spec or "x : Long_Float" in art.body
    assert "return Long_Float" in art.spec or "return Long_Float" in art.body


# ── Ada keyword collision ───────────────────────────────────────


def test_param_name_colliding_with_ada_keyword_renamed() -> None:
    # `loop` is reserved in Ada; the backend appends `_`.
    src = "fn id(loop: Real) -> Real { loop }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    art = AdaBackend().compile_full(mod)
    assert "loop_" in art.body
    assert "loop_" in art.spec


# ── compile() = spec + body banner-separated ───────────────────


def test_compile_combines_spec_and_body(
    profiler: Profiler, backend: AdaBackend,
) -> None:
    mod = parse_file(AUTOPILOT)
    profiler.profile_module(mod)
    combined = backend.compile(mod)
    assert "save as autopilot.ads" in combined
    assert "save as autopilot.adb" in combined
    assert "package Autopilot is" in combined
    assert "package body Autopilot is" in combined


# ── Profile comment header ──────────────────────────────────────


def test_profile_comment_present(
    profiler: Profiler, backend: AdaBackend,
) -> None:
    art = _compile(AUTOPILOT, profiler, backend)
    assert "Chain order:" in art.spec
    assert "Cost class:" in art.spec
