# Backends — module reference

> Each backend is a single Python class with a `compile()`
> method. The interface differs slightly between software
> backends (take `EMLModule`) and hardware backends (also take
> an `AllocationPlan`).

---

## Software backends

All software backends live under `software/backends/` and
take a single `EMLModule` as input.

### `CBackend` — `software/backends/c_backend.py`

```python
from software.backends.c_backend import CBackend

src: str = CBackend(optimize=True).compile(mod)
```

Emits C99 linking `libmonogate.h`. Tuple-returning functions
synthesize a `_result_t` struct at the top of the file and
return that struct. Module-level constants emit as
`static const`.

### `RustBackend` — `software/backends/rust_backend.py`

```python
from software.backends.rust_backend import RustBackend

src: str = RustBackend(optimize=True).compile(mod)
```

Emits Rust source consuming the `monogate-sys` crate. Tuple
returns become Rust tuples; passes `cargo clippy -D warnings`
on the canonical demo set.

### `PythonBackend` — `software/backends/python_backend.py`

```python
from software.backends.python_backend import PythonBackend

src: str = PythonBackend(optimize=True).compile(mod)
```

Emits Python 3 using `math.*` only. The path is AST → SymPy
(via `lang/profiler/ast_to_sympy.py`) → Python (via
`eml_cost.transpile.eml_tree_to_python`, the published Tool 5).
Functions whose body lies outside the SymPy subset fall back
to a direct AST emitter.

### `LLVMBackend` — `software/backends/llvm_backend.py`

```python
from software.backends.llvm_backend import LLVMBackend

ir: str = LLVMBackend(optimize=True, target_triple=None).compile(mod)
```

Emits portable LLVM IR text. Each EML transcendental becomes
an external `declare`-d call into `libmonogate` (same naming
as the C backend); arithmetic and control flow lower to
native LLVM instructions. The body emitter uses
`alloca`/`load`/`store` for mutable bindings — `mem2reg`
cleans the slots up downstream.

### `WASMBackend` — `software/backends/wasm_backend.py`

```python
from software.backends.wasm_backend import WASMBackend

result = WASMBackend(optimize=True).compile_full(mod)
# result.toolchain in {"llc", "clang", "none"}
# result.wasm     -> bytes (empty if toolchain == "none")
# result.ir       -> str (always present; the LLVM IR fallback)
```

Lowers through `LLVMBackend` with the `wasm32-unknown-unknown`
triple, then defers to `llc -march=wasm32` (or `clang
--target=wasm32`) for bytecode. When neither is on PATH,
returns the IR text and reports `toolchain="none"`.

---

## Hardware backends

All hardware backends live under `hardware/hdl_gen/` and take
both an `EMLModule` and an `AllocationPlan` from the FPGA
allocator.

### `VerilogBackend` — `hardware/hdl_gen/verilog_backend.py`

```python
from hardware.allocator import FPGAAllocator
from hardware.hdl_gen.verilog_backend import VerilogBackend

plan = FPGAAllocator().allocate(mod, constraints={"target": "xilinx.artix7"})
src  = VerilogBackend(optimize=True).compile(mod, plan)
```

Emits one parametric Verilog module per `@target(fpga)`
function. Pipeline stages: one stage per EML node. Standard
valid/ready handshake. Transcendental ops become
instantiations of `eml_<op>` modules from
`hardware/modules/transcendental/` (CORDIC variant by default).

### `VHDLBackend` — `hardware/hdl_gen/vhdl_backend.py`

```python
from hardware.hdl_gen.vhdl_backend import VHDLBackend

src = VHDLBackend(optimize=True).compile(mod, plan)
```

VHDL-2008 port of `VerilogBackend`. Same combinational AST
translation; transcendentals become component instantiations
of `eml_<op>` from `hardware/modules/transcendental_vhd/`.

### `ChiselBackend` — `hardware/hdl_gen/chisel_backend.py`

```python
from hardware.hdl_gen.chisel_backend import ChiselBackend

src = ChiselBackend(optimize=True, package_name="monogate.gen").compile(mod, plan)
```

Emits Chisel 3 / Scala source. Each `@target(fpga)` function
becomes a `Module` whose `IO` carries clk/rst/validIn +
per-parameter `SInt(width.W)` ports. Transcendentals become
instances of `EmlExp`, `EmlLn`, `EmlSin`, etc.

---

## Verification backend

### `LeanBackend` — `software/verification/lean/LeanBackend.py`

```python
from software.verification.lean.LeanBackend import LeanBackend

src: str | None = LeanBackend(optimize=True).compile_module(mod)
```

Emits Lean 4 theorems for functions carrying `@verify(lean,
theorem=...)` annotations. Theorem statements come from the
function's `requires` + `ensures` clauses; the proof attempts
`eml_auto` from `monogate-lean/MonogateEML/Tactics.lean` and
falls back to `sorry` with a TODO comment if `eml_auto` doesn't
close.

`compile_module` returns `None` when the input module has no
`@verify(lean, ...)` blocks.

---

## Equivalence

`tools/equivalence/cross_target_check()` runs a chosen function
through any subset of `{python, c, rust, lean}`, compares the
output vectors, and returns an `EquivalenceReport`. Toolchain-
missing backends report `available=False` rather than failing
the run.
