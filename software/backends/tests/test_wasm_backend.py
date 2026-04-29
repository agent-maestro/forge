"""Tests for the WASM backend.

llc / clang are not present in this environment, so we verify that
`compile_full()` reports `toolchain='none'` and still returns valid
LLVM IR with the wasm32 triple. When the toolchain ships, the same
test machinery runs the bytecode-emit path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler
from software.backends.wasm_backend import WASMBackend


REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "lang" / "spec" / "grammar" / "examples"


@pytest.mark.parametrize("demo", [
    "sigmoid.eml", "arrhenius.eml", "hello.eml", "orbit.eml",
])
def test_wasm_compile_returns_ir_when_no_toolchain(demo):
    mod = parse_file(str(EXAMPLES / demo))
    Profiler().profile_module(mod)
    result = WASMBackend().compile_full(mod)
    assert result.toolchain in ("llc", "clang", "none")
    assert "wasm32" in result.ir
    if result.toolchain == "none":
        assert result.wasm == b""
    else:
        assert result.wasm.startswith(b"\x00asm")  # wasm magic bytes


def test_wasm_compile_short_form_smoke():
    mod = parse_file(str(EXAMPLES / "sigmoid.eml"))
    Profiler().profile_module(mod)
    out = WASMBackend().compile(mod)
    assert isinstance(out, bytes)
