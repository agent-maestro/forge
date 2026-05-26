# Boundary Intervention Benchmark

Schema: `forge.optimizer.boundary_intervention_benchmark.v1`
Pairs: `24`

| dimension | intervention | expected transition | obligation | raw survival | intervened survival | survival delta | bad-event delta | rescued count | entropy delta |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 2 | log_domain_lift | `domain_wall->log_domain_rescue` | positive_coordinate_preservation | 1.0000 | 1.0000 | 0.0000 | 0 | 0 | -0.2257 |
| 2 | guard_clamp | `overflow_wall->guard_rescue` | output_safety | 1.0000 | 1.0000 | 0.0000 | 0 | 0 | -0.0339 |
| 2 | precision_escape | `phantom_attractor->interior_sample` | precision_sensitivity | 0.9961 | 1.0000 | 0.0039 | 0 | 191 | -0.2231 |
| 2 | saturation_deshelf | `saturation_shelf->corner_concentration` | clamp_invariant | 0.9961 | 1.0000 | 0.0039 | 6 | 45 | -0.0605 |
| 4 | log_domain_lift | `domain_wall->log_domain_rescue` | positive_coordinate_preservation | 0.9844 | 1.0000 | 0.0156 | 4 | 4 | -0.3532 |
| 4 | guard_clamp | `overflow_wall->guard_rescue` | output_safety | 1.0000 | 1.0000 | 0.0000 | 0 | 0 | -0.0211 |
| 4 | precision_escape | `phantom_attractor->interior_sample` | precision_sensitivity | 1.0000 | 1.0000 | 0.0000 | 0 | 138 | -0.4425 |
| 4 | saturation_deshelf | `saturation_shelf->corner_concentration` | clamp_invariant | 0.9922 | 1.0000 | 0.0078 | 11 | 63 | -0.0728 |
| 8 | log_domain_lift | `domain_wall->log_domain_rescue` | positive_coordinate_preservation | 0.9883 | 1.0000 | 0.0117 | 3 | 3 | -0.5998 |
| 8 | guard_clamp | `overflow_wall->guard_rescue` | output_safety | 0.9844 | 1.0000 | 0.0156 | 0 | 4 | -0.0414 |
| 8 | precision_escape | `phantom_attractor->interior_sample` | precision_sensitivity | 0.9805 | 1.0000 | 0.0195 | 0 | 89 | -0.5545 |
| 8 | saturation_deshelf | `saturation_shelf->corner_concentration` | clamp_invariant | 0.9805 | 1.0000 | 0.0195 | 22 | 110 | -0.0941 |
| 16 | log_domain_lift | `domain_wall->log_domain_rescue` | positive_coordinate_preservation | 0.1836 | 1.0000 | 0.8164 | 3 | 209 | -0.1656 |
| 16 | guard_clamp | `overflow_wall->guard_rescue` | output_safety | 0.1875 | 1.0000 | 0.8125 | 206 | 208 | -0.1225 |
| 16 | precision_escape | `phantom_attractor->interior_sample` | precision_sensitivity | 0.1758 | 1.0000 | 0.8242 | 0 | 33 | -0.1206 |
| 16 | saturation_deshelf | `saturation_shelf->corner_concentration` | clamp_invariant | 0.1992 | 1.0000 | 0.8008 | 0 | 17 | 0.0000 |
| 32 | log_domain_lift | `domain_wall->log_domain_rescue` | positive_coordinate_preservation | 0.0000 | 1.0000 | 1.0000 | 0 | 256 | 0.0000 |
| 32 | guard_clamp | `overflow_wall->guard_rescue` | output_safety | 0.0000 | 1.0000 | 1.0000 | 256 | 256 | 0.0000 |
| 32 | precision_escape | `phantom_attractor->interior_sample` | precision_sensitivity | 0.0000 | 1.0000 | 1.0000 | 0 | 0 | 0.0000 |
| 32 | saturation_deshelf | `saturation_shelf->corner_concentration` | clamp_invariant | 0.0000 | 1.0000 | 1.0000 | 0 | 0 | 0.0000 |
| 64 | log_domain_lift | `domain_wall->log_domain_rescue` | positive_coordinate_preservation | 0.0000 | 1.0000 | 1.0000 | 0 | 256 | 0.0000 |
| 64 | guard_clamp | `overflow_wall->guard_rescue` | output_safety | 0.0000 | 0.9297 | 0.9297 | 238 | 238 | 0.7285 |
| 64 | precision_escape | `phantom_attractor->interior_sample` | precision_sensitivity | 0.0000 | 1.0000 | 1.0000 | 0 | 0 | 0.0000 |
| 64 | saturation_deshelf | `saturation_shelf->corner_concentration` | clamp_invariant | 0.0000 | 0.9258 | 0.9258 | 0 | 0 | 0.7643 |

This benchmark is simulated and pairwise. It tests whether named rescue
operators change boundary-event dynamics; it does not claim a semantic
rewrite, optimizer release, serial capture, or hardware observation.
