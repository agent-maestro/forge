# EML-Lang: A Programming Language for Verified Mathematical Computation

**Status:** PLANNING — foundational pieces exist, language design is new
**What this is:** A programming language where every expression is an
EML tree. The compiler optimizes via SuperBEST routing, verifies via
Lean proofs, and targets BOTH software (C/Rust/Python) AND hardware
(FPGA bitstream). The full stack from human-readable math to silicon.
**Why it's better than ladder logic:** Ladder logic is Boolean rungs
from the 1960s. It can't express transcendental functions, can't
prove correctness, can't optimize node count, and treats PID loops
as black boxes. EML-lang makes every mathematical operation visible,
measurable, optimizable, and formally verifiable.
**Patent coverage:** #11 (profiling), #12 (fusion), #14 (FPGA allocator),
#01/#02/#08 (routing). Language itself is new IP (#21 chain-order types,
#22 dual-target compilation).

---

## Why This Matters

### What industrial automation uses today

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

### What EML-lang provides

```
EML-LANG:
  // PID controller — every operation is visible
  control pid(error: Real, integral: Real, derivative: Real) -> Real {
    let proportional = Kp * error           // chain 0, 2 nodes
    let integral_term = Ki * integral       // chain 0, 2 nodes
    let derivative_term = Kd * derivative   // chain 0, 2 nodes
    proportional + integral_term + derivative_term  // chain 0, 6 nodes total
  }

  // Compiler tells you:
  //   chain_order: 0 (purely polynomial — no transcendental risk)
  //   total_nodes: 6 (SuperBEST optimal)
  //   precision: bounded by Lean theorem pid_relerr_bound
  //   FPGA: 6 MAC units, 0 transcendental units needed

  // Now compare with a nonlinear controller:
  control nonlinear_pid(error: Real, t: Real) -> Real {
    let gain = exp(-decay * t) * cos(omega * t)  // chain 3, 7 nodes
    gain * error                                  // chain 3, 9 nodes total
  }

  // Compiler tells you:
  //   chain_order: 3 (1 oscillation + 1 decay — needs exp + cos)
  //   total_nodes: 9
  //   precision: relerr <= 2.2e-16 (Lean-verified)
  //   dynamics: 1 oscillation mode, 1 decay mode
  //   FPGA: 6 MAC + 1 exp unit + 1 trig unit (Patent #14 allocates)
  //   WARNING: chain 3 means fp16 quantization will drift (Patent #4)
```

The engineer sees EVERYTHING. The chain order tells them the structural
complexity before they compile. The dynamics counter tells them what
physical phenomena the controller encodes. The FPGA allocator tells
them exactly what hardware they need. Lean proves the precision bounds.

Ladder logic can do NONE of this.

---

## The Language

### Design Principles

```
1. EVERY expression is an EML tree under the hood
2. The compiler MEASURES before it compiles (profiling is automatic)
3. SuperBEST routing is the default optimizer (not optional)
4. Chain order is a FIRST-CLASS concept (like types)
5. Lean verification is available (not required for every program)
6. Dual target: software AND hardware from the same source
7. Readable by humans AND agents (structured, not visual rungs)
```

### Syntax

