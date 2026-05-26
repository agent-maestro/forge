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
- `obligation_registry`: per-lane routed/witnessed/proven/CI/public-copy state
- `approval_gate`: reviewer decision for surfacing/deploying generated artifacts

## Required Lanes

| Operator | Transition | Obligation |
| --- | --- | --- |
| `log_domain_lift` | `domain_wall->log_domain_rescue` | `PositiveCoordinateObligation` |
| `guard_clamp` | `overflow_wall->guard_rescue` | `OutputSafetyObligation` |
| `precision_escape` | `phantom_attractor->interior_sample` | `PrecisionSensitivityObligation` |
| `saturation_deshelf` | `saturation_shelf->corner_concentration` | `ClampInvariantObligation` |

Every lane must set `has_transition_witness` to `true`.

## Obligation Registry

The registry classifies each lane with six booleans:

- `routed`: Forge names the MachLib obligation.
- `witnessed`: the trace contains the expected transition witness.
- `proven`: a concrete sample-level MachLib theorem discharges the local
  obligation.
- `ci_guarded`: CI regenerates and checks the artifact.
- `public_copy_safe`: current public copy may describe the lane under the
  conservative claim boundary.
- `blocked`: the lane must not be surfaced as approved.

For v0, `log_domain_lift`, `guard_clamp`, and `saturation_deshelf` have
concrete sample-level MachLib witness theorems. `precision_escape` remains
routed and witnessed through packet bridges, but not concretely proven.

## Approval Gate

The approval artifact records whether the generated bundle may be used by the
existing public/dev surfaces. It requires valid replay, full registry coverage,
conservative claim flags, and at least one concrete MachLib witness. It also
states that electronics physical packets must use the evidence grammar before
they can support hardware claims.

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
forge rescue --suite --strict
```

The replay validator checks lane completeness, expected transitions, obligation
names, witness flags, embedded packet agreement, and conservative boundary
flags. CI also checks the registry and approval artifacts.

See `docs/research_artifact_contract.md` for the ownership and CI contract
connecting Forge, monogate.dev, monogate.org, monogate.net, and MachLib.
