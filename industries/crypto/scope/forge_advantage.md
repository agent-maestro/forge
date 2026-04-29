# What Forge brings to crypto that nobody else has

> The strategic case for an EML-lang crypto pipeline. This document
> is the "why" sitting under every `.eml` file in this vertical.
> Engineers ship crypto from `industries/crypto/`; investors and
> partners read this file to understand *why ship it from here*.

---

## Today's crypto hardware (the status quo)

```
Engineer writes crypto algorithm
  → codes in C or Verilog manually
  → hopes timing is constant (side-channel resistance)
  → hopes precision is correct
  → NO formal verification of the math
  → NO structural analysis
  → Takes months, costs millions
```

The hand-rolled pipeline forces every team to reinvent the same
side-channel mitigations, the same NIST test-vector harnesses,
and the same FPGA allocation tactics. Each rewrite is a fresh
chance to introduce a CVE.

---

## With Forge

Write the crypto in EML-lang:

```eml
@verify(lean, theorem = "aes_round_correct")
@target(fpga, clock_mhz = 300, constant_time = true)
fn aes_sbox(input: Byte) -> Byte {
    // GF(2^8) inversion + affine transform
    let inv = gf256_inverse(input)
    affine_transform(inv)
}
```

Compiler output:

```
chain_order: 0          (polynomial — pure field arithmetic)
nodes: 12               (SuperBEST optimal)
FPGA: 0 transcendental  (all LUT-based)
timing: CONSTANT        (verified by type system)
Lean proof: aes_sbox_correct attached
Verilog: aes_sbox.v     (synthesizable, side-channel resistant)
```

Every line of that output is something the status-quo pipeline
must produce by hand or guess at; here it is a build-time
artifact of compiling a single source.

---

## The killer feature: constant-time verification

The biggest crypto bug of the last decade is timing-based
side-channel leakage. If `exp(secret_key)` takes longer for
larger keys, an attacker can measure timing and extract the
key. Constant-time *by construction* — not by audit — is what
the field needs and what no language gives you today.

Forge prevents this with a type-level constraint:

```eml
type ConstantTime = Real where timing_invariant == true
```

The compiler verifies that **every code path** through the
function takes the same number of operations.

  - Chain order 0 (polynomial) operations are naturally
    constant-time. The cost model proves it.
  - Chain order 1+ (transcendental) operations are NOT
    constant-time and are rejected by the type checker for any
    function annotated `ConstantTime`.

The type system catches side-channel vulnerabilities **at
compile time**. Nobody else has this.

---

## What this unlocks

  - **Faster certification.** FIPS 140-3 algorithm-implementation
    review hinges on side-channel evidence. Compiler-emitted
    constant-time proofs replace pages of audit narrative.
  - **No drift between spec, C, and HDL.** The same `.eml`
    source is the input for both software and hardware
    implementations, so post-quantum migrations don't fork into
    two parallel codebases.
  - **PQC-ready.** CRYSTALS-Kyber, Dilithium, and Falcon are
    polynomial / lattice arithmetic — chain order 0. The forge
    SuperBEST optimizer reorganizes the NTT exactly the same way
    it does for AES, just with different field constants.
  - **Reproducible side-channel-resistant hardware.** The FPGA
    backend's resource allocator is told "constant_time = true"
    and emits a pipeline with no shared multipliers between
    branches, no key-dependent control flow, and no transcendental
    units (which can't be made constant-time on most FPGAs).

---

## What stays out of scope (today)

  - Random number generation. RNGs are inherently non-functional
    (they have side effects). Forge depends on the host's RNG
    via an `extern` boundary.
  - Memory safety of the surrounding C bindings. Forge proves the
    crypto math; the calling C code's bounds checks are still on
    the integrator.
  - Protocol-level analysis. TLS 1.3 / Noise / Signal protocols
    are sequences of crypto primitives; forge proves each
    primitive but doesn't prove the protocol composition. Tools
    like ProVerif / Tamarin still apply at that layer.

These boundaries are the same ones that bound any "verified
crypto" effort (HACL*, fiat-crypto, EverCrypt). What's new is
that forge unifies the C, the Verilog, and the Lean inside the
boundaries, instead of leaving the FPGA path entirely
unverified.
