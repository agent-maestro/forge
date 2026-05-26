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
| `restricted_semantic_rewrite` | MachLib proves the rescue preserves a stated semantics for a restricted program class. | Safe to describe only with the named restriction. |
| `semantic_rewrite` | A rescue operator preserves full program meaning under a stated semantics. | Not claimed by v0. |

## Operator Contracts

| Operator | Accepts | Restores | Allowed change | Current tier |
|---|---|---|---|---|
| `log_domain_lift` | `domain_wall` samples with non-positive raw log coordinates | positive internal coordinates through `exp(theta)` | raw coordinate representation may become a lifted internal coordinate | `restricted_semantic_rewrite` |
| `guard_clamp` | `overflow_wall` samples outside a finite evaluation envelope | bounded guarded coordinate/output witness | coordinate may be clamped to the configured guard limit | `concrete_sample_invariant` |
| `precision_escape` | `phantom_attractor` samples where low precision stalls near a basin | higher-precision nonzero escape signal from a low-precision stall | precision and probe coordinate may change to expose a descent direction | `concrete_sample_invariant` |
| `saturation_deshelf` | `saturation_shelf` samples collapsed by clamped output | pre-clamp pressure inside the declared clamp interval | trace may expose pre-clamp pressure instead of only clamped output | `concrete_sample_invariant` |

## Reviewer Decision

`log_domain_lift` now has the first restricted semantic rewrite theorem. For
the small log-domain class represented by the witness record, the rescue is a
representation change from a raw domain-wall sample into a positive internal
coordinate with a `log_domain_rescue` event.

`precision_escape` also has a concrete sample-invariant witness. The witness is
local: low precision reports a stalled gradient, while the higher-precision
replay exposes a nonzero escape signal and moves the sample from
`phantom_attractor` to `interior_sample`.

The v0 approval gate may surface the existing Explorer because all four lanes
have at least concrete sample-invariant coverage, the log-domain lane has a
restricted semantic rewrite theorem, and the page keeps `semantic_rewrite_claim`
false. Any future product copy that treats the restricted theorem as full
rewrite semantics should be blocked by review.

## Non-Claims

- No full semantic rewrite theorem is claimed.
- No optimizer release claim is created.
- No hardware observation is implied.
- No production safety or certified safety status is implied.
- No physical electronics packet is accepted unless it satisfies the evidence
  grammar and carries real capture flags.
