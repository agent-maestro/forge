# Getting Started — Monogate Forge

> **The 10-minute tour.** Walk through compiling a real
> aerospace control law from EML-lang source to four
> deployable artifacts (C, Rust, Lean, Verilog) plus a
> DO-178C cert package, in one command.
>
> By the end of this page you'll understand what Monogate
> Forge does, why it exists, and where to look next.

---

## What Monogate Forge does

Forge is a programming language + compiler for verified
mathematical computation. You write a `.eml` source file
describing a control law (PID, FOC, autopilot, anything
expressible as math). The compiler emits **nine targets**:

| Target | Output | Use case |
|--------|--------|----------|
| `--target c`        | C99 source linking `libmonogate.h`     | Fast portable binary; gcc-compilable |
| `--target rust`     | Rust source via the `monogate-sys` crate | `cargo build`-compatible |
| `--target python`   | Python module using `math.*`           | Tooling, notebooks, golden reference |
| `--target llvm`     | Portable LLVM IR text                  | Lower with `llc` to native, ARM, RISC-V |
| `--target wasm`     | wasm32 bytecode                        | Browser-native (1op.io playground) |
| `--target verilog`  | Synthesizable Verilog                  | FPGA via Vivado / yosys |
| `--target vhdl`     | VHDL-2008                              | FPGA in shops with VHDL flows |
| `--target chisel`   | Chisel 3 / FIRRTL                      | SiFive / Chipyard / Rocket flows |
| `--target lean`     | Lean 4 theorem with `MonogateEML.Tactics` | Formal verification of `requires` → `ensures` |
| `--target all`      | All of the above in one shot           | Full cert package generation |

All of those targets share **one source of truth**: the `.eml`
file. Same parser, same profiler, same SuperBEST-routed
optimizer. The C / Rust / Verilog outputs are bit-equivalent
within 3 LSBs of Q16.16 (verified by the Verilator harness
when verilator is on PATH).

---

## The 10-minute tour

### Step 1 — Look at a real example

Open `examples/pid_controller.eml`:

```eml
@verify(lean, theorem = "pid_output_clamped")
fn pid(error: Real, integral: Real, derivative: Real) -> Real
    where chain_order <= 0
    requires (abs(error)      <= 100.0)
    requires (abs(integral)   <= 100.0)
    requires (abs(derivative) <= 100.0)
    ensures  (result >= OUT_MIN)
    ensures  (result <= OUT_MAX)
{
    let raw = Kp * error + Ki * integral + Kd * derivative;
    clamp(raw, OUT_MIN, OUT_MAX)
}
```

Three things to notice:

1. **`where chain_order <= 0`** — pure rational. The compiler
   uses chain order across the toolchain to drive stability
   bounds, FPGA cost estimates, and proof obligations.
2. **`@verify(lean, theorem = "...")`** — emit a Lean 4 theorem
   the certifier can machine-check.
3. **`requires` / `ensures`** clauses — the safety contract.
   The Lean theorem proves `requires → ensures` (specifically
   that the output stays within `[OUT_MIN, OUT_MAX]` no matter
   what inputs come in, as long as they stay in their declared
   domain).

### Step 2 — Profile it

```
$ eml-compile examples/pid_controller.eml --profile-only

# Module: pid_controller  (1 fn, 5 const)
# Source: examples/pid_controller.eml

  pid
    status: ok    chain_order: 0    cost_class: p0-d4-w0-c0
    fpga: 3 MAC, 0 exp, 0 ln, 0 trig (6 cy @ 32-bit)
```

Each function's profile shows up immediately. The
**chain order** is the Pfaffian complexity bound — a number
the rest of the toolchain uses for stability + FPGA
estimates.

### Step 3 — Compile to C and run it

```
$ eml-compile examples/pid_controller.eml --target c -o pid.c

# wrote pid.c (1,200 bytes, ~30 lines)

$ gcc pid.c \
    software/runtime/c/libmonogate.c \
    -I software/runtime/c \
    -lm -o pid.out
```

The generated C is plain C99 with profile comments above each
function. Reviewers can read it directly; gcc compiles it
cleanly with `-Wall -Werror`.

### Step 4 — Generate the FPGA allocation plan

For functions tagged `@target(fpga, ...)`, the FPGA allocator
emits a resource estimate against your chosen device:

```
$ eml-compile examples/damped_wave.eml --allocate

  FPGA allocation plan for Arty A7-100
  Pipeline depth: 4 stages
  Clock target:   100 MHz

  Resources:     90 LUTs     2 DSPs      0 KB BRAM
  MAC units:  2
  Transcendental units: 1 exp, 1 sin
```

### Step 5 — One command for everything

```
$ eml-compile examples/pid_controller.eml --target all -o ./out

  # eml-compile --target all -> ./out  (tier: Free)
    [ok]   c        ./out/pid_controller.c       (1,200 bytes)
    [ok]   rust     ./out/pid_controller.rs      (1,150 bytes)
    [ok]   lean     ./out/pid_controller.lean    (    900 bytes)
    [ok]   python   ./out/pid_controller.py      (    400 bytes)
    [ok]   javascript ./out/pid_controller.mjs   (    900 bytes)
    ...
```

Many artifacts. One source. Zero hand-translation.