```eml
// EML-lang source file: motor_control.eml

// Constants
const Kp: Real = 2.5
const Ki: Real = 0.1
const Kd: Real = 0.05
const omega: Real = 60.0    // motor speed rad/s
const decay: Real = 0.02    // damping coefficient

// Type annotations include chain order constraints
type StableSignal = Real where chain_order <= 2
type OscSignal = Real where chain_order >= 2

// Functions — the compiler profiles every expression
fn pid_output(error: Real, integral: Real, deriv: Real) -> StableSignal {
    Kp * error + Ki * integral + Kd * deriv
    // Compiler: chain_order = 0 (polynomial), 6 nodes
    // Type check: 0 <= 2 ✓ (satisfies StableSignal)
}

fn damped_response(t: Real, amplitude: Real) -> OscSignal {
    amplitude * exp(-decay * t) * cos(omega * t)
    // Compiler: chain_order = 3 (1 osc + 1 decay), 9 nodes
    // Type check: 3 >= 2 ✓ (satisfies OscSignal)
}

fn motor_torque(voltage: Real, speed: Real) -> Real {
    let back_emf = voltage - speed * Kv
    let current = back_emf / R
    current * Kt
    // Compiler: chain_order = 0, 7 nodes
}

// The dangerous one — compiler warns you
fn unstable_gain(x: Real) -> Real {
    1.0 / (1.0 + exp(-100.0 * x))
    // Compiler WARNING:
    //   chain_order = 2 (sigmoid)
    //   fp16_drift_risk = HIGH (steep sigmoid, k=100)
    //   SUGGEST: use stable_sigmoid form (8.6x better precision)
    //   Patent #4: phantom attractor risk at float32
}

// Hardware-targeted block
@target(fpga, clock_mhz = 100, precision = float32)
fn realtime_control(sensor: Real) -> Real {
    let error = setpoint - sensor
    let output = pid_output(error, accumulator, last_error - error)
    clamp(output, -1.0, 1.0)
    // FPGA synthesis:
    //   6 MAC units allocated
    //   0 transcendental units (chain 0)
    //   Latency: 3 clock cycles at 100 MHz
    //   Patent #14: workload profile → hardware config
}

// Lean-verified block
@verify(lean, theorem = "pid_bounded")
fn safe_pid(error: Real, integral: Real, deriv: Real) -> Real
    requires abs(error) < 1000.0
    requires abs(integral) < 10000.0
    ensures abs(result) < 50000.0
{
    pid_output(error, integral, deriv)
    // Lean generates and checks:
    //   theorem pid_bounded : forall error integral deriv,
    //     abs error < 1000 -> abs integral < 10000 ->
    //     abs (pid_output error integral deriv) < 50000
}
```

### Type System

```eml
// Chain order is part of the type system

type Polynomial = Real where chain_order == 0
type SingleExp = Real where chain_order == 1
type Oscillatory = Real where chain_order >= 2
type Stable = Real where chain_order <= 1

// The compiler enforces these at compile time:

fn safe_filter(x: Stable) -> Stable {
    0.5 * x + 0.3    // chain 0, returns Stable ✓
}

fn safe_filter_BAD(x: Stable) -> Stable {
    sin(x)            // chain 2 — COMPILE ERROR:
                      // "sin(x) has chain_order 2,
                      //  but return type requires <= 1"
}

// This catches structural errors at COMPILE TIME
// that ladder logic can never catch
```

### Built-in Profiling

```eml
// Every expression automatically gets profiled

fn example(x: Real) -> Real {
    exp(x) * cos(omega * x) + ln(x)
}

// Compiler output (always visible, not optional):
//
// PROFILE: example
//   chain_order: 3
//   max_path_r: 2
//   eml_depth: 7
//   cost_class: p3-d7-w2-c1
//   dynamics: 1 oscillation, 0 decays
//   nodes: 7 (SuperBEST optimal)
//   siblings: ["damped oscillator (physics)",
//              "FM carrier (audio)"]
//   stability: ln(x) undefined for x <= 0 — domain restriction
//   fpga_estimate: 2 exp + 1 ln + 1 cos + 3 MAC = 7 units
```

---

## The Compiler

### Architecture

```
SOURCE CODE (.eml file)
       │
       ▼
┌──────────────┐
│    PARSER    │ ← ANTLR4 grammar for EML-lang
│              │   Produces typed AST
└──────┬───────┘
       │
       ▼
┌──────────────┐
│   PROFILER   │ ← eml-cost integration (automatic)
│              │   Computes chain order, cost class,
│              │   dynamics for every expression
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  TYPE CHECK  │ ← Verifies chain-order type constraints
│              │   "This function claims to return Stable
│              │    but the expression has chain_order 3"
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  OPTIMIZER   │ ← SuperBEST routing (automatic)
│              │   Minimizes node count
│              │   Applies fusion patterns (Patent #12)
│              │   Selects optimal operator from 23 family
└──────┬───────┘
       │
       ├──────────────────────┐
       │                      │
       ▼                      ▼
┌──────────────┐     ┌──────────────┐
│  SOFTWARE    │     │   HARDWARE   │
│  BACKEND     │     │   BACKEND    │
│              │     │              │
│ C / Rust /   │     │ FPGA / ASIC  │
│ Python /     │     │ Verilog /    │
│ LLVM IR      │     │ VHDL         │
└──────┬───────┘     └──────┬───────┘
       │                      │
       ▼                      ▼
  libmonogate.h          bitstream
  (Patent #01-#08)       (Patent #14)
       │                      │
       ▼                      ▼
   Runs on CPU           Runs on FPGA
   Lean-verified         Silicon-verified
```

