# Precision-Escape Proof-Carrying Rescue

Schema: `forge.optimizer.precision_escape_rescue.v1`
Function family: `quantized_basin`
Rescue operator: `precision_escape`
Expected transition: `phantom_attractor->interior_sample`
MachLib obligation: `PrecisionSensitivityObligation`

| sample | x | raw event | low-grad | high-grad | escaped x | transition |
|---:|---:|---|---:|---:|---:|---|
| 0 | 0.25 | phantom_attractor | 0.0000000000 | -0.2500000000 | 0.3750000000 | `phantom_attractor->interior_sample` |
| 1 | 0.5 | phantom_attractor | 0.0000000000 | 0.2500000000 | 0.3750000000 | `phantom_attractor->interior_sample` |
| 2 | 0.75 | phantom_attractor | 0.0000000000 | 0.7500000000 | 0.3750000000 | `phantom_attractor->interior_sample` |

Phantom event count: `3`
Rescued event count: `3`

This packet is analysis-only. It demonstrates one suspicious finite trap
that is sensitive to precision and escapable under replay; it does not
claim a true local optimum, semantic rewrite, optimizer release, hardware
observation, or completed formal proof.
