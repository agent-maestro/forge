# EML-Lang vs Ladder Logic (and friends)

> Why ladder logic stops scaling once your control law has a
> transcendental in it, and what EML-Lang gives you instead.

---

## The shape of industrial control today

```
LADDER LOGIC (IEC 61131-3 standard):
  |---[ X1 ]---[ X2 ]---( Y1 )---|     Boolean AND
  |---[ X1 ]---+---( Y2 )--------|     Boolean OR
  |---[ X3 ]---+                  |

  For math: call a black-box FUNCTION BLOCK
  |---[ EN ]---[ PID_BLOCK ]---( OUT )---|

  What's inside PID_BLOCK? Nobody knows.
  What precision does it use? Vendor-dependent.
  Is it optimal? No way to measure.
  Is it correct? Hope so.

STRUCTURED TEXT (IEC 61131-3):
  output := Kp * error + Ki * integral + Kd * derivative;

  Better than ladder, but:
  - No structural analysis
  - No optimization beyond what the compiler does
  - No formal verification
  - Transcendental functions are opaque library calls
  - No hardware synthesis path
```

## Comparison matrix

```
                    Ladder    Structured   MATLAB    EML-Lang
                    Logic     Text (ST)    Simulink
================================================================
Boolean logic       OK        OK           OK        OK
Arithmetic          basic     OK           OK        OK
Transcendental      black-box black-box    library   NATIVE
PID control         block     code         block     TRANSPARENT
Structural analysis MISSING   MISSING      MISSING   AUTOMATIC
Chain-order types   MISSING   MISSING      MISSING   OK
Formal verification MISSING   MISSING      MISSING   LEAN
Node optimization   MISSING   MISSING      MISSING   SuperBEST
FPGA synthesis      vendor    vendor       HDL Coder NATIVE
Precision bounds    MISSING   MISSING      MISSING   LEAN-PROVED
Cross-domain search MISSING   MISSING      MISSING   find_siblings
Dynamics prediction MISSING   MISSING      MISSING   AUTOMATIC
fp16 drift warning  MISSING   MISSING      MISSING   AUTOMATIC
Open source         varies    varies       no        YES (MIT)
```

## The PID-controller example

Same control law in three languages.

### Ladder Logic

```
|---[ EN ]---[ PID_BLOCK_FB ]---( OUT )---|
              ^
              |  inputs: SP, PV, Kp, Ki, Kd
              |  parameters: stored in vendor-specific tags
              |  precision: vendor-defined; can change per firmware version
              |  proof: none
              |  FPGA synthesis: only if vendor's PLC has an FPGA backplane
```

### Structured Text

```iec
FUNCTION_BLOCK PIDController
VAR_INPUT
    SP   : REAL;
    PV   : REAL;
    Kp   : REAL := 2.5;
    Ki   : REAL := 0.1;
    Kd   : REAL := 0.05;
END_VAR
VAR
    error      : REAL;
    integral   : REAL := 0.0;
    derivative : REAL;
    last_error : REAL := 0.0;
END_VAR
VAR_OUTPUT
    Output : REAL;
END_VAR

error := SP - PV;
integral := integral + error * dt;
derivative := (error - last_error) / dt;
Output := Kp * error + Ki * integral + Kd * derivative;
last_error := error;
END_FUNCTION_BLOCK
```

Better than ladder. Still:
- The compiler knows nothing about the structural complexity
- No way to express "this MUST be polynomial-only / chain order 0"
- No precision proof
- HDL output requires a separate codegen tool with its own opinions

### EML-Lang

```eml
const Kp: Real = 2.5
const Ki: Real = 0.1
const Kd: Real = 0.05

type StableSignal = Real where chain_order <= 2

@verify(lean, theorem = "pid_bounded")
fn pid(error: Real, integral: Real, deriv: Real) -> StableSignal
    requires abs(error) < 1000.0
    requires abs(integral) < 10000.0
    ensures abs(result) < 50000.0
{
    Kp * error + Ki * integral + Kd * deriv
    // Compiler:
    //   chain_order = 0  (polynomial -- no transcendental risk)
    //   nodes = 6        (SuperBEST optimal)
    //   FPGA estimate: 6 MAC, 0 transcendental, 3 cycles @ 100 MHz
    //   Lean theorem pid_bounded auto-attempted
}
```

The engineer sees the structural complexity (chain_order = 0),
the resource cost (6 MAC, 0 transcendental), the FPGA estimate
(3 cycles), and the precision proof obligation (theorem
`pid_bounded`). All visible at compile time. None of the others
provide any of this.

## What about MATLAB / Simulink + HDL Coder?

HDL Coder takes a Simulink block diagram and emits Verilog. It's
the closest commercial product to EML-Lang's hardware backend.
What it lacks:

1. **No structural analysis.** It can't tell you "your design
   has chain order 4 — fp16 will drift." It just compiles.
2. **No formal proof.** No precision bound, no Lean theorem.
3. **Closed source.** $30K+ per seat; opaque optimizer.
4. **One-way.** Can't go from HDL back to Simulink to inspect.
5. **Tied to MATLAB.** You buy the MATLAB ecosystem to use HDL Coder.

EML-Lang is open source, source-of-truth, structurally aware,
formally verifiable, and ecosystem-independent (Python tooling +
LLVM + open FPGA flows like yosys/nextpnr).

## Where ladder logic still wins (honestly)

- **Field-engineer maintenance.** A maintenance tech can read a
  ladder diagram on a tablet and trace the rung. EML-Lang text is
  for engineers writing the control law, not for the night-shift
  tech debugging the line.
- **Existing PLC infrastructure.** Most factories run on existing
  PLCs that speak IEC 61131-3. EML-Lang interop story:
  compile to a function block (`@target(iec61131_3)`) and drop
  it into the existing ladder.
- **Regulatory inertia.** Some regulated environments (e.g.
  power utility relays) demand ladder for liability reasons.
  EML-Lang outputs a verified C reference + a ladder-block
  wrapper; the regulator gets both.

## Long-term

Ladder logic will outlive every modern language because of
inertia. EML-Lang doesn't try to replace it on the factory floor.
What it replaces is the **control-engineering process** — the
loop from "we need a new motor controller" through "ship the
bitstream" — by collapsing 5 tools (MATLAB, Simulink, HDL Coder,
hand-written C, certification consultant) into one source file
with one compiler.
