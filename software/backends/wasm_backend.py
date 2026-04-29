"""WebAssembly backend.

Strategy: lower through `LLVMBackend` with the `wasm32-unknown-unknown`
target triple, then defer to `llc -march=wasm32` (or `clang --target=wasm32`)
to produce the actual wasm bytecode. When the LLVM toolchain isn't
available, `compile()` returns the IR text instead of bytecode and
records that fact on the result.

This is the path the 1op.io playground demos take. Reference:
lang/spec/EML_LANG_DESIGN.md (Phase 2 cross-cutting).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lang.parser.ast_nodes import EMLModule
from software.backends.llvm_backend import LLVMBackend


@dataclass(frozen=True)
class WASMResult:
    """Result of a WASM compile run.

    `wasm` is the wasm32 bytecode if `llc` was available; empty bytes
    otherwise. `ir` always carries the LLVM IR text so callers can fall
    back to that on a downstream toolchain.
    """
    wasm: bytes
    ir: str
    toolchain: str
    """One of: 'llc', 'clang', 'none'."""


class WASMBackend:
    """Compile an EMLModule to WebAssembly bytecode."""

    name = "wasm"

    def __init__(self, *, optimize: bool = True):
        self.optimize = optimize
        self._llvm = LLVMBackend(
            optimize=optimize, target_triple="wasm32-unknown-unknown",
        )

    # ── Public API ────────────────────────────────────────────

    def compile(self, mod: EMLModule) -> bytes:
        """Convenience wrapper -- returns just the bytecode (or empty
        bytes if no toolchain). Use `compile_full()` for the IR + toolchain
        info.
        """
        return self.compile_full(mod).wasm

    def compile_full(self, mod: EMLModule) -> WASMResult:
        ir = self._llvm.compile(mod)

        llc = shutil.which("llc")
        if llc:
            wasm = self._run_llc(ir, llc)
            return WASMResult(wasm=wasm, ir=ir, toolchain="llc")

        clang = shutil.which("clang")
        if clang:
            wasm = self._run_clang(ir, clang)
            return WASMResult(wasm=wasm, ir=ir, toolchain="clang")

        return WASMResult(wasm=b"", ir=ir, toolchain="none")

    # ── Toolchain runners ─────────────────────────────────────

    @staticmethod
    def _run_llc(ir: str, llc_path: str) -> bytes:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ll_file = td / "module.ll"
            ll_file.write_text(ir, encoding="utf-8")
            wasm_file = td / "module.wasm"
            subprocess.run(
                [llc_path, "-march=wasm32", "-filetype=obj",
                 "-o", str(wasm_file), str(ll_file)],
                check=True, capture_output=True,
            )
            return wasm_file.read_bytes()

    @staticmethod
    def _run_clang(ir: str, clang_path: str) -> bytes:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ll_file = td / "module.ll"
            ll_file.write_text(ir, encoding="utf-8")
            wasm_file = td / "module.wasm"
            subprocess.run(
                [clang_path, "--target=wasm32-unknown-unknown",
                 "-c", "-o", str(wasm_file), str(ll_file)],
                check=True, capture_output=True,
            )
            return wasm_file.read_bytes()