### Compilation Targets

```
SOFTWARE TARGETS:
  C99          → libmonogate.h calls (existing roadmap Product 1)
  Rust         → monogate-sys crate
  Python       → NumPy/SymPy (Tool 5 transpiler, already shipped)
  LLVM IR      → any LLVM backend (x86, ARM, RISC-V, WebAssembly)
  WebAssembly  → browser execution (1op.io demos)

HARDWARE TARGETS:
  Verilog      → FPGA synthesis (Xilinx Vivado, Intel Quartus)
  VHDL         → alternative FPGA synthesis
  SystemC      → hardware simulation
  Chisel/FIRRTL → parameterized hardware generation

VERIFICATION TARGETS:
  Lean 4       → formal proofs of precision and correctness
  SMT (Z3)     → automated constraint checking
  CBMC         → bounded model checking of generated C
```

---

## Phase 1: Language Design + Parser (3 sessions)

### 1.1 Grammar definition (1 session)

```antlr
// eml_lang.g4 — ANTLR4 grammar

grammar EMLLang;

program: (declaration | function | constant)* EOF;

constant: 'const' ID ':' type '=' expr;

function: annotation* 'fn' ID '(' params ')' '->' type
          requires* ensures* block;

annotation: '@target' '(' targetSpec ')'
          | '@verify' '(' verifySpec ')';

type: 'Real'
    | 'Real' 'where' constraint
    | ID;

constraint: 'chain_order' comparator INTEGER;

comparator: '<=' | '>=' | '==' | '<' | '>';

expr: expr ('*' | '/' | '+' | '-') expr    // arithmetic
    | 'exp' '(' expr ')'                    // transcendental
    | 'ln' '(' expr ')'
    | 'sin' '(' expr ')'
    | 'cos' '(' expr ')'
    | 'sqrt' '(' expr ')'
    | 'eml' '(' expr ',' expr ')'          // raw EML operator
    | 'pow' '(' expr ',' expr ')'
    | ID '(' args ')'                       // function call
    | ID                                     // variable
    | NUMBER                                 // literal
    | '(' expr ')';                         // grouping

block: '{' statement* expr '}';

statement: 'let' ID (':' type)? '=' expr;
```

### 1.2 Parser implementation (1 session)

```python
# eml_lang/parser.py

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

class NodeKind(Enum):
    CONST = "const"
    VAR = "var"
    BINOP = "binop"
    CALL = "call"
    EML = "eml"
    EXP = "exp"
    LN = "ln"
    SIN = "sin"
    COS = "cos"
    SQRT = "sqrt"
    LET = "let"
    FUNC = "func"

@dataclass
class ASTNode:
    kind: NodeKind
    value: any = None
    children: List['ASTNode'] = None
    type_annotation: str = None
    chain_constraint: dict = None
    line: int = 0
    col: int = 0

@dataclass
class EMLFunction:
    name: str
    params: List[dict]  # [{"name": "x", "type": "Real"}]
    return_type: str
    return_constraint: dict  # {"chain_order": "<=", "value": 2}
    body: ASTNode
    annotations: List[dict]  # [@target(...), @verify(...)]
    requires: List[str]
    ensures: List[str]

    # Computed by profiler (filled in after parsing)
    profile: dict = None  # chain_order, cost_class, dynamics, etc.
```

### 1.3 Profiler integration (1 session)

```python
# eml_lang/profiler.py

from eml_cost import analyze, canonicalize, analyze_dynamics
from eml_cost import predict_chain_order_via_additivity

class Profiler:
    """
    Automatically profile every expression in an EML-lang program.
    This runs DURING compilation, not as a separate step.
    """

    def profile_function(self, func: EMLFunction) -> dict:
        """Profile a function's body expression."""
        sympy_expr = self.ast_to_sympy(func.body)
        canonical = canonicalize(sympy_expr)
        result = analyze(canonical)
        dynamics = analyze_dynamics(sympy_expr)

        profile = {
            'chain_order': result.pfaffian_r,
            'max_path_r': result.max_path_r,
            'eml_depth': result.eml_depth,
            'structural_overhead': result.structural_overhead,
            'cost_class': result.cost_class,
            'dynamics': {
                'oscillations': dynamics.n_oscillations,
                'decays': dynamics.n_decays,
                'predicted_r': dynamics.predicted_r,
            },
            'node_count': result.eml_depth,
            'stability_warnings': self.check_stability(sympy_expr),
            'fp16_drift_risk': self.assess_drift_risk(result),
            'fpga_estimate': self.estimate_fpga(result),
        }

        func.profile = profile
        return profile
```

