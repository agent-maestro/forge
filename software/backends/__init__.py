"""Software code-generation backends.

Each backend takes a list of (parsed + profiled + optimized)
EMLFunction objects and returns source code in its target
language. All backends share the same upstream pipeline so
their outputs are semantically equivalent within tolerance.

Available backends (SCAFFOLD -- only headers + classes today):
    c_backend       -> C99 via libmonogate.h
    rust_backend    -> Rust via monogate-sys
    python_backend  -> Python/NumPy (delegates to eml-cost Tool 5)
    llvm_backend    -> LLVM IR
    wasm_backend    -> WebAssembly
"""
