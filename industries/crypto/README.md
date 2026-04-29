# crypto

> Industry vertical for cryptographic primitives. The headline forge
> property here is **constant-time-by-construction**: chain order 0
> (polynomial / pure field arithmetic) operations are naturally
> constant-time and are the only chain order permitted by the
> `ConstantTime` type.

**Certification target:** FIPS 140-3 (US), Common Criteria EAL4+
**Typical chain orders:** 0 (polynomial — required for side-channel resistance)

## Why crypto belongs in EML-lang

Read [`scope/forge_advantage.md`](scope/forge_advantage.md) — the
strategic case for an EML-lang crypto pipeline vs the
hand-rolled-C-and-Verilog status quo. Short version:

  - The type system catches side-channel timing leaks at compile
    time via the `ConstantTime` constraint (`chain_order == 0`).
  - Lean-attached theorems pin algebraic correctness (e.g.
    `aes_round_correct`, `gf256_inverse_involutive`) before the
    bitstream ships.
  - The same `.eml` source emits constant-time C, side-channel
    resistant Verilog, and a Lean machine-checked proof — no
    hand-translation drift between the spec, the C, and the HDL.

## Subdirectories

| Path | Family | Headline algorithms | Chain order |
|------|--------|---------------------|-------------|
| `symmetric/` | block + stream + hash | AES-256, ChaCha20, SHA-256, SHA-3 | 0 |
| `asymmetric/` | classical PKC | RSA, ECDSA, Ed25519, X25519 | 0 (modular arithmetic only) |
| `post_quantum/` | NIST PQC selections | Kyber, Dilithium, Falcon | 0 (lattice arithmetic) |
| `zero_knowledge/` | ZK proof systems | STARK, Groth16, PLONK | 0 (pairing / poly arithmetic) |
| `certification/` | compliance guides | FIPS 140-3, CC EAL | docs only |
| `scope/` | strategic case | what forge brings vs the status quo | docs only |

## Adding an algorithm

1. Pick the right family directory.
2. Write `<algo>.eml` declaring `type ConstantTime = Real where
   chain_order == 0` somewhere in scope, then constrain every
   public function's signature with `ensures (timing_invariant ==
   true)`.
3. Add a Lean `@verify` clause naming the correctness theorem
   and check that `lake build` passes after `eml-compile <fn>.eml
   --target lean`.
4. If certification-relevant, add the appropriate FIPS / CC
   evidence row in the matching guide under `certification/`.
5. Add a regression row to
   `tools/benchmarks/vertical_baseline.json` so subsequent runs
   can't silently regress chain order or constant-time status.

## Cross-references

  - Patents touching this vertical: see `patents/index.md`
    (constant-time type system + side-channel-resistant FPGA
    allocation are filed under separate claims).
  - Reference implementations (NIST test vectors, RFC 7748 / 8032
    test cases) live in the user's domain-research folder, not
    here.
