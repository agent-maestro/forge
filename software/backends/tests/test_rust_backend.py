"""Tests for the Rust backend (`software.backends.rust_backend`)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

from lang.parser import parse_file
from lang.profiler import Profiler
from software.backends.rust_backend import RustBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES_DIR = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"
RUNTIME_RUST_DIR = REPO_ROOT / "software" / "runtime" / "rust"


@pytest.fixture(scope="module")
def profiler() -> Profiler:
    return Profiler()


@pytest.fixture(scope="module")
def backend() -> RustBackend:
    return RustBackend()


def _profile_and_compile(filename: str, profiler: Profiler,
                         backend: RustBackend) -> str:
    mod = parse_file(EXAMPLES_DIR / filename)
    profiler.profile_module(mod)
    return backend.compile(mod)


# ── All demo files compile to Rust without raising ──────────────────


@pytest.mark.parametrize(
    "filename",
    sorted(p.name for p in EXAMPLES_DIR.glob("*.eml")),
)
def test_demo_compiles_to_rust(filename: str, profiler: Profiler,
                               backend: RustBackend) -> None:
    out = _profile_and_compile(filename, profiler, backend)
    assert "use monogate_sys::*;" in out
    assert "pub fn " in out


# ── Specific structural expectations ────────────────────────────────


def test_hello_emits_pub_fn(profiler: Profiler, backend: RustBackend):
    out = _profile_and_compile("hello.eml", profiler, backend)
    assert "pub fn answer() -> f64" in out
    # Tail expression (no semicolon, no `return`)
    assert out.rstrip().endswith("}")


def test_pid_basic_emits_pub_const(profiler: Profiler, backend: RustBackend):
    out = _profile_and_compile("pid_basic.eml", profiler, backend)
    assert "pub const Kp: f64 = 0.5;" in out


def test_arrhenius_dispatches_to_mg_exp(profiler: Profiler,
                                        backend: RustBackend):
    out = _profile_and_compile("arrhenius.eml", profiler, backend)
    assert "mg_exp(" in out
    # Unary minus on Ea
    assert "(-Ea)" in out


def test_motor_foc_emits_struct_and_camelcase_typename(
    profiler: Profiler, backend: RustBackend,
):
    out = _profile_and_compile("motor_foc.eml", profiler, backend)
    assert "pub struct ParkResult" in out
    assert "ParkResult { e0:" in out
    assert "pub fn park(" in out
    assert " -> ParkResult" in out


def test_orbit_emits_let_mut_and_while(profiler: Profiler,
                                       backend: RustBackend):
    out = _profile_and_compile("orbit.eml", profiler, backend)
    assert "let mut E: f64 = M;" in out
    assert "let mut i: u8 = 0;" in out
    assert "while " in out
    # Bare assignment to mut binding
    assert "E = " in out


def test_motor_control_emits_six_functions(profiler: Profiler,
                                           backend: RustBackend):
    out = _profile_and_compile("motor_control.eml", profiler, backend)
    for fn_name in ("pid_output", "damped_response", "motor_torque",
                    "unstable_gain", "realtime_control", "safe_pid"):
        assert f"pub fn {fn_name}(" in out


def test_doc_comment_includes_chain_order(profiler: Profiler,
                                          backend: RustBackend):
    out = _profile_and_compile("motor_control.eml", profiler, backend)
    # damped_response should be tagged with chain_order 3
    assert "Chain order: 3" in out


def test_complex_body_emits_doc_with_complex_marker(
    profiler: Profiler, backend: RustBackend,
):
    out = _profile_and_compile("orbit.eml", profiler, backend)
    assert "COMPLEX BODY" in out
    # The function still emits a body
    assert "pub fn kepler_solve" in out


def test_user_function_call_passes_through(profiler: Profiler,
                                           backend: RustBackend):
    out = _profile_and_compile("motor_control.eml", profiler, backend)
    # safe_pid calls pid_output
    assert "pid_output(error" in out


def test_unsupported_node_kind_raises():
    from lang.parser.ast_nodes import ASTNode, NodeKind
    from software.backends.rust_backend import CompileError, RustBackend
    bad = ASTNode(kind=NodeKind.BLOCK)  # not an expression
    with pytest.raises(CompileError):
        RustBackend()._emit_expr(bad)


# ── Optional integration test: cargo check if available ────────────


def _cargo_available() -> bool:
    return shutil.which("cargo") is not None


@pytest.mark.skipif(not _cargo_available(), reason="cargo not on PATH")
def test_generated_rust_compiles_against_runtime_crate(
    profiler: Profiler, backend: RustBackend,
) -> None:
    """When cargo is available, generate Rust for `pid_basic.eml`,
    drop it into a tiny test crate that depends on monogate-sys via
    a path dependency, and run `cargo check`."""
    # Compile pid_basic.eml -- the simplest non-trivial demo.
    rust_source = _profile_and_compile("pid_basic.eml", profiler, backend)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Write a tiny test crate
        cargo_toml = textwrap.dedent(f'''
            [package]
            name = "forge_test"
            version = "0.0.1"
            edition = "2021"

            [lib]
            name = "forge_test"
            path = "src/lib.rs"

            [dependencies]
            monogate-sys = {{ path = "{RUNTIME_RUST_DIR.as_posix()}" }}
        ''').lstrip()
        (tmp_path / "Cargo.toml").write_text(cargo_toml, encoding="utf-8")
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "lib.rs").write_text(rust_source, encoding="utf-8")

        result = subprocess.run(
            ["cargo", "check", "--quiet"],
            cwd=str(tmp_path),
            capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, (
            f"cargo check rejected generated Rust:\n"
            f"--- STDERR ---\n{result.stderr}\n"
            f"--- SOURCE ---\n{rust_source[:2000]}"
        )
