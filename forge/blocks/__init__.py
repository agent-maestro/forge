"""forge.blocks — standard library of pre-verified EML computation blocks.

Each block lands as a frozen dataclass with everything the compiler
needs already pre-computed: the parsed AST, the chain order, the cost
class, the FPGA allocation, and (for the proof-bearing blocks) a Lean
theorem statement. When user code imports a block, the compiler skips
parsing + profiling + optimization + allocation and uses the cached
values directly. Compilation drops from seconds to milliseconds.

Usage
=====

::

    from forge.blocks.oscillator   import sin_block, damped_osc
    from forge.blocks.exponential  import sigmoid_block
    from forge.blocks              import compose, get, list_blocks

    # Direct use
    sin_block.chain_order   # -> 1
    sin_block.cost_class    # -> 'p1-d2-w0-c0'

    # Composition: chain_order = max(...)
    pipeline = sin_block >> sigmoid_block
    assert pipeline.chain_order == max(sin_block.chain_order,
                                       sigmoid_block.chain_order)

    # Registry lookup
    pid = get("pid")
    blocks = list_blocks()  # all registered Block instances

The bookkeeping (parse, profile, allocate, register) happens once at
module-import time; everything after is O(1).

Lean theorems
=============

Blocks shipping with `lean_theorem` carry a literal Lean 4 statement
that has either been verified inside the `monogate-lean` Lake project
or that we believe `eml_auto` can close. Verification status of the
canonical theorems is tracked in
`monogate-lean/MonogateEML/Tactics.lean`.

See also
========

- `forge.blocks.compose` — the composition operator + arity check.
- `tests/integration/test_forge_blocks.py` — equivalence test.
"""

from __future__ import annotations

from forge.blocks._core import (
    Block,
    BlockCompositionError,
    compose,
    get,
    list_blocks,
    make_block,
    register,
)

# Importing the modules below causes their top-level `make_block(...)`
# calls to fire and register every shipped block in the global
# registry. Keep this list ordered by abstraction layer.
from forge.blocks import polynomial    # noqa: E402, F401
from forge.blocks import oscillator    # noqa: E402, F401
from forge.blocks import exponential   # noqa: E402, F401
from forge.blocks import control       # noqa: E402, F401
from forge.blocks import signal        # noqa: E402, F401
from forge.blocks import transform     # noqa: E402, F401


__all__ = [
    "Block",
    "BlockCompositionError",
    "compose",
    "get",
    "list_blocks",
    "make_block",
    "register",
    # Submodules with their typed exports.
    "polynomial",
    "oscillator",
    "exponential",
    "control",
    "signal",
    "transform",
]
