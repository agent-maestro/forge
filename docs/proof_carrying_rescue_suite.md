# Proof-Carrying Rescue Suite Manifest

Schema: `forge.optimizer.proof_carrying_rescue_suite.v0`

This manifest is the stable machine-readable contract for the v0 boundary-event
rescue suite. It aggregates the four lane packets into one replayable artifact.

## Required Top-Level Fields

- `schema_version`: must be `forge.optimizer.proof_carrying_rescue_suite.v0`
- `suite`: currently `proof-carrying-rescue-v0`
- `lane_count`: must be `4`
- `complete_v0`: must be `true`
- `lanes`: compact lane summaries
- `packets`: embedded lane packets
- `boundaries`: conservative claim flags

## Required Lanes

| Operator | Transition | Obligation |
| --- | --- | --- |
| `log_domain_lift` | `domain_wall->log_domain_rescue` | `PositiveCoordinateObligation` |
| `guard_clamp` | `overflow_wall->guard_rescue` | `OutputSafetyObligation` |
| `precision_escape` | `phantom_attractor->interior_sample` | `PrecisionSensitivityObligation` |
| `saturation_deshelf` | `saturation_shelf->corner_concentration` | `ClampInvariantObligation` |

Every lane must set `has_transition_witness` to `true`.

## Conservative Flags

These fields must remain `false` at the suite level and embedded packet level:

- `semantic_rewrite_claim`
- `optimizer_release_claim`
- `hardware_observed`
- `completed_formal_proof_claim` when present

The manifest is evidence for replay and obligation routing. It is not itself a
semantic rewrite, optimizer release, hardware capture, or completed formal proof.

## Replay

Use:

```text
python tools/proof_carrying_rescue_replay.py \
  reports/proof_carrying_rescue_suite_v0_2026_05_26.json \
  --strict
```

The replay validator checks lane completeness, expected transitions, obligation
names, witness flags, embedded packet agreement, and conservative boundary
flags.
