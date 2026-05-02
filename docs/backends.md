# Backends

Every `.eml` source file compiles to **32 different targets**. This page documents each one: CLI flag, file extension, what it's for, and tier.

```bash
# Compile to one target:
eml-compile my_file.eml --target rust -o my_file.rs

# Compile to all targets your tier permits:
eml-compile my_file.eml --target all -o build/

# See profile and exit (no codegen):
eml-compile my_file.eml --profile-only
```

Tier definitions:
- **Free** — works without a license. Install Forge, compile, ship. No questions.
- **Pro** — requires a Pro license token. Get one at [monogateforge.com/get-started](https://monogateforge.com/get-started).

A complete tier listing lives in `tools/license/verifier.py:FREE_TARGETS` and `:PRO_TARGETS`.

---

## Software (general-purpose)

### C99 — `--target c` (Free)
**Extension:** `.c`
**Use it for:** embedded firmware, microcontrollers, legacy systems, anywhere a C99 compiler runs.
**Notes:** emits standalone C99 with `<math.h>` calls; no allocation, no globals beyond constants. Float literals carry the `f` suffix when the body is f32-typed.

### C++17 — `--target cpp` (Free)
**Extension:** `.cpp`
**Use it for:** game engines, native plugins, performance-critical code that wants templates and `inline`.
**Notes:** uses `inline` everywhere, namespace = module name. Tuple returns lower to `std::tuple` or aggregate structs.

### Rust — `--target rust` (Free)
**Extension:** `.rs`
**Use it for:** systems programming, WebAssembly via `wasm-bindgen`, embedded with `no_std` (the output uses no allocation).
**Notes:** every function gets `#[inline(always)]`; `requires` becomes `debug_assert!`; Forge respects Rust's strict-aliasing and orphan rules.

### Python 3 — `--target python` (Free)
**Extension:** `.py`
**Use it for:** notebooks, ML pipelines, reference implementations, ground-truth oracles in equivalence testing.
**Notes:** uses `math.exp`, `math.cos`, etc. No NumPy dependency for scalar bodies. Type hints are emitted.

### Go — `--target go` (Free)
**Extension:** `.go`
**Use it for:** backend services, CLI tools, anything in the Go ecosystem.
**Notes:** package = module name; `math.Exp`, `math.Cos` etc.; integer types map to `int64`.

### Java — `--target java` (Free)
**Extension:** `.java`
**Use it for:** Android (with the Android math classes), JVM services, enterprise integrations.
**Notes:** wraps functions in a `final class <Module>` with `public static` methods. `Math.exp`, `Math.cos`. Tuple returns use generated record classes.

### Kotlin — `--target kotlin` (Free)
**Extension:** `.kt`
**Use it for:** modern Android, server-side Kotlin, multiplatform code.
**Notes:** uses top-level functions (`object` only when needed). `kotlin.math.exp`, `kotlin.math.cos`. Idiomatic null-safety throughout.

### MATLAB — `--target matlab` (Free)
**Extension:** `.m`
**Use it for:** Simulink import, MATLAB-resident research code, vendor toolchains that consume `.m`.
**Notes:** one function per file when MATLAB requires it; matrix-friendly operators where applicable.

### C# — `--target csharp` (Pro)
**Extension:** `.cs`
**Use it for:** Unity, .NET services, Xamarin / MAUI, Windows desktop.
**Notes:** wraps in a `static class`; uses `System.Math` for transcendentals; `[MethodImpl(MethodImplOptions.AggressiveInlining)]`.

### Swift — `--target swift` (Pro)
**Extension:** `.swift`
**Use it for:** iOS / macOS / watchOS / tvOS, server-side Swift via SwiftNIO.
**Notes:** `import Foundation`; top-level `@inline(__always) public func`; unlabeled parameters (`_ paramName: Type`) so call sites match the EML convention; `precondition()` for `requires`.

### JavaScript — `--target javascript` (Pro)
**Extension:** `.js`
**Use it for:** browser frontends, Node.js, any JS runtime.
**Notes:** ES module form (`export function …`); `Math.exp`, `Math.cos`; emits a JSDoc block with the chain-order profile.

---

## Compiler IRs

### LLVM IR — `--target llvm` (Pro)
**Extension:** `.ll`
**Use it for:** custom toolchains, hand-tuned codegen, embedding in your own LLVM-based compiler.
**Notes:** SSA-form, function-level attributes (`alwaysinline`), uses `llvm.exp.f64` etc. intrinsics where possible.

### WebAssembly — `--target wasm` (Pro)
**Extension:** `.wasm.ll` (LLVM IR targeting wasm), or compile that with `llc` to a `.wasm` binary.
**Use it for:** sandboxed numerical kernels in browsers, edge-runtime compute.
**Notes:** generates LLVM IR with the wasm32 target triple; `f32` is the default precision.

---

## GPU shaders

All shader backends emit **function libraries** (no entry-point markers, no `[[kernel]]` / `[shader(…)]` / `void main`). You bring them into a vertex/fragment/compute shader from your engine.

### HLSL (DirectX) — `--target hlsl` (Pro)
**Extension:** `.hlsl`
**Use it for:** DirectX 12, Unity HDRP/URP HLSL, Unreal HLSL custom nodes.
**Notes:** float32 only (HLSL's `double` is rare and slow); validated against `dxc -T lib_6_3`. Geometry-shader topology keywords (`point`, `line`, `triangle`) are reserved.

### GLSL (desktop) — `--target glsl` (Pro)
**Extension:** `.glsl`
**Use it for:** OpenGL 4.x, Vulkan via SPIRV.
**Notes:** version pragma `#version 450`; uses `precision highp float`.

### GLSL ES — `--target glsles` (Pro)
**Extension:** `.glsles`
**Use it for:** WebGL, mobile GL ES.
**Notes:** version pragma `#version 300 es`; explicit `mediump`/`highp` qualifiers.

### WGSL (WebGPU) — `--target wgsl` (Pro)
**Extension:** `.wgsl`
**Use it for:** WebGPU in browsers, Dawn/wgpu-native applications.
**Notes:** WGSL has no forward declarations, so Forge topologically sorts functions before emit. `f32` only.

### Metal — `--target metal` (Pro)
**Extension:** `.metal`
**Use it for:** iOS / macOS Metal compute and graphics shaders.
**Notes:** `#include <metal_stdlib>`; native `half` for `f16`; validated with `xcrun -sdk macosx metal -c`. The Apple-toolchain CI (`.github/workflows/apple-validate.yml`) runs both Metal and Swift validation on every PR.

---

## Hardware (FPGA / ASIC)

### Verilog — `--target verilog` (Pro)
**Extension:** `.v`
**Use it for:** Xilinx Vivado, Intel Quartus, open-source flows (Yosys, nextpnr).
**Notes:** synthesizable; CORDIC modules pulled from `hardware/modules/` for transcendentals; `@target(fpga)` annotations drive the per-unit precision allocator (Patent #14).

### SystemVerilog — `--target systemverilog` (Pro)
**Extension:** `.sv`
**Use it for:** modern RTL workflows, formal verification with SymbiYosys, advanced Vivado/Quartus features.
**Notes:** uses `logic` instead of `wire`/`reg`; assertion macros from contracts.

### VHDL — `--target vhdl` (Pro)
**Extension:** `.vhd`
**Use it for:** safety-critical FPGA work (DO-254), aerospace and defense flows where VHDL is mandated.
**Notes:** entity/architecture pairs; `ieee.fixed_pkg` for fixed-point precision; full IEEE-1076-2008 syntax.

### Chisel / FIRRTL — `--target chisel` (Pro)
**Extension:** `.scala`
**Use it for:** RISC-V and academic/research RTL flows, anything in the Berkeley ecosystem.
**Notes:** Scala 2.13 + Chisel 3.6; emits a `Module` per function; FIRRTL passes downstream.

---

## Formal verification

### Lean 4 — `--target lean` (Free)
**Extension:** `.lean`
**Use it for:** machine-checked correctness proofs, MachLib integration.
**Notes:** every function with a `requires`/`ensures` block becomes a Lean theorem skeleton with `sorry` placeholders; functions tagged `@verify` get strict `theorem` form. The MachLib root (`--machlib-root`) supplies pre-proved lemmas — see [verify guide](verify-guide.md).

### Coq — `--target coq` (Pro)
**Extension:** `.v`
**Use it for:** Coq-resident research projects, formal proofs in the Coq ecosystem.
**Notes:** uses `Reals` library; `Definition` for non-verified, `Theorem` + `Proof.` for verified.

### Isabelle/HOL — `--target isabelle` (Pro)
**Extension:** `.thy`
**Use it for:** Isabelle/HOL projects, Sledgehammer-friendly proofs.
**Notes:** Isabelle theory files with `theory` / `imports Main` headers.

---

## Safety-critical

### Ada / SPARK — `--target ada` (Pro)
**Extension:** `.adb` (body) + `.ads` (spec)
**Use it for:** DO-178C avionics, MISRA-C-equivalent flows, safety-critical embedded.
**Notes:** SPARK 2014 mode; `Pre`/`Post` aspects from `requires`/`ensures`; static-analyzable by GNATprove.

### AUTOSAR C — `--target autosar` (Pro)
**Extension:** `.autosar.c` + `.arxml`
**Use it for:** automotive ECU code, ISO 26262 flows.
**Notes:** AUTOSAR Classic Platform-style C; `.arxml` companion for the SW component description.

### AADL — `--target aadl` (Pro)
**Extension:** `.aadl`
**Use it for:** architecture analysis, safety-critical system modeling, real-time scheduling.
**Notes:** AADLv2 syntax; one component per kernel.

### ROS 2 / C++ — `--target ros2` (Pro)
**Extension:** `_pkg/` (full ROS 2 package)
**Use it for:** robotics integration, autonomous-vehicle stacks.
**Notes:** generates a complete colcon-buildable C++ package with `package.xml`, `CMakeLists.txt`, headers, and the kernel as a node.

---

## Gaming

### Luau (Roblox) — `--target luau` (Pro)
**Extension:** `.luau`
**Use it for:** Roblox game logic.
**Notes:** Luau strict mode; uses Roblox's built-in `math.*`.

### GDScript (Godot 4) — `--target gdscript` (Pro)
**Extension:** `.gd`
**Use it for:** Godot 4 game scripts.
**Notes:** typed GDScript (`var x: float`); class-named after the module.

---

## Blockchain

### Solidity — `--target solidity` (Pro)
**Extension:** `.sol`
**Use it for:** smart contracts requiring on-chain math (DeFi, prediction markets, options pricing).
**Notes:** uses PRBMath SD59x18 for transcendentals; emits NatSpec including a per-function gas estimate. Combined with `--audit-bundle` produces a self-contained audit package: `.sol`, `.spec.json`, EML source, copies of every referenced Lean theorem, AUDITOR.md, and a manifest with sha256 of every artifact.

Companion flags:
- `--with-prbmath` — also emit a child contract wiring the transcendentals to PRBMath SD59x18.
- `--with-foundry-tests` — emit `test/<Contract>Test.t.sol` + `foundry.toml` so `forge test` runs out of the box.
- `--no-gas-estimate` — strip the gas-estimate NatSpec for diff-stable fixture comparisons.

---

## The `all` meta-target

```bash
eml-compile my_file.eml --target all -o build/
```

`all` runs every backend your tier permits and writes one file per target into the output directory. On the Free tier you'll get 9 files; on Pro you'll get all 32. Use it for cross-target equivalence testing — the bit-equivalence harness in `tests/equivalence/` validates that the C, Rust, Python, and Verilog paths produce identical results within ULP tolerance.

---

For the optimizer pipeline (constant folding, CSE, SuperBEST routing, tree-shaking) and chain-order analysis, see [`docs/architecture/`](architecture/). For the FPGA path specifically, see [fpga guide](fpga-guide.md).
