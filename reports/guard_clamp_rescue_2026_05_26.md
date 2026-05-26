# Guard-Clamp Proof-Carrying Rescue

Schema: `forge.optimizer.guard_clamp_rescue.v1`
Function family: `exp_pressure`
Rescue operator: `guard_clamp`
Expected transition: `overflow_wall->guard_rescue`
MachLib obligation: `OutputSafetyObligation`

| sample | raw x | raw event | guarded x | guarded event | transition |
|---:|---:|---|---:|---|---|
| 0 | 1.0 | interior_sample | 1.0 | interior_sample | `interior_sample->interior_sample` |
| 1 | 4.0 | interior_sample | 4.0 | interior_sample | `interior_sample->interior_sample` |
| 2 | 10.0 | interior_sample | 8.0 | interior_sample | `interior_sample->interior_sample` |
| 3 | 30.0 | overflow_wall | 8.0 | guard_rescue | `overflow_wall->guard_rescue` |
| 4 | 710.0 | overflow_wall | 8.0 | guard_rescue | `overflow_wall->guard_rescue` |
| 5 | 800.0 | overflow_wall | 8.0 | guard_rescue | `overflow_wall->guard_rescue` |

Raw finite count: `3`
Guarded finite count: `6`
Rescued event count: `3`

This packet is analysis-only. It demonstrates the evidence shape for an
overflow/output-safety rescue; it does not claim a semantic rewrite,
optimizer release, hardware observation, or completed formal proof.
