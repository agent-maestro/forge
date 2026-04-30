"""Tests for the C++17 backend (`software.backends.cpp_backend`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser import parse_file, parse_source
from lang.profiler import Profiler
from software.backends.cpp_backend import CppBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"
AUTOPILOT = REPO_ROOT / "industries" / "aerospace" / "flight_control" / "autopilot.eml"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> CppBackend:
    return CppBackend()


def _compile(path: Path, profiler: Profiler, backend: CppBackend) -> str:
    mod = parse_file(path)
    profiler.profile_module(mod)
    return backend.compile(mod)


# ── Smoke: every demo compiles ─────────────────────────────────


@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_demo_compiles_to_cpp(
    filename: str, profiler: Profiler, backend: CppBackend,
) -> None:
    out = _compile(EXAMPLES_DIR / filename, profiler, backend)
    assert "#pragma once" in out
    assert "#include <cmath>" in out
    assert "namespace forge::" in out
    # `[[nodiscard]]` is on every non-extern function.
    assert "[[nodiscard]]" in out


# ── Autopilot: namespacing + Doxygen contracts ─────────────────


def test_autopilot_namespace_and_doxygen(
    profiler: Profiler, backend: CppBackend,
) -> None:
    out = _compile(AUTOPILOT, profiler, backend)

    assert "namespace forge::autopilot" in out
    assert "}  // namespace forge::autopilot" in out

    # Doxygen contracts derived from requires/ensures.
    assert "@pre" in out
    assert "@post" in out
    assert "std::abs(pitch_setpoint)" in out
    assert "std::abs(result)" in out  # `result` kept verbatim in @post

    # @verify cross-link surfaces.
    assert "@verify lean theorem=autopilot_command_within_limits" in out

    # Profile metadata surfaces in the Doxygen header.
    assert "@profile chain_order" in out


# ── constexpr eligibility (C++17 cmath restriction) ────────────


def test_pure_arithmetic_is_constexpr() -> None:
    src = "fn quad(x: Real, a: Real, b: Real, c: Real) -> Real { a*x*x + b*x + c }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = CppBackend().compile(mod)
    # No <cmath> calls -> safe to mark constexpr + noexcept under C++17.
    assert "constexpr double quad" in out
    assert "noexcept" in out


def test_function_with_cos_is_not_constexpr() -> None:
    src = "fn g(x: Real) -> Real { cos(x) }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = CppBackend().compile(mod)
    # `std::cos` isn't constexpr until C++26 — backend stays
    # conservative and omits the qualifier.
    assert "constexpr double g" not in out
    assert "[[nodiscard]] double g(double x)" in out


# ── Builtin mapping ────────────────────────────────────────────


def test_clamp_lowers_to_std_clamp() -> None:
    src = "fn cl(x: Real, lo: Real, hi: Real) -> Real { clamp(x, lo, hi) }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = CppBackend().compile(mod)
    assert "std::clamp(x, lo, hi)" in out


def test_eml_inlines_to_exp_minus_log() -> None:
    src = "fn e(x: Real, y: Real) -> Real { eml(x, y) }\n"
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = CppBackend().compile(mod)
    assert "(std::exp(x) - std::log(y))" in out


# ── Constants ─────────────────────────────────────────────────


def test_constants_are_constexpr(
    profiler: Profiler, backend: CppBackend,
) -> None:
    out = _compile(AUTOPILOT, profiler, backend)
    assert "constexpr double Kp" in out
    assert "constexpr double ELEVATOR_MAX" in out


# ── Extern declarations ───────────────────────────────────────


def test_extern_emits_extern_c() -> None:
    src = 'extern fn libc_fn(x: Real) -> Real;\n'
    mod = parse_source(src)
    Profiler().profile_module(mod)
    out = CppBackend().compile(mod)
    assert 'extern "C" double libc_fn' in out
