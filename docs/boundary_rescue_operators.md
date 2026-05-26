# Boundary Rescue Operators

Status: simulated paired-benchmark contract.

Boundary rescue operators are named interventions over boundary-event dynamics.
They are not semantic rewrites yet. They are benchmarked as pairwise runs:

```text
raw run -> observe boundary dynamics
intervened run -> observe boundary dynamics
compare survival, bad-event count, entropy, and rescue events
```

| Operator | Target transition | Obligation |
| --- | --- | --- |
| `log_domain_lift` | `domain_wall -> log_domain_rescue` | positive-coordinate preservation |
| `guard_clamp` | `overflow_wall -> guard_rescue` | output safety |
| `precision_escape` | `phantom_attractor -> interior_sample` | precision sensitivity |
| `saturation_deshelf` | `saturation_shelf -> corner_concentration` | clamp invariant |

The paired benchmark is emitted by:

```bash
python tools/boundary_optimizer_benchmark.py --strict
```

Outputs:

- `reports/boundary_intervention_benchmark_2026_05_26.json`
- `reports/boundary_intervention_benchmark_2026_05_26.md`

The contract is intentionally conservative: simulated, analysis-only, no
optimizer release claim, and no hardware observation.
