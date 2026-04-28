# Patent Index

> **Internal only.** Snapshot 2026-04-28. Sourced from prior
> patent-strengthening work in `monogate-research/exploration/
> patent-strengthening-2026-04-25/`.

| # | Status | Title | Code area |
|--:|--------|-------|-----------|
| 01 | filed | SuperBEST routing | `lang/optimizer/superbest.py` |
| 02 | filed | Hybrid routing | `lang/optimizer/superbest.py` |
| 03 | filed | Activation function selection | `industries/ml/activations/` |
| 04 | filed | Phantom attractor avoidance | `lang/optimizer/` |
| 05 | filed | Symbolic distillation | `software/backends/` |
| 06 | filed | MCTS search over EML trees | (research; not in core compiler) |
| 07 | filed | Fused kernels | `lang/optimizer/fusion.py` |
| 08 | filed | Cost branch selection | `lang/optimizer/superbest.py` |
| 09 | filed | Catalog schema | `data/operators.json` |
| 10 | filed | CapCard schema | (capcard.ai only) |
| 11 | filed | Pfaffian profile | `lang/profiler/profiler.py` |
| 12 | filed | Fusion patterns | `lang/optimizer/fusion.py` |
| 13 | filed | Loss function selection | `industries/ml/loss/` |
| 14 | filed | FPGA resource allocator | `hardware/allocator/` |
| 15 | filed | Dynamics counter (chain-order additivity) | `lang/profiler/dynamics.py` |
| 16 | filed | Living trust score | (capcard.ai only) |
| 17 | pending | Playbook inheritance | (PETAL only) |
| 18 | pending | Self-improving curriculum | (PETAL only) |
| 19 | filed | Chain regularizer (eml-cost SR) | (eml-cost only) |
| 20 | pending | Quantization drift prediction | `industries/ml/quantization/` |
| 21 | pending | Chain-order types | `lang/spec/types/chain_order_types.md`, `lang/parser/type_checker.py` |
| 22 | pending | Dual-target compilation (SW + HW from one source) | (whole `monogate-forge` architecture) |

## Counts

- Filed: 17
- Pending: 5
- **Total: 22**

## Patents directly relevant to monogate-forge

The dual-target compilation umbrella (#22) is THE patent that
defines this repo's existence. The chain-order types patent (#21)
is the language-level mechanism. Patents #14 (FPGA allocator) and
#15 (dynamics counter) gate the hardware backend's value
proposition. The remaining patents (1-13, 16-20) cover specific
methods used inside the compiler.
