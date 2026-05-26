# First Proof-Carrying Rescue

Schema: `forge.optimizer.proof_carrying_rescue.v1`
Function family: `positive_log_energy`
Rescue operator: `log_domain_lift`
Expected transition: `domain_wall->log_domain_rescue`
MachLib obligation: `PositiveCoordinateObligation`

| sample | raw x | raw event | lifted x | lifted event | transition |
|---:|---:|---|---:|---|---|
| 0 | -2.0 | domain_wall | 0.13533528 | log_domain_rescue | `domain_wall->log_domain_rescue` |
| 1 | -0.5 | domain_wall | 0.60653066 | log_domain_rescue | `domain_wall->log_domain_rescue` |
| 2 | 0.0 | domain_wall | 1.00000000 | log_domain_rescue | `domain_wall->log_domain_rescue` |
| 3 | 0.25 | interior_sample | 1.28402542 | interior_sample | `interior_sample->interior_sample` |
| 4 | 1.25 | interior_sample | 3.49034296 | interior_sample | `interior_sample->interior_sample` |
| 5 | 2.0 | interior_sample | 7.38905610 | interior_sample | `interior_sample->interior_sample` |

Raw finite count: `3`
Lifted finite count: `6`
Rescued event count: `3`

This packet is analysis-only. It demonstrates the evidence shape for a
proof-carrying rescue; it does not claim a semantic rewrite, optimizer
release, hardware observation, or completed formal proof.
