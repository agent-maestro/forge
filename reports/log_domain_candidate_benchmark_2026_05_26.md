# Log-Domain Candidate Benchmark

Schema: `forge.optimizer.log_domain_candidate_benchmark.v1`
Files: `17`
Functions: `82`
Candidates: `9`

| path | function | candidate | reason | exp/log depth | transcendentals | drift |
|---|---|---:|---|---:|---:|---|
| `lang/spec/grammar/examples/bessel_fm.eml` | `fm_voice` | yes | high_drift | 0 | 0 | HIGH |
| `lang/spec/grammar/examples/motor_control.eml` | `damped_response` | yes | high_drift | 1 | 1 | HIGH |
| `lang/spec/grammar/examples/pid_nonlinear.eml` | `nonlinear_gain` | yes | high_drift | 1 | 1 | HIGH |
| `lang/spec/stdlib/math.eml` | `log_b` | yes | multi_transcendental | 1 | 2 | MEDIUM |
| `lang/spec/stdlib/ml.eml` | `softplus` | yes | nested_exp_log | 2 | 2 | MEDIUM |
| `lang/spec/stdlib/ml.eml` | `mish` | yes | high_drift | 2 | 3 | HIGH |
| `lang/spec/stdlib/signal.eml` | `wave_triangle` | yes | high_drift | 0 | 0 | HIGH |
| `lang/spec/stdlib/signal.eml` | `box_muller` | yes | high_drift | 1 | 2 | HIGH |
| `lang/spec/stdlib/signal.eml` | `box_muller_pair` | yes | high_drift | 1 | 2 | HIGH |

This benchmark is analysis-only. It marks functions for log-domain search-coordinate
consideration; it does not claim a semantic rewrite or optimizer release.
