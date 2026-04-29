# Common Criteria EAL Compliance Guide — Monogate Forge

> Common Criteria for Information Technology Security Evaluation
> (CC, ISO/IEC 15408) is the international counterpart to FIPS
> 140-3 — required for crypto products sold into European,
> Japanese, and many other government markets. The Evaluation
> Assurance Level (EAL) ranges from EAL1 (minimal) to EAL7
> (formally verified). Crypto modules typically target **EAL4+**
> (commercial), **EAL5+** (high-assurance hardware), or **EAL6+
> / EAL7** (defense / nuclear).
>
> Forge's machine-checked Lean theorems and constant-time type
> system map directly onto the higher-EAL formal-verification
> requirements that hand-rolled crypto cannot meet without
> heroic effort.

---

## Quick map: forge artifact → CC EAL evidence

| CC class | Family | Forge artifact |
|----------|--------|----------------|
| **ASE** Security Target | ASE_REQ Security Requirements | `requires` / `ensures` clauses on each public `.eml` function |
| **ADV** Development | ADV_FSP Functional Specification | `eml-compile --emit-spec` — function-level summary |
| ADV | ADV_TDS TOE Design | `--profile-only` dump (chain order, cost class, FPGA estimate) |
| ADV | ADV_IMP Implementation Representation | `.eml` source itself + `--target c` / `--target verilog` |
| ADV | ADV_SPM Security Policy Modeling (EAL5+) | `requires`/`ensures` are the security policy; mechanically checked |
| **ATE** Tests | ATE_FUN Functional Testing | `--emit-test-harness` with FIPS / RFC test vectors |
| ATE | ATE_DPT Depth (EAL5+) | Lean theorems prove correctness across all inputs (not just test vectors) |
| **AVA** Vulnerability | AVA_VAN Vulnerability Analysis | `ConstantTime` type checker output catches timing leaks at compile time |
| **ALC** Lifecycle | ALC_TAT Tools and Techniques | This guide + `tools/audit/` reproducibility scripts |

---

## EAL ladder — what forge unlocks per level

### EAL1 (functionally tested) — trivial for forge
  - Any `.eml` source compiles to a testable C binary. Run the
    FIPS / RFC test-vector harness and pass.

### EAL2 (structurally tested) — included
  - `--profile-only` produces a structural summary that maps
    every operation to its chain-order class. Reviewable.

### EAL3 (methodically tested and checked) — included
  - Lean theorem files are reproducible by `lake build` from the
    `.eml` source. The theorem's hypothesis / conclusion match
    the function's `requires` / `ensures`.

### EAL4 (methodically designed, tested and reviewed) — current target
  - Adds a security policy model (ADV_SPM). For forge, this is
    the union of all `requires` / `ensures` clauses across the
    module's public surface, automatically enumerable from
    `eml-compile --emit-spec --json`.

### EAL5 (semiformally designed and tested)
  - Requires *formal* (not just structural) correctness proofs.
    Forge's Lean theorems are formal proofs by construction;
    EAL5's "semiformal" requirement is comfortably exceeded.

### EAL6 (semiformally verified design and tested)
  - Adds covert-channel analysis (AVA_CCA). Forge's chain-order-0
    type system provides a mechanical timing-channel-absence
    proof. Power and EM channels still require physical
    countermeasures (masking, hiding) layered above the
    constant-time core.

### EAL7 (formally verified design and tested)
  - Requires the full development chain to be formally proven
    correct. With forge: the source language has a formal
    semantics (`lang/spec/semantics/*.lean`), the C and Verilog
    backends have cross-target equivalence proven (see
    `equivalence/`), and the SuperBEST optimizer's
    cost-preserving rewrites are themselves Lean-proven. EAL7
    is in reach for an EML-lang core that no hand-rolled
    pipeline can match.

---

## Worked example — Ed25519 signature (RFC 8032)

A typical EAL5 submission for an Ed25519 implementation needs:

| CC requirement | Forge contribution |
|----------------|--------------------|
| ADV_FSP.5 — full functional spec, formal | `industries/crypto/asymmetric/ed25519.eml` declarations are the spec |
| ADV_IMP.1 — implementation rep | The same `.eml` is the impl after `--target c` / `--target verilog` |
| ADV_SPM.1 — security policy model | Union of `requires` / `ensures` clauses on every public fn |
| ATE_DPT.3 — testing depth | `ed25519_sign_correct` Lean theorem covers all valid inputs |
| AVA_VAN.5 — high vulnerability analysis | `ConstantTime` type-check log proves no timing leak |

The integrator wraps the forge output with deployment glue
(key storage, RNG integration, audit logging) and submits the
whole package to the certification lab.

---

## Cross-references with FIPS 140-3

  - FIPS approved algorithms generally satisfy CC EAL4+ for
    CAVP-equivalent evidence; the difference is procedural.
  - `certification/FIPS_140_3.md` covers the US-specific CMVP
    submission steps; this file covers the international CC
    track. Most of the forge artifacts feed both.
  - For dual submission, run the CMVP and CC submissions in
    parallel from the same `.eml` master copy — the equivalence
    proof guarantees the artifacts agree.

---

## What's outside scope

  - **Operational environment evaluation.** CC certifies the
    *product* in a *defined operational environment*. Forge
    contributes the product; the OE is the integrator's
    responsibility.
  - **Composition (CC Part 3 ACO).** Combining a forge crypto
    module with a third-party OS / smart-card OS into one
    certified product requires composition arguments outside
    forge's scope.
  - **National schemes.** Each CC member nation may add local
    requirements (e.g. BSI in Germany, ANSSI in France). These
    add to but do not replace the core CC requirements covered
    above.
