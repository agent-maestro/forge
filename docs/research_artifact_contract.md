# Monogate Research Artifact Contract

This contract keeps the rescue-suite loop from drifting back into hand-copied
tables.

## Ownership

Forge owns generated machine artifacts:

- `reports/proof_carrying_rescue_suite_v0_2026_05_26.json`
- `reports/proof_carrying_rescue_replay_v0_2026_05_26.json`
- `reports/proof_carrying_rescue_suite_v0_2026_05_26.md`
- `reports/proof_carrying_rescue_explorer_fixture_v0_2026_05_26.json`
- `reports/rescue_obligation_registry_v0_2026_05_26.json`
- `reports/rescue_artifact_approval_v0_2026_05_26.json`

The canonical generation command is:

```text
forge rescue --suite --strict
```

`monogate.dev` displays the generated Explorer fixture. It may add interaction,
layout, and explanatory controls, but it must not become the authority for lane
data.

`monogate.org` explains what the artifacts mean, what is proved, and what is
not claimed.

`monogate.net` indexes public interactive surfaces.

MachLib names and discharges formal obligations. A route from a packet to an
obligation is not the same as a completed semantic rewrite theorem.

The obligation registry is the reviewer surface for each lane. Every entry
must say whether the obligation is routed, witnessed, proven by a concrete
MachLib theorem, semantically tiered, CI guarded, public-copy safe, or blocked.

The approval gate is the deploy/surfacing contract. It must remain
machine-readable and conservative: public surfaces are allowed only when replay
is valid, the registry covers all lanes, conservative flags remain false, and at
least one concrete MachLib witness is present. It must also expose the semantic
summary so reviewers can distinguish complete concrete sample-invariant
coverage from any future packet-bridge-only lane.

Future electronics physical packets are separate from the software rescue
suite, but they must speak the same evidence grammar: source, capture mode,
trace path, validator result, replay result, claim flags, and review status.

## CI Boundary

The rescue-suite CI job must fail when:

- `forge rescue --suite --strict` fails
- committed reports drift from generated reports
- replay validation fails
- obligation registry coverage changes unexpectedly
- semantic-strength fields drift unexpectedly
- approval gate blocks surfacing or deploy
- the Explorer fixture no longer mirrors a valid replay
- conservative claim flags flip to true

## Claim Boundary

The v0 rescue suite claims:

- deterministic generated artifacts
- simulated trace evidence
- replay validation
- named MachLib obligation routing
- one concrete positive-coordinate witness theorem for the log-domain lane
- one concrete output-safety witness theorem for the guard-clamp lane
- one concrete clamp-invariant witness theorem for the saturation-deshelf lane
- one concrete precision-escape witness theorem for the precision lane
- a semantic-strength registry that marks all four v0 lanes as
  `concrete_sample_invariant`
- reviewer approval for the existing generated public/dev surfaces

The v0 rescue suite does not claim:

- production optimizer rewrites
- hardware observation
- completed full semantic correctness for all rescue operators
- authorization for hardware action
- peer-reviewed mathematical finality
