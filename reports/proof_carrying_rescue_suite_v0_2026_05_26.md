# Proof-Carrying Rescue Suite v0

Schema: `forge.optimizer.proof_carrying_rescue_suite.v0`
Lanes: `4`
Complete v0: `True`

| rescue operator | transition | obligation | source | witness |
|---|---|---|---|---:|
| `log_domain_lift` | `domain_wall->log_domain_rescue` | `PositiveCoordinateObligation` | `examples/proof_carrying_rescue.eml` | true |
| `guard_clamp` | `overflow_wall->guard_rescue` | `OutputSafetyObligation` | `examples/guard_clamp_rescue.eml` | true |
| `precision_escape` | `phantom_attractor->interior_sample` | `PrecisionSensitivityObligation` | `examples/precision_escape_rescue.eml` | true |
| `saturation_deshelf` | `saturation_shelf->corner_concentration` | `ClampInvariantObligation` | `examples/saturation_deshelf_rescue.eml` | true |

This manifest is analysis-only. It aggregates the four v0 proof-carrying
rescue packets; it does not claim semantic rewrites, optimizer release,
hardware observations, or completed formal proofs.
