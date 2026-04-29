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
expressible as math). The compiler emits:

| Target | Output | Use case |
|--------|--------|----------|
| `--target c` | C99 source linking `libmonogate.h` | Fast portable binary; gcc-compilable |
| `--target rust` | Rust source via the `monogate-sys` crate | `cargo build`-compatible |
| `--target lean` | Lean 4 theorem with `MonogateEML.Tactics` | Formal verification of `requires` → `ensures` |
| `--target verilog` | Synthesizable Verilog (Arty A7-100 default) | FPGA deployment via Vivado / yosys |
| `--allocate` | FPGA resource allocation plan | Pre-synthesis budget check |
| `--target all` | All of the above in one shot | Full cert package generation |

All of those targets share **one source of truth**: the `.eml`
file. Same parser, same profiler, same SuperBEST-routed
optimizer. The C and Verilog outputs are bit-equivalent within
3 LSBs of Q16.16 (verified by the Verilator harness when
verilator is on PATH).

---

## The 10-minute tour

### Step 1 — Look at a real example

Open `industries/aerospace/flight_control/autopilot.eml`:

```eml
@target(fpga, clock_mhz = 100, precision = float32)
@verify(lean, theorem = "autopilot_command_within_limits")
fn autopilot_step(
    pitch_setpoint: Real,
    pitch_measured: Real,
    pitch_integral: Real,
) -> Real
    requires (abs(pitch_setpoint) < 1.5708)   // |pi/2|, +/- 90 deg
    requires (abs(pitch_measured) < 1.5708)
    requires (abs(pitch_integral) < INTEGRAL_LIMIT)
    ensures  (abs(result) < ELEVATOR_MAX)
{
    let pitch_error = pitch_setpoint - pitch_measured;
    let rate_target = rate_controller(
        pitch_error, pitch_integral, pitch_measured,
    );
    clamp(Kr * rate_target, ELEVATOR_MIN, ELEVATOR_MAX)
}
```

Three things to notice:

1. **`@target(fpga, ...)`** — this function is destined for an
   FPGA. The compiler will run the FPGA allocator on it.
2. **`@verify(lean, theorem = "...")`** — emit a Lean 4 theorem
   the certifier can machine-check.
3. **`requires` / `ensures`** clauses — the safety contract.
   The Lean theorem proves `requires → ensures` (specifically
   that the elevator command stays within `ELEVATOR_MAX = 0.349
   rad = ±20°` no matter what inputs come in, as long as the
   inputs themselves stay in their declared domain).

### Step 2 — Profile it

```
$ python tools/cli/main.py \
    industries/aerospace/flight_control/autopilot.eml \
    --profile-only

# Module: autopilot  (3 fn, 8 const, 1 type)
# Source: industries\aerospace\flight_control\autopilot.eml

  gravity_compensation
    status: ok    chain_order: 2    cost_class: p2-d4-w2-c0
    dynamics: 1 osc, 0 decay  (predicted_r=2)
    fpga: 4 MAC, 0 exp, 0 ln, 1 trig (8 cy @ 32-bit)

  rate_controller
    status: ok    chain_order: 0    cost_class: p0-d2-w0-c0
    fpga: 2 MAC, 0 exp, 0 ln, 0 trig (4 cy @ 32-bit)

  autopilot_step
    status: ok    chain_order: 0    cost_class: p0-d6-w0-c0
    fpga: 6 MAC, 0 exp, 0 ln, 0 trig (12 cy @ 32-bit)
```

Each function's profile shows up immediately. The
**chain order** is the Pfaffian complexity bound — a number
the rest of the toolchain uses for stability + FPGA
estimates. For DO-178C work you constrain it via the
type aliases (`StableSignal = Real where chain_order <= 2`).

### Step 3 — Compile to C and run it

```
$ python tools/cli/main.py \
    industries/aerospace/flight_control/autopilot.eml \
    --target c -o autopilot.c

# wrote autopilot.c (1,875 bytes, 47 lines)

$ gcc autopilot.c \
    software/runtime/c/libmonogate.c \
    -I software/runtime/c \
    -lm -o autopilot.out

# (Now autopilot.out is a real executable. Add a main() that
#  calls autopilot_step() to actually run it.)
```

The generated C is plain C99 with profile comments above each
function. Reviewers can read it directly; gcc compiles it
cleanly with `-Wall -Werror`.

### Step 4 — Generate the FPGA allocation plan

```
$ python tools/cli/main.py \
    industries/aerospace/flight_control/autopilot.eml \
    --allocate

  FPGA allocation plan for Arty A7-100
  Pipeline depth: 6 stages
  Clock target:   100 MHz
  Throughput:     16.7 Msamples/s

  Resources:    300 LUTs     6 DSPs      0 KB BRAM
  MAC units:  6
  Transcendental units: none (pure-polynomial design)
```

300 LUTs out of the Arty A7-100's 63,400 — comfortable
0.5% utilization. You could fit a hundred autopilots on
one FPGA (and you might, for redundant
voting-channel architectures).

### Step 5 — One command for everything

```
$ python tools/cli/main.py \
    industries/aerospace/flight_control/autopilot.eml \
    --target all -o ./out

  # eml-compile --target all -> ./out
    [ok]   c        ./out/autopilot.c       (1,875 bytes)
    [ok]   rust     ./out/autopilot.rs      (1,808 bytes)
    [ok]   lean     ./out/autopilot.lean    (1,237 bytes)
    [ok]   verilog  ./out/autopilot.v       (1,712 bytes)
```

Four artifacts. One source. Zero hand-translation.

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
forge: parse + profile + type-check
    │
    ├──→ C99      (libmonogate.h)        ← compiles with gcc
    ├──→ Rust     (monogate-sys crate)   ← compiles with cargo
    ├──→ Verilog  (Arty A7-100 plan)     ← simulates via Verilator
    │                                       (matches C bit-for-bit)
    └──→ Lean theorem                    ← verifies via lake build
```

That's the whole compiler. Six verticals already have working
examples (`industries/aerospace`, `automotive`, `robotics`,
`medical`, `defense`, `energy`); each ships its own cert
template (DO-178C, ISO 26262, ROS 2, IEC 62304, MIL-STD-882,
NRC respectively).

---

## Where to look next

| You want to… | Read |
|--------------|------|
| Understand the language design | `lang/spec/EML_LANG_DESIGN.md` |
| See the language spec | `lang/spec/SPEC.md` |
| Browse the demo examples | `lang/spec/grammar/examples/` (10 short demos) |
| Browse the industry examples | `industries/<vertical>/` (six verticals) |
| Read the FPGA allocator design | `hardware/allocator/allocator.py` |
| Read the patent map | `patents/index.md` |
| See where the project's headed | `roadmap/phases/`, `roadmap/business/` |
| Submit something | `CONTRIBUTING.md` |

---

## What's left to ship

The compiler is real. The forge produces working artifacts in
all four targets. What's still on the roadmap:

- **Phase 2.3 (LLVM IR + WASM):** browser-deployable demos.
- **Phase 4 IDE:** VS Code extension with inline profile
  annotations.
- **More vendor FPGA targets:** Lattice ECP5 (open-source
  toolchain), Xilinx Kintex / UltraScale, Intel Cyclone /
  Stratix.
- **Q-format precision tuning:** the literals work today
  at fixed Q16.16; per-function FRAC is on deck.

See `CHANGELOG.md` for the full ship history (so far: 16
commits, 220 tests passing, 26% scaffold buildout).
