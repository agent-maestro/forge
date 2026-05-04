# `monogate-zk` — Plonky2 ZK backend for the Verification Network

This crate is the real, zero-knowledge prover that backs Phase 1 of
the Monogate Verification Network. It compiles an EML circuit
description (produced by `lang/zkproof/circuit.py`) into a
Plonky2 PLONK + FRI circuit over the Goldilocks field, generates a
proof bound to a module fingerprint, and ships it as JSON for the
transparency log.

## Build

```bash
cd lang/zkproof/plonky2_backend
cargo build --release
```

`cargo` resolves the toolchain via [`rust-toolchain.toml`](rust-toolchain.toml) — Plonky2's
`plonky2_field` crate uses unstable specialization, so a nightly
compiler is required. The build pulls ~200 transitive crates and
takes 5–15 minutes from cold; subsequent rebuilds are seconds.

The Python bridge (`lang/zkproof/plonky2_runner.py`) discovers the
binary in this order:

1. `MONOGATE_ZK_BIN` env var
2. `target/release/monogate-zk` next to this README
3. `monogate-zk` on `$PATH`

If none resolve, every consumer falls back to the transparent stub
in `lang/zkproof/prover.py` — there is no hard dependency on Rust
for code paths that don't actually need ZK.

## CLI surface

```text
monogate-zk capabilities
monogate-zk prove   --circuit <file.json> --inputs '{...}' \
                    --fingerprint sha256:... --out proof.json
monogate-zk verify  --circuit <file.json> --proof proof.json \
                    --fingerprint sha256:...
```

All three commands speak JSON in / JSON out. `verify` exits 0 when
the proof passes, 1 when it fails; the `is_valid` + `reason` envelope
on stdout carries the human-facing detail either way.

## Gate coverage (Phase 1)

| Gate | Backend | Notes |
|------|---------|-------|
| `CONST` | Plonky2 | fixed-point encoded, scale = 2^16 |
| `INPUT` | Plonky2 | registered as a public input |
| `ADD` | Plonky2 | scale-aligned via `mul_const` |
| `SUB` | Plonky2 | scale-aligned via `mul_const` |
| `MUL` | Plonky2 | output scale = a.scale + b.scale |
| `NEG` | Plonky2 | preserves scale |
| `OUTPUT` | Plonky2 | registered as a public input |
| `DIV`, `MOD`, `POW` | **stub fallback** | needs range proof gadget |
| `EXP`, `LN`, `SIN`, `COS`, `TAN`, `SQRT` | **stub fallback** | needs lookup table |
| `ASIN`, `ACOS`, `ATAN`, `SINH`, `COSH`, `TANH` | **stub fallback** | needs lookup table |
| `ABS`, `MIN`, `MAX`, `CLAMP` | **stub fallback** | needs comparison gadget |

The Python `prove()` auto-routes — arithmetic-only circuits go to
Plonky2, anything else falls back to the transparent stub. Pass
`backend="plonky2"` to require the real backend (raises if it can't
handle the circuit) or `backend="stub"` to force the fallback.

## Fixed-point encoding

Floats are encoded into Goldilocks via `floor(x * 2^16)`, with
negatives stored as `p - |x|`. Each wire tracks its accumulated
scale: ADD/SUB align scales by multiplying the lower-scale operand
by `2^(diff)`, MUL adds the operand scales, NEG preserves. The
OUTPUT wire's scale is recorded in the proof JSON for documentation
but the verifier always **recomputes** it from the circuit — so
tampering with `output_scale_bits` cannot mask a bad output claim.

`MAX_OUTPUT_SCALE_BITS = 56` keeps 8 bits of headroom against the
64-bit Goldilocks half-range. A circuit whose MUL chain would
exceed that errors out cleanly; the Python bridge falls back to the
transparent stub.

## What "real ZK" buys you today

- **Cryptographic soundness**: a valid proof is computationally
  binding to the circuit + fingerprint + inputs + output — forging
  one requires breaking SHA-256 + Plonky2's FRI commitment.
- **Tamper detection**: changing the proof's claimed output or any
  public input causes the field-element commitment inside the proof
  to disagree with the verifier's recomputed encoding; rejection is
  immediate.
- **Cross-machine determinism**: the binary is reproducible given
  the same Plonky2 version (pinned in `Cargo.toml`).

What it **doesn't** buy you yet:

- **Input privacy**. Phase 1 still records inputs in the clear in
  the proof JSON for the registry to display. The Plonky2 backend
  uses public inputs for everything; switching to private witnesses
  is a Phase 2 change (single-line Plonky2 API swap, but requires
  the registry to be updated to omit them from the JSON).
- **Transcendental gates**. Lookup tables for sin/exp/log land in
  Phase 1.5; until then those circuits use the transparent stub.

## Test

```bash
cargo test --release
```

Two unit tests:
- `round_trip_encoding` — fixed-point encode/decode preserves
  values within one quantisation step.
- `linear_circuit_proves_and_verifies` — full prove + verify of
  `2*x + 3` over the binary's CLI plumbing.

The Python integration tests in `lang/zkproof/tests/test_plonky2_backend.py`
exercise the bridge end-to-end (auto-routing, tamper detection,
JSON round-trip through the registry pipeline). They skip cleanly
when the binary hasn't been built.