### Deliverables Phase 1
- [ ] ANTLR4 grammar for EML-lang
- [ ] Parser producing typed AST
- [ ] Profiler integration (automatic on every expression)
- [ ] Chain-order type checking
- [ ] FPGA resource estimation
- [ ] 10 example .eml programs
- [ ] Tests for parser + profiler + type checker

---

## Phase 2: Software Compiler Backend (4 sessions)

### 2.1 C backend via libmonogate (1 session)

```python
# eml_lang/backends/c_backend.py

class CBackend:
    """Compile EML-lang to C code using libmonogate.h."""

    def compile(self, program: List[EMLFunction]) -> str:
        """Generate complete C source file."""
        lines = ['#include "libmonogate.h"', '#include <math.h>', '']
        for func in program:
            lines.append(self.compile_function(func))
        return '\n'.join(lines)
```

### 2.2 Rust backend (1 session)

Rust output uses the `monogate-sys` crate. Same SuperBEST routing
as the C backend; same per-function profile comments emitted.

### 2.3 LLVM IR backend (1 session)

LLVM IR for portability — x86, ARM, RISC-V, WebAssembly all fall
out of LLVM's target backends. Each EML operator becomes an LLVM
function call; SuperBEST routing decides which.

### 2.4 Lean verification backend (1 session)

```python
# eml_lang/backends/lean_backend.py

class LeanBackend:
    """
    Compile EML-lang @verify blocks to Lean 4 theorems.

    Input:
      @verify(lean, theorem = "pid_bounded")
      fn safe_pid(error: Real) -> Real
          requires abs(error) < 1000
          ensures abs(result) < 50000
      { ... }

    Output:
      theorem pid_bounded (error : R)
          (h : abs error < 1000) :
          abs (safe_pid error) < 50000 := by
        unfold safe_pid
        -- auto-generated proof attempt
        sorry -- or actual proof if eml_auto closes it
    """
```

### Deliverables Phase 2
- [ ] C backend (libmonogate.h calls)
- [ ] Rust backend (monogate-sys crate)
- [ ] LLVM IR backend (portable)
- [ ] Lean backend (@verify blocks to theorems)
- [ ] Python backend (reuse Tool 5 transpiler)
- [ ] All backends share the same SuperBEST optimizer
- [ ] Tests: compile 10 example programs to each target

---

## Phase 3: Hardware Compiler Backend (4 sessions)

### 3.1 FPGA resource allocator (1 session)

```python
# eml_lang/backends/fpga_allocator.py
# Implements Patent #14

class FPGAAllocator:
    """
    Given a program's aggregate Pfaffian profile, allocate FPGA
    resources: how many exp blocks, how many ln blocks, which
    fusion patterns to instantiate, bit precision per block,
    pipeline depth.
    """

    def allocate(self, program: List[EMLFunction],
                 constraints: dict) -> dict:
        """
        constraints:
          clock_mhz: target clock frequency
          precision: float16 / float32 / float64
          max_luts: LUT budget
          max_dsps: DSP block budget
          max_brams: block RAM budget
        """
```

### 3.2 Verilog code generator (2 sessions)

Each EML operator maps to a hardware module:
- `exp(x)`: CORDIC or polynomial approximation block
- `ln(x)`: CORDIC or series expansion block
- add/mul/div: standard arithmetic units
- SuperBEST routing: combinational logic selecting optimal path

### 3.3 Simulation + verification (1 session)

Simulate the generated Verilog using Verilator before synthesis.
Compare software and hardware outputs to verify correctness.
On Blackwell: use CUDA to accelerate the simulation.

