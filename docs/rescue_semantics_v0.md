# Rescue Semantics v0

This note defines the reviewer contract for the proof-carrying rescue suite.
It does not promote the suite to a semantic rewrite theorem. It states what
each v0 rescue operator is allowed to claim, what it restores, and where the
current proof boundary sits.

## Semantic Tiers

| Tier | Meaning | Public copy discipline |
|---|---|---|
| `concrete_sample_invariant` | Forge emits a packet and MachLib has a concrete witness theorem for the local invariant exposed by that packet. | Safe to describe as a concrete witness, with local/sample wording. |
| `packet_bridge_only` | Forge emits a packet and MachLib has a packet bridge, but no concrete sample-invariant theorem yet. | Must stay candidate/inspectability wording. |
| `semantic_rewrite` | A rescue operator preserves full program meaning under a stated semantics. | Not claimed by v0. |

## Operator Contracts

| Operator | Accepts | Restores | Allowed change | Current tier |
|---|---|---|---|---|
| `log_domain_lift` | `domain_wall` samples with non-positive raw log coordinates | positive internal coordinates through `exp(theta)` | raw coordinate representation may become a lifted internal coordinate | `concrete_sample_invariant` |
| `guard_clamp` | `overflow_wall` samples outside a finite evaluation envelope | bounded guarded coordinate/output witness | coordinate may be clamped to the configured guard limit | `concrete_sample_invariant` |
| `precision_escape` | `phantom_attractor` samples where low precision stalls near a basin | inspectable higher-precision escape witness | precision and probe coordinate may change to expose a descent direction | `packet_bridge_only` |
| `saturation_deshelf` | `saturation_shelf` samples collapsed by clamped output | pre-clamp pressure inside the declared clamp interval | trace may expose pre-clamp pressure instead of only clamped output | `concrete_sample_invariant` |

## Reviewer Decision

`precision_escape` is deliberately weaker than the other three lanes. It remains
in the suite because it has replay evidence and a MachLib packet bridge, but it
must not be described as having a concrete sample-invariant proof until a
MachLib theorem discharges that obligation directly.

The v0 approval gate may surface the existing Explorer because the page carries
conservative wording, exposes the weaker precision lane explicitly, and keeps
`semantic_rewrite_claim` false. Any future product copy that treats all four
lanes as equally proven should be blocked by review.

## Non-Claims

- No full semantic rewrite theorem is claimed.
- No optimizer release claim is created.
- No hardware observation is implied.
- No production safety or certified safety status is implied.
- No physical electronics packet is accepted unless it satisfies the evidence
  grammar and carries real capture flags.
