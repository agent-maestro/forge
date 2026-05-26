# Boundary Optimizer Benchmark

Schema: `forge.optimizer.boundary_run_benchmark.v1`
Electronics packet schema: `monogate-electronics.boundary-run.v0`
Runs: `18`

| dimension | mode | dominant event | dominant transition | entropy | boundary hits | center hits | domain failures | saturation events | finite survival |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|
| 2 | raw | interior_sample | interior_sample->interior_sample | 2.1835 | 70 | 36 | 0 | 25 | 1.0000 |
| 2 | guarded | interior_sample | interior_sample->interior_sample | 2.0036 | 62 | 47 | 0 | 13 | 1.0000 |
| 2 | log-domain candidate | interior_sample | interior_sample->interior_sample | 1.6159 | 57 | 46 | 0 | 2 | 1.0000 |
| 4 | raw | interior_sample | interior_sample->interior_sample | 2.7091 | 93 | 12 | 3 | 36 | 0.9883 |
| 4 | guarded | interior_sample | interior_sample->interior_sample | 2.7668 | 102 | 17 | 0 | 36 | 1.0000 |
| 4 | log-domain candidate | interior_sample | interior_sample->interior_sample | 2.3837 | 105 | 12 | 0 | 7 | 1.0000 |
| 8 | raw | corner_concentration | corner_concentration->corner_concentration | 3.2803 | 167 | 3 | 4 | 69 | 0.9844 |
| 8 | guarded | corner_concentration | interior_sample->corner_concentration | 3.3281 | 162 | 3 | 0 | 52 | 1.0000 |
| 8 | log-domain candidate | corner_concentration | corner_concentration->corner_concentration | 2.4066 | 167 | 4 | 0 | 9 | 1.0000 |
| 16 | raw | overflow_wall | overflow_wall->overflow_wall | 1.7614 | 223 | 0 | 211 | 125 | 0.1758 |
| 16 | guarded | guard_rescue | guard_rescue->guard_rescue | 1.8542 | 224 | 0 | 0 | 96 | 1.0000 |
| 16 | log-domain candidate | log_domain_rescue | log_domain_rescue->log_domain_rescue | 1.9358 | 224 | 1 | 0 | 25 | 1.0000 |
| 32 | raw | overflow_wall | overflow_wall->overflow_wall | 0.0000 | 253 | 0 | 256 | 177 | 0.0000 |
| 32 | guarded | guard_rescue | guard_rescue->guard_rescue | 0.0000 | 251 | 0 | 0 | 153 | 1.0000 |
| 32 | log-domain candidate | log_domain_rescue | log_domain_rescue->log_domain_rescue | 0.0000 | 252 | 0 | 0 | 55 | 1.0000 |
| 64 | raw | overflow_wall | overflow_wall->overflow_wall | 0.0000 | 256 | 0 | 256 | 237 | 0.0000 |
| 64 | guarded | guard_rescue | guard_rescue->guard_rescue | 0.7929 | 255 | 0 | 20 | 214 | 0.9219 |
| 64 | log-domain candidate | log_domain_rescue | log_domain_rescue->log_domain_rescue | 0.0000 | 256 | 0 | 0 | 111 | 1.0000 |

This benchmark is simulated and analysis-only. It backs the Course 006
Optimization Boundary Lab contract; it does not claim a semantic rewrite,
optimizer release, serial capture, or hardware observation.
