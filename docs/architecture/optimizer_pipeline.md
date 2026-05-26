# Optimizer pipeline

> Five passes, ordered. Each one can be inspected via
> `eml-compile <file> --explain`. Pass `--no-optimize` to
> bypass the lot.

---

## The five passes

### 1. `inline_calls`

Where: `lang/optimizer/inline.py`

Inlines eligible same-module `CALL` nodes into their callers.
A function is eligible when:

- Its body is a single expression (no `let`, `let mut`,
  `while`, or `assign`).
- It is not recursive (direct or indirect).
- The caller is in the same module.

The `imported_from` field on imported functions remains; the
shake pass later drops anything still unreferenced.

### 2. `constant_folding`

Where: `lang/optimizer/constant_folding.py`

Folds pure-literal subtrees:

| Before                | After     |
|-----------------------|-----------|
| `2.0 * 3.0`           | `6.0`     |
| `exp(0.0)`            | `1.0`     |
| `x + 0.0`             | `x`       |
| `x * 1.0`             | `x`       |
| `x * 0.0`             | `0.0`     |
| `0 - x`               | `-x`      |
| `sqrt(4.0)`           | `2.0`     |

Algebraic identities trigger only when the resulting node is
provably equivalent over the reals — nothing fancy, nothing
that might paint over a domain error.

### 3. `apply_cse`

Where: `lang/optimizer/cse.py`

Common-subexpression elimination. Hoists any AST subtree that
appears more than once into a `let _cse_N =` binding. The
threshold is tuned to avoid hoisting trivial subtrees that are
cheaper to recompute than to load (literals, single VARs).

CSE is conservative around function calls: only `CALL`s into
pure functions (no `mut`, no `assign`, no `while`) participate.

### 4. `superbest_module`

Where: `lang/optimizer/superbest.py`

This is Patent #01 in operational form. For every function,
run `eml_cost.recommend_form` to find a canonical equivalent
of the body that the EML cost analyzer ranks more numerically
stable. If `digits_saved > 0.5`, rewrite to the canonical form.

Pre-filters skip the SuperBEST call when:

- The function body is pure polynomial (no transcendentals).
- The function uses no `exp` / `tanh` / `sigmoid` family
  members.
- The function has more than 10 atoms (cost analyzer is
  O(n²) on atom count).
- Any literal is irrational and not handled by the canonical
  form table.

### 5. `shake_imports`

Where: `lang/optimizer/shake.py`

Tree-shake imported functions. After inlining, any function
that arrived via `use stdlib::math;` and isn't reached by a
local `CALL` is dropped. This keeps the emitted artifacts
proportional to what the program actually uses, not to the
size of the imported modules.

---

## Inspecting a run

```
eml-compile mymodule.eml --explain --json
```

emits a stable JSON shape per function:

```json
{
  "name": "binary_classifier",
  "passes": {
    "inline_calls":     {"fired": false, "calls_inlined": 0},
    "constant_folding": {"fired": true,  "nodes_before": 17, "nodes_after": 11},
    "apply_cse":        {"fired": true,  "bindings_added": 2},
    "superbest_module": {
      "fired": true,
      "family":         "sigmoid_tanh_form",
      "digits_saved":   1.08,
      "before_score":   3.4,
      "after_score":    2.32
    },
    "shake_imports": {"fired": true, "functions_dropped": 4}
  }
}
```

`--explain` without `--json` prints a human-readable report.

---

## Adding a new pass

1. Drop the implementation under `lang/optimizer/` exposing a
   `run(module: EMLModule) -> EMLModule` function that returns
   a fresh `EMLModule` (immutable; do not mutate the input).
2. Wire it into `optimize_module` in `lang/optimizer/__init__.py`.
3. Add a regression test under `lang/optimizer/tests/`

## Log-Domain Branch

Where: `lang/optimizer/log_domain.py`

The log-domain branch is opt-in:

```python
optimize_module(mod, log_domain=True, optimizer_trace_path="trace.json")
```

It promotes the high-dimensional EML tree-space research into the real Forge
optimizer pipeline as an analysis pass. Candidate functions are annotated in
their profile with:

- `log_domain_candidate`
- `log_domain_reason`
- `log_domain_transform = "analysis_only"`

When `optimizer_trace_path` is provided, Forge writes a deterministic JSON
packet with schema `forge.optimizer.log_domain_trace.v1`.

This branch does not rewrite function semantics yet. Log-domain
parameterization changes optimizer search coordinates, not the user's function
signature, so the first production step is traceable candidate selection.
   covering both the firing and non-firing path.
4. Add an `--explain` field describing what your pass did.
5. Update the order documentation here.

The order matters. Constant folding runs after inlining
because `inline_calls` can produce new constant subexpressions
the folder can fold. SuperBEST runs after CSE because CSE
shrinks the atom count, often nudging functions over the 10-
atom threshold.
