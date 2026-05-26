# Boundary Optimizer Benchmark

Schema: `forge.optimizer.boundary_run_benchmark.v1`
Electronics packet schema: `monogate-electronics.boundary-run.v0`
Runs: `18`

| dimension | mode | dominant event | boundary hits | center hits | domain failures | saturation events | finite survival |
|---:|---|---|---:|---:|---:|---:|---:|
| 2 | raw | interior_sample | 70 | 36 | 0 | 25 | 1.0000 |
| 2 | guarded | interior_sample | 62 | 47 | 0 | 13 | 1.0000 |
| 2 | log-domain candidate | interior_sample | 57 | 46 | 0 | 2 | 1.0000 |
| 4 | raw | interior_sample | 93 | 12 | 3 | 36 | 0.9883 |
| 4 | guarded | interior_sample | 102 | 17 | 0 | 36 | 1.0000 |
| 4 | log-domain candidate | interior_sample | 105 | 12 | 0 | 7 | 1.0000 |
| 8 | raw | corner_concentration | 167 | 3 | 4 | 69 | 0.9844 |
| 8 | guarded | corner_concentration | 162 | 3 | 0 | 52 | 1.0000 |
| 8 | log-domain candidate | corner_concentration | 167 | 4 | 0 | 9 | 1.0000 |
| 16 | raw | overflow_wall | 223 | 0 | 211 | 125 | 0.1758 |
| 16 | guarded | guard_rescue | 224 | 0 | 0 | 96 | 1.0000 |
| 16 | log-domain candidate | log_domain_rescue | 224 | 1 | 0 | 25 | 1.0000 |
| 32 | raw | overflow_wall | 253 | 0 | 256 | 177 | 0.0000 |
| 32 | guarded | guard_rescue | 251 | 0 | 0 | 153 | 1.0000 |
| 32 | log-domain candidate | log_domain_rescue | 252 | 0 | 0 | 55 | 1.0000 |
| 64 | raw | overflow_wall | 256 | 0 | 256 | 237 | 0.0000 |
| 64 | guarded | guard_rescue | 255 | 0 | 20 | 214 | 0.9219 |
| 64 | log-domain candidate | log_domain_rescue | 256 | 0 | 0 | 111 | 1.0000 |

This benchmark is simulated and analysis-only. It backs the Course 006
Optimization Boundary Lab contract; it does not claim a semantic rewrite,
optimizer release, serial capture, or hardware observation.
