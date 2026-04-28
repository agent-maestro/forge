"""WebAssembly backend -- compiles via LLVM IR -> wasm.

Used by the 1op.io playground demos. Reference:
lang/spec/EML_LANG_DESIGN.md (Phase 2 cross-cutting).
SCAFFOLD.
"""

from __future__ import annotations

from lang.parser.ast_nodes import EMLFunction


class WASMBackend:
    """Compile an EMLFunction list to WebAssembly bytecode."""

    name = "wasm"

    def compile(self, program: list[EMLFunction]) -> bytes:
        # Real impl lowers to LLVMBackend output, then runs llc -march=wasm32.
        return b""
