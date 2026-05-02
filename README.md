# Monogate Forge

[![CI](https://github.com/agent-maestro/forge/actions/workflows/ci.yml/badge.svg)](https://github.com/agent-maestro/forge/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/monogate-forge.svg)](https://pypi.org/project/monogate-forge/)
[![VS Code Marketplace](https://img.shields.io/visual-studio-marketplace/v/monogate.eml-lang?label=VS%20Code)](https://marketplace.visualstudio.com/items?itemName=monogate.eml-lang)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/monogate-forge.svg)](https://pypi.org/project/monogate-forge/)

**Forge is the EML language and compiler. Write a math kernel once, compile it to 32 different targets — software, GPU shaders, FPGA RTL, formal-verification proofs, and safety-critical avionics — with chain-order analysis and Lean-checkable contracts on every function.**

---

## Quick start

```bash
pip install monogate-forge
```

Create `hello.eml`:

```eml
module hello;

fn pid(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
    requires (-1.0 <= error && error <= 1.0)
    ensures  (-1.5 * 1.0 <= result && result <= 1.5 * 1.0)
{
    let kp = 1.0;
    let ki = 0.2;
    let kd = 0.3;
    kp * error + ki * integral + kd * derivative
}
```

Compile to every target at once:

```bash
eml-compile hello.eml --target all -o build/
```

You now have `build/hello.c`, `build/hello.rs`, `build/hello.py`, `build/hello.lean`, `build/hello.v`, `build/hello.hlsl`, `build/hello.metal`, `build/hello.swift`, … one file per target. Pick a single target instead:

```bash
eml-compile hello.eml --target rust -o hello.rs
eml-compile hello.eml --target c    -o hello.c
eml-compile hello.eml --target lean -o Hello.lean
```

A snippet of `hello.rs`:

```rust
#[inline(always)]
pub fn pid(error: f64, integral: f64, derivative: f64) -> f64 {
    debug_assert!((-1.0_f64) <= error && error <= 1.0_f64);
    let kp: f64 = 1.0;
    let ki: f64 = 0.2;
    let kd: f64 = 0.3;
    kp * error + ki * integral + kd * derivative
}
```

Five-minute tour: [`docs/quickstart.md`](docs/quickstart.md). Full tutorial: [monogate.dev/learn/eml/intro](https://monogate.dev/learn/eml/intro).

---

## What you get

**32 backends.** Every kernel compiles to all of these from the same source.

### Software (general-purpose)
| Target | Flag | Tier |
|---|---|---|
| C99 | `--target c` | Free |
| C++17 | `--target cpp` | Free |
| Rust | `--target rust` | Free |
| Python 3 | `--target python` | Free |
| Go | `--target go` | Free |
| Java | `--target java` | Free |
| Kotlin | `--target kotlin` | Free |
| MATLAB | `--target matlab` | Free |
| C# | `--target csharp` | Pro |
| Swift | `--target swift` | Pro |
| JavaScript | `--target javascript` | Pro |

### Compiler IRs
| Target | Flag | Tier |
|---|---|---|
| LLVM IR | `--target llvm` | Pro |
| WebAssembly | `--target wasm` | Pro |

### GPU shaders
| Target | Flag | Tier |
|---|---|---|
| HLSL (DirectX) | `--target hlsl` | Pro |
| GLSL (desktop) | `--target glsl` | Pro |
| GLSL ES | `--target glsles` | Pro |
| WGSL (WebGPU) | `--target wgsl` | Pro |
| Metal (Apple) | `--target metal` | Pro |

### Hardware (FPGA / ASIC)
| Target | Flag | Tier |
|---|---|---|
| Verilog | `--target verilog` | Pro |
| SystemVerilog | `--target systemverilog` | Pro |
| VHDL | `--target vhdl` | Pro |
| Chisel / FIRRTL | `--target chisel` | Pro |

### Formal verification
| Target | Flag | Tier |
|---|---|---|
| Lean 4 | `--target lean` | Free |
| Coq | `--target coq` | Pro |
| Isabelle/HOL | `--target isabelle` | Pro |

### Safety-critical
| Target | Flag | Tier |
|---|---|---|
| Ada/SPARK | `--target ada` | Pro |
| AUTOSAR C | `--target autosar` | Pro |
| AADL | `--target aadl` | Pro |
| ROS 2 / C++ | `--target ros2` | Pro |

### Gaming
| Target | Flag | Tier |
|---|---|---|
| Luau (Roblox) | `--target luau` | Pro |
| GDScript (Godot) | `--target gdscript` | Pro |

### Blockchain
| Target | Flag | Tier |
|---|---|---|
| Solidity (PRBMath SD59x18) | `--target solidity` | Pro |

The Free tier is enough to use Forge productively for general-purpose software and Lean proofs. A Pro license unlocks every other target. Get a license at [monogateforge.com/get-started](https://monogateforge.com/get-started).

---

## VS Code extension

[![Install](https://img.shields.io/visual-studio-marketplace/d/monogate.eml-lang?label=installs)](https://marketplace.visualstudio.com/items?itemName=monogate.eml-lang)

```
ext install monogate.eml-lang
```

LSP features:

- **Chain-order on hover** — every function shows its profiled chain order, cost class, and node count.
- **Completions** — keywords (`fn`, `let`, `where`, `requires`, `ensures`, `module`, `use`), builtins (`exp`, `ln`, `sin`, `cos`, `sqrt`, `tanh`, `pow`, `clamp`, `eml`, …), stdlib modules.
- **Diagnostics** — type errors, unbound identifiers, chain-order violations, contract failures.
- **FPGA status bar** — for any function annotated `@target(fpga)`, the status bar shows estimated LUT / DSP / latency for the selected device.
- **Format on save** — canonical layout via `eml-fmt`.

Marketplace listing: [monogate.eml-lang](https://marketplace.visualstudio.com/items?itemName=monogate.eml-lang).

---

## Why Forge

Industrial automation today is stuck on ladder logic — Boolean rungs from the 1960s that can't express transcendental functions, can't prove correctness, can't optimize node count, and treat PID loops as black boxes. Structured Text is marginally better but still opaque. MATLAB/Simulink + HDL Coder will get you to FPGA, but the math hides inside vendor library calls and you have no formal proof of precision.

**EML makes every mathematical operation visible, measurable, optimizable, and formally verifiable.** Every expression is an EML tree, every function carries a chain order, every contract becomes a Lean theorem. The same source compiles to your laptop, your microcontroller, your FPGA, your Solidity contract, and your formal proof — and the cross-target equivalence harness verifies they agree to the bit.

---

## Documentation

- [Quickstart](docs/quickstart.md) — pip install to first compile in 5 minutes.
- [Language reference](docs/language-reference.md) — every keyword, builtin, type, and annotation.
- [Backends](docs/backends.md) — every compilation target with its CLI flag, file extension, and tier.
- [Verify guide](docs/verify-guide.md) — `@verify`, `requires`/`ensures`, Lean output, MachLib integration.
- [FPGA guide](docs/fpga-guide.md) — `@target(fpga)`, LUT/DSP estimates, precision selection, vendor support.

External:

- [monogate.dev/learn/eml/intro](https://monogate.dev/learn/eml/intro) — guided tutorial.
- [monogate.org](https://monogate.org) — research papers and theory.
- [machlib.org](https://machlib.org) — formal library of mathematical kernels with Lean proofs.
- [arXiv preprint](https://arxiv.org/) — the EML cost conjecture and Pfaffian profile.

---

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports and feature requests via GitHub issues.

## License

Compiler is MIT (see [`LICENSE`](LICENSE)). Specific algorithmic methods covered by patents — open implementation, but commercial re-implementations may need a license. See `patents/index.md`.

Built by [Mosa Creates LLC](https://monogateforge.com).
