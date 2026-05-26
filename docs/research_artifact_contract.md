# Monogate Research Artifact Contract

This contract keeps the rescue-suite loop from drifting back into hand-copied
tables.

## Ownership

Forge owns generated machine artifacts:

- `reports/proof_carrying_rescue_suite_v0_2026_05_26.json`
- `reports/proof_carrying_rescue_replay_v0_2026_05_26.json`
- `reports/proof_carrying_rescue_suite_v0_2026_05_26.md`
- `reports/proof_carrying_rescue_explorer_fixture_v0_2026_05_26.json`

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

## CI Boundary

The rescue-suite CI job must fail when:

- `forge rescue --suite --strict` fails
- committed reports drift from generated reports
- replay validation fails
- the Explorer fixture no longer mirrors a valid replay
- conservative claim flags flip to true

## Claim Boundary

The v0 rescue suite claims:

- deterministic generated artifacts
- simulated trace evidence
- replay validation
- named MachLib obligation routing
- one concrete positive-coordinate witness theorem for the log-domain lane

The v0 rescue suite does not claim:

- production optimizer rewrites
- hardware observation
- completed full semantic correctness for all rescue operators
- peer-reviewed mathematical finality
