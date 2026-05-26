# Saturation-Deshelf Proof-Carrying Rescue

Schema: `forge.optimizer.saturation_deshelf_rescue.v1`
Function family: `saturated_response`
Rescue operator: `saturation_deshelf`
Expected transition: `saturation_shelf->corner_concentration`
MachLib obligation: `ClampInvariantObligation`

| sample | x | raw value | raw event | pre-clamp pressure | deshelf event | transition |
|---:|---:|---:|---|---:|---|---|
| 0 | -2.0 | 0.1353352832 | interior_sample | 0.1269280110 | interior_sample | `interior_sample->interior_sample` |
| 1 | 0.0 | 1.0000000000 | interior_sample | 0.6931471806 | interior_sample | `interior_sample->interior_sample` |
| 2 | 2.0 | 1.0000000000 | saturation_shelf | 2.1269280110 | saturation_shelf | `saturation_shelf->saturation_shelf` |
| 3 | 4.0 | 1.0000000000 | saturation_shelf | 4.0181499279 | corner_concentration | `saturation_shelf->corner_concentration` |
| 4 | 8.0 | 1.0000000000 | saturation_shelf | 8.0003354064 | corner_concentration | `saturation_shelf->corner_concentration` |

Saturation event count: `3`
Deshelved event count: `2`

This packet is analysis-only. It demonstrates a finite clamp shelf being
replayed as measurable boundary structure; it does not claim a semantic
rewrite, optimizer release, hardware observation, global optimizer win,
or completed formal proof.