### Deliverables Phase 3
- [ ] FPGA resource allocator (Patent #14 implementation)
- [ ] Verilog code generator
- [ ] CORDIC-based exp/ln hardware modules
- [ ] Pipeline generator from EML trees
- [ ] Simulation framework (Verilator integration)
- [ ] Software vs hardware verification
- [ ] Tests on 5 example programs

---

## Phase 4: IDE + Developer Experience (2 sessions)

### 4.1 VS Code extension for EML-lang

- Syntax highlighting for `.eml` files
- Inline Pfaffian profile annotations
- Chain-order type error highlighting
- FPGA resource estimation in status bar
- "Compile to..." command (C / Rust / Verilog / Lean)
- SuperBEST routing visualization
- Dynamics counter output in hover
- Auto-complete for EML operators

### 4.2 CLI compiler

```bash
eml-compile motor_control.eml --target c --output motor_control.c
eml-compile motor_control.eml --target verilog --output motor_control.v \
    --clock 100 --precision float32 --max-luts 50000
eml-compile motor_control.eml --profile-only
eml-compile motor_control.eml --target lean --verify
eml-compile motor_control.eml --target all --verify --fpga-sim
```

### Deliverables Phase 4
- [ ] VS Code extension with syntax highlighting + profiling
- [ ] CLI compiler (eml-compile)
- [ ] Profile-only mode
- [ ] Multi-target compilation
- [ ] Man page / documentation

---

## Comparison: EML-Lang vs Existing Languages

```
                    Ladder    Structured   MATLAB    EML-Lang
                    Logic     Text (ST)    Simulink
================================================================
Boolean logic       ✓         ✓            ✓         ✓
Arithmetic          basic     ✓            ✓         ✓
Transcendental      black-box black-box    library   NATIVE
PID control         block     code         block     TRANSPARENT
Structural analysis ✗         ✗            ✗         AUTOMATIC
Chain-order types   ✗         ✗            ✗         ✓
Formal verification ✗         ✗            ✗         LEAN
Node optimization   ✗         ✗            ✗         SuperBEST
FPGA synthesis      vendor    vendor       HDL Coder NATIVE
Precision bounds    ✗         ✗            ✗         LEAN-PROVED
Cross-domain search ✗         ✗            ✗         find_siblings
Dynamics prediction ✗         ✗            ✗         AUTOMATIC
fp16 drift warning  ✗         ✗            ✗         AUTOMATIC
Open source         varies    varies       ✗         ✓
```

---

## Timeline

```
PHASE 1 (month 1-2): Language + Parser
  Grammar, parser, profiler integration, type checker
  3 sessions

PHASE 2 (month 2-4): Software Backends
  C, Rust, LLVM, Lean, Python backends
  4 sessions

PHASE 3 (month 4-6): Hardware Backend
  FPGA allocator, Verilog generator, simulation
  4 sessions
  (Blackwell box enables CUDA-accelerated simulation)

PHASE 4 (month 6-7): IDE + DX
  VS Code extension, CLI compiler
  2 sessions

TOTAL: 13 sessions over 7 months
```

---

## Patent Implications

```
ALREADY COVERED:
  #01,#02,#08 — routing (compiler optimizer uses these)
  #11 — profiling (compiler profiles automatically)
  #12 — fusion patterns (compiler applies these)
  #14 — FPGA allocator (hardware backend implements this)

NEW IP TO CONSIDER:
  #21 — Chain-order type system
    "A type system for programming languages where types
    include Pfaffian chain order constraints, enabling
    compile-time verification of structural complexity"

  #22 — Dual-target compilation from EML trees
    "A compiler that generates both software (C/Rust/LLVM)
    and hardware (Verilog/VHDL) from a single EML-tree
    intermediate representation with automatic resource
    allocation"

  Both are novel. Neither exists in any PLC or HDL compiler.
  File when the compiler ships.
```

---

## Standing Rules
- The language is READABLE by humans AND agents
- Every expression gets profiled AUTOMATICALLY (no opt-in)
- Chain-order type constraints are ENFORCED at compile time
- SuperBEST routing is the DEFAULT optimizer (not optional)
- FPGA synthesis uses Patent #14's allocator
- The compiler NEVER silently loses precision
  (if chain_order >= 3 and target is float16, it's a compile ERROR)
- Lean verification is AVAILABLE but not REQUIRED
  (@verify blocks opt in; everything else compiles without proofs)
- The language does NOT replace general-purpose languages
  (it targets MATHEMATICAL COMPUTATION specifically)
- Ladder logic interop: an EML-lang function can be wrapped
  as an IEC 61131-3 function block for use in existing PLCs
- Open source (MIT license for compiler, patents cover the methods)
