# Pfaffian profiler

> Every function in every `.eml` file gets profiled. The
> profile drives the type checker, the optimizer, the FPGA
> allocator, and the per-function comments in every emitted
> artifact.

---

## What lands on `EMLFunction.profile`

After `Profiler().profile_module(mod)`, every function in
`mod.functions` carries a populated `profile` dict (or
`status="complex_body"` for iterative bodies).

| Key                          | Type        | Meaning |
|------------------------------|-------------|---------|
| `status`                     | str         | `"ok"`, `"tuple"`, or `"complex_body"` |
| `chain_order`                | int         | Pfaffian depth — how deeply transcendentals nest |
| `max_path_r`                 | int         | Worst-case path through the AST |
| `eml_depth`                  | int         | Distance to deepest `eml(.)` call |
| `cost_class`                 | str         | `eml-cost.analyze` classification (e.g. `"p2-d4-w1-c0"`) |
| `node_count`                 | int         | Atom count of the SymPy expression |
| `dynamics`                   | dict        | `{oscillations, decays, predicted_r}` |
| `stability_warnings`         | list[str]   | Per-issue diagnostic strings |
| `fp16_drift_risk`            | str         | `"LOW"` / `"MEDIUM"` / `"HIGH"` |
| `fpga_estimate`              | dict        | MAC/exp/ln/trig units, latency cycles, precision |

The `complex_body` branch only carries `status` + `note`. Every
backend must handle that case (the C backend leaves the
function body intact and emits a `/* complex body */` comment;
the Python backend falls through to the direct AST emitter).

---

## Profiling pipeline

```
   AST function
       │
       ▼
   ┌──────────────────┐
   │ ast_to_sympy     │ — convert AST body to SymPy expression
   │ (subset only)    │
   └──────┬───────────┘
          │
          ▼
   ┌──────────────────┐
   │ eml_cost.analyze │ — chain order, cost class, node count
   └──────┬───────────┘
          │
          ▼
   ┌──────────────────────────┐
   │ eml_cost.analyze_dynamics│ — oscillations + decays
   └──────┬───────────────────┘
          │
          ▼
   ┌──────────────────────────┐
   │ stability heuristics     │ — fp16 drift, warnings
   └──────┬───────────────────┘
          │
          ▼
   ┌──────────────────────────┐
   │ fpga estimator           │ — Patent #14 unit count
   └──────────────────────────┘
```

Anything that can't be lowered to SymPy lands in
`complex_body` and the rest of the pipeline is skipped for
that function.

---

## Type checker hookup

`lang/parser/type_checker.py` reads `chain_order` from the
profile and compares against the `where chain_order <op> N`
clauses on each function:

```eml
fn safe_filter(x: f64) -> f64
  where chain_order <= 1
{
    sin(x)
}
```

Profiler reports `chain_order = 1`; the constraint `<= 1` is
satisfied; type-check passes.

```eml
fn unsafe_filter(x: f64) -> f64
  where chain_order <= 1
{
    exp(sin(x))   // chain_order = 2
}
```

Type-check fails: emitter is invoked with a poisoned module
that the backend refuses, reporting

```
type error: function 'unsafe_filter' returns chain_order 2
            but signature says <= 1
            at file:23:1
```

---

## Stability warnings

The profiler emits warnings for known fp16 drift patterns:

- **`exp(large)`** when a literal argument exceeds 50.
- **`1 / (1 + exp(-x))`** with `x` outside `[-30, 30]` —
  saturated sigmoid on f16.
- **`tan(x)`** when the domain isn't bounded by a
  `where domain: ...` clause to avoid the `π/2` pole.

Each warning reaches the C backend's per-function comment
block:

```c
/*
 * unsafe_filter
 * Chain order: 2     Cost class: p2-d4-w1-c0
 * EML depth:   2     Drift risk: HIGH
 * WARNING: tan(x) without bounded domain — risk of pole near π/2
 */
double unsafe_filter(double x) {
    return mg_tan(x);
}
```

---

## FPGA estimate (Patent #14)

The estimator counts:

- **MAC units** — one per `*` and one per `+` involving
  non-literal operands.
- **exp / ln / trig units** — one per matching node kind.
- **latency cycles** — `eml_depth` × (per-unit latency).
- **precision_bits_needed** — `f64` if `chain_order ≥ 3`,
  else `f32` if `chain_order ≥ 1`, else `f32` (default).

The allocator (`hardware/allocator/`) consumes these per-
function counts plus user constraints (`clock_mhz`,
`max_luts`, `max_dsps`, `max_brams`) to produce an
`AllocationPlan` that the Verilog/VHDL/Chisel backends
parameterize over.

---

## Programmatic API

```python
from lang.parser.parser import parse_file
from lang.profiler.profiler import Profiler

mod = parse_file("path/to/module.eml")
Profiler().profile_module(mod)

for fn in mod.functions:
    print(f"{fn.name}: {fn.profile['cost_class']}")
```

`Profiler` is stateless beyond a per-call cache, so the same
instance can be used across calls.
