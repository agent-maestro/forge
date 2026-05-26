# Boundary Optimizer Benchmark

Schema: `forge.optimizer.boundary_run_benchmark.v1`
Electronics packet schema: `monogate-electronics.boundary-run.v0`
Runs: `18`

| dimension | mode | boundary hits | center hits | domain failures | saturation events | finite survival |
|---:|---|---:|---:|---:|---:|---:|
| 2 | raw | 70 | 36 | 0 | 25 | 1.0000 |
| 2 | guarded | 62 | 47 | 0 | 13 | 1.0000 |
| 2 | log-domain candidate | 57 | 46 | 0 | 2 | 1.0000 |
| 4 | raw | 93 | 12 | 3 | 36 | 0.9883 |
| 4 | guarded | 102 | 17 | 0 | 36 | 1.0000 |
| 4 | log-domain candidate | 105 | 12 | 0 | 7 | 1.0000 |
| 8 | raw | 167 | 3 | 4 | 69 | 0.9844 |
| 8 | guarded | 162 | 3 | 0 | 52 | 1.0000 |
| 8 | log-domain candidate | 167 | 4 | 0 | 9 | 1.0000 |
| 16 | raw | 223 | 0 | 211 | 125 | 0.1758 |
| 16 | guarded | 224 | 0 | 0 | 96 | 1.0000 |
| 16 | log-domain candidate | 224 | 1 | 0 | 25 | 1.0000 |
| 32 | raw | 253 | 0 | 256 | 177 | 0.0000 |
| 32 | guarded | 251 | 0 | 0 | 153 | 1.0000 |
| 32 | log-domain candidate | 252 | 0 | 0 | 55 | 1.0000 |
| 64 | raw | 256 | 0 | 256 | 237 | 0.0000 |
| 64 | guarded | 255 | 0 | 20 | 214 | 0.9219 |
| 64 | log-domain candidate | 256 | 0 | 0 | 111 | 1.0000 |

This benchmark is simulated and analysis-only. It backs the Course 006
Optimization Boundary Lab contract; it does not claim a semantic rewrite,
optimizer release, serial capture, or hardware observation.