You can also target any of the other five backends individually:
`--target python`, `--target llvm`, `--target wasm`,
`--target vhdl`, `--target chisel`. See
[`software_targets.md`](software_targets.md) and
[`hardware_targets.md`](hardware_targets.md) for the full
per-target walk-through.

### Step 6 — Verify the Lean theorem

The generated `autopilot.lean` is real Lean 4 source. Move
it into the upstream `monogate-lean` Lake project and run
`lake build`:

```
$ cp ./out/autopilot.lean ../monogate-lean/MonogateEML/Autopilot.lean
$ cd ../monogate-lean
$ lake build MonogateEML.Autopilot
```

If the theorem closes, you have machine-checkable proof that
the autopilot's elevator command stays within `±ELEVATOR_MAX`
regardless of inputs (under the declared `requires` clauses).
That artifact is your DO-178C verification evidence.

### Step 7 — Bit-equivalence check (optional)

If you have `verilator` on PATH, you can prove the Verilog
output and the C output produce the same numbers:

```
$ pytest hardware/simulation/tests/ -v
```

The harness compiles the Verilog with verilator, drives both
backends with random test vectors, and asserts MATCH within
3 LSBs of the Q16.16 fixed-point representation.

---

## What you just saw

```
.eml source                ← human writes math
    │
    ▼
forge: parse + profile + type-check + 5-pass optimizer
    │
    ├──→ C99      (libmonogate.h)        ← compiles with gcc
    ├──→ Rust     (monogate-sys crate)   ← compiles with cargo
    ├──→ Python   (math.*)               ← golden reference / notebooks
    ├──→ LLVM IR  (portable)             ← lower with llc to any target
    ├──→ WASM     (wasm32)               ← browser playgrounds
    ├──→ Verilog  (Arty A7-100 plan)     ← simulates via Verilator
    ├──→ VHDL     (VHDL-2008)            ← Vivado / Quartus VHDL flows
    ├──→ Chisel   (FIRRTL)               ← SiFive / Chipyard
    └──→ Lean theorem                    ← verifies via lake build
```

That's the whole compiler. The Pro tier ships pre-verified domain
kernels across **23 verticals** (aerospace, automotive, robotics,
medical, defense, energy, audio DSP + synthesis, ML inference,
scientific physics, manufacturing process control, gaming,
crypto, and more), each with its own cert template
(DO-178C, ISO 26262, ROS 2, IEC 62304, MIL-STD-882, NRC, AES-67,
MIDI, MLPerf-tiny, IEEE 754, ISA-95, etc.). See
<https://monogateforge.com/get-started> for access.

If you want a head start, **`forge.blocks`** ships 34 pre-verified
computation blocks (PID, sigmoid, Park, Kalman, biquad, …) where
the parse + profile + FPGA allocation are pre-cached at import
time. See [`language_guide.md`](language_guide.md#using-forgeblocks)
for the tour.

---

## Where to look next

| You want to… | Read |
|--------------|------|
| Write your first .eml file              | [`language_guide.md`](language_guide.md) |
| Compile to C / Rust / Python / LLVM / WASM | [`software_targets.md`](software_targets.md) |
| Compile to Verilog / VHDL / Chisel      | [`hardware_targets.md`](hardware_targets.md) |
| Use `@verify(lean)` blocks              | [`verification_guide.md`](verification_guide.md) |
| Skim the architecture                   | [`architecture/overview.md`](architecture/overview.md) |
| CLI reference                           | [`api_reference/cli.md`](api_reference/cli.md) |
| Backend reference                       | [`api_reference/backends.md`](api_reference/backends.md) |
| FPGA / ASIC target catalogue            | [`api_reference/targets.md`](api_reference/targets.md) |
| Browse the public examples              | [`examples/`](../examples/) (12 short, public-domain teaching files) |
| Browse the demo grammar fixtures        | `lang/spec/grammar/examples/` (10 short demos) |
| Pre-verified domain library             | Forge Pro — see <https://monogateforge.com/get-started> |
| Browse pre-verified blocks              | [`forge/blocks/README.md`](../forge/blocks/README.md) |
| Read the language design                | `lang/spec/EML_LANG_DESIGN.md` |
| Read the FPGA allocator design          | `hardware/allocator/allocator.py` |
| Read the patent map                     | `patents/index.md` |
| See where the project's headed          | `roadmap/phases/`, `roadmap/business/` |
| Submit something                        | `CONTRIBUTING.md` |

---

## What's left to ship

The compiler is real. The forge produces working artifacts in
**all nine targets**. What's still on the roadmap:

- **CUDA-accelerated Verilator simulation** (Blackwell-gated):
  batch FPGA simulation of 10K+ test vectors per testbench.
- **Vendor synth + bitstream smoke**: Vivado / Quartus / OpenLane
  flows wired into CI. Today the toolchain is on the user's
  PATH; the harness expects it.
- **Place-and-route closure feedback** into the FPGA allocator.
- **JetBrains plugin polish**: 0.1 scaffold ships; grammar-driven
  lexer + CodeVision land in 0.2.
- **VS Code SuperBEST visualization**: extension shows the
  routing decision per-node.

See `CHANGELOG.md` for the full ship history. Live counters:
**~677 tests passing**, 56% scaffold buildout, 9/9 backends
live, 5 FPGA/ASIC targets, 11 industry verticals, 34 pre-verified
blocks in `forge.blocks`.
