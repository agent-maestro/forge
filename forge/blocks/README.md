# `forge.blocks` — pre-verified standard library

> 34 blocks across 6 categories. Parse + profile + allocate happen
> once at import time; every subsequent compile is a dict lookup.

---

## Categories

| Module                       | Blocks                                                                |
|------------------------------|-----------------------------------------------------------------------|
| `forge.blocks.polynomial`    | `linear`, `quadratic`, `power_squared/cubed/quartic`, `horner_quintic`|
| `forge.blocks.oscillator`    | `sin_block`, `cos_block`, `damped_osc`, `fm_carrier`, `chirp`         |
| `forge.blocks.exponential`   | `exp_block`, `decay`, `growth`, `sigmoid_block`, `softplus`, `tanh_block` |
| `forge.blocks.control`       | `pid`, `pid_anti_windup`, `state_space_step`, `luenberger_observer`, `kalman_1d`, `lpf1` |
| `forge.blocks.signal`        | `fft_butterfly`, `convolution_3tap/5tap`, `biquad_step`, `moving_average_4`, `one_pole_hpf` |
| `forge.blocks.transform`     | `clarke`, `inverse_clarke`, `park`, `inverse_park`, `dq0`             |

---

## The `Block` dataclass

```python
@dataclass(frozen=True)
class Block:
    name:               str
    eml_tree:           ASTNode
    chain_order:        int
    node_count:         int
    cost_class:         str
    arity:              int = 1
    parameters:         tuple[str, ...] = ()
    lean_theorem:       str = ""
    fpga_allocation:    dict = ...
    source:             str = ""
    function:           EMLFunction | None = None
```

Each field is computed once at module import time:

- `eml_tree` — the parsed AST body (a `BLOCK` `NodeKind`).
- `chain_order` / `node_count` / `cost_class` — from the profiler.
- `fpga_allocation` — flat dict from the FPGA allocator (only for
  blocks carrying `@target(fpga, ...)`; empty otherwise).
- `lean_theorem` — literal Lean 4 statement; verification status
  tracked in `monogate-lean/MonogateEML/Tactics.lean`.

---

## Composition

```python
from forge.blocks.polynomial   import linear, quadratic
from forge.blocks.exponential  import sigmoid_block

# pipeline = sigmoid(m*x + b)
pipeline = linear >> sigmoid_block

assert pipeline.chain_order == max(linear.chain_order,
                                   sigmoid_block.chain_order)
assert pipeline.node_count  == linear.node_count + sigmoid_block.node_count
```

Compose-time invariant: `chain_order(A >> B) = max(A.chain_order,
B.chain_order)`. The compiler enforces this — if `A >> B` would
violate a downstream `where chain_order <= N` clause, the compose
itself raises before any code is emitted.

Constraints on composition:

- The right-hand side block must have `arity == 1` (single input).
  Multi-input rhs needs a join combinator (not yet shipped).
- The right-hand side block's body must be a single expression;
  blocks with `let` / `while` / `assign` cannot be on the rhs of
  compose. Use them as terminal nodes instead.

---

## Compile-time speedup

```python
from forge.blocks.polynomial   import linear
from software.backends.c_backend import CBackend

# Block path: AST + profile already cached
src = CBackend().compile(linear.to_module())
```

vs.

```python
from lang.parser.parser  import parse_source
from lang.profiler.profiler import Profiler
from software.backends.c_backend import CBackend

mod = parse_source(LINEAR_SRC)
Profiler().profile_module(mod)            # full profile pass
src = CBackend().compile(mod)              # backend re-runs optimizer
```

For the trivial `linear` block the speedup is ~2x. For blocks
carrying `@target(fpga, ...)`, where the FPGA allocator runs once
at import time and the compile path skips it entirely, the
speedup is closer to 10x.

---

## Public API

```python
from forge.blocks import (
    Block,
    BlockCompositionError,
    compose,           # functional form of >>
    get,               # registry lookup by name
    list_blocks,       # registry view
    make_block,        # build a new Block from EML source
    register,          # add to the registry
)
```

---

## Tests

```
forge/blocks/tests/test_blocks_core.py     # 34 tests: dataclass + compose
forge/blocks/tests/test_blocks_speedup.py  # 5 tests: cache speedup + invariants
```
