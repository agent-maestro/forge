# NRC Compliance Guide — Monogate Forge

> The US Nuclear Regulatory Commission (NRC) regulates safety-
> critical software in nuclear power plant instrumentation +
> controls under 10 CFR 50.55a + Regulatory Guide 1.152
> (criteria for digital computer instrumentation). Software is
> also subject to IEC 60880 (nuclear power plants — instrumentation
> + controls — software aspects).
>
> This guide maps forge artifacts to NRC + IEC 60880 evidence.

---

## Quick map: forge artifact → NRC evidence

| Reg requirement | Artifact |
|-----------------|----------|
| **10 CFR 50.55a** Acceptable software | `eml-compile --target c` produces deterministic, single-translation-unit C; no dynamic memory, no concurrency primitives, no UB |
| **RG 1.152 §2.2** Independent verification | `eml-compile --target lean` produces a verification artifact independent of the implementation language |
| **RG 1.152 §3** Validation | `--fpga-sim` confirms HW deployment matches the verified C reference |
| **IEC 60880 §6.4** Software requirements specification | `requires` / `ensures` clauses on every safety-affecting function |
| **IEC 60880 §7.4** Software design | The `.eml` source (declarative; no procedural noise; chain-order types for stability) |
| **IEC 60880 §10** Software verification | `lake build MonogateEML.<fn>` PASS on the generated `.lean` |

## Per-class guidance

NRC's safety classification follows IEEE Std 603 / RG 1.97:

| Class | Description | Forge constraints |
|-------|-------------|-------------------|
| **1E** (safety-related: emergency core cooling, reactor protection, etc.) | All forge constraints + 100% `@verify` coverage + `chain_order <= 1` everywhere |
| **Augmented Quality** (post-accident monitoring) | `@verify` on safety-affecting fns + `chain_order <= 2` |
| **Important to Safety** (control rod motion, etc.) | `@verify` on actuator-driving fns + `chain_order <= 3` |
| **Non-safety** (display, logging) | Forge defaults |

## Worked example: `mppt.eml` (renewable analog)

(MPPT itself isn't an NRC application — it's the renewable-energy
analog of the same safety-control pattern that NRC class-1E
software exhibits. Substitute "reactor neutron flux" for "PV
array voltage" and the structure is identical.)

```eml
@target(fpga, clock_mhz = 100, precision = float32)
@verify(lean, theorem = "mppt_voltage_command_safe")
fn mppt_step(...) -> Real
    requires (V_MIN <= voltage_now <= V_MAX)
    ...
    ensures  (V_MIN <= result <= V_MAX)
{ ... }
```

The `ensures` is the safety-control evidence: no matter what
input the controller receives, the commanded output stays
within the actuator's safe operating envelope.

```bash
$ eml-compile mppt.eml --target all -o ./out
$ # The .lean theorem is the IEC 60880 §10 verification artifact
$ cp out/mppt.lean ../monogate-lean/MonogateEML/MPPT.lean
$ cd ../monogate-lean && lake build MonogateEML.MPPT
```

---

## What forge does NOT (yet) do

- Defense in depth analysis (cyber). Tool-orthogonal.
- Common-cause failure analysis (multi-channel diversity). The
  same `.eml` compiled twice is by definition the same artifact;
  diversity needs intentionally different implementations.
- ALWR / ABWR / SMR-specific platform integration.

---

## Partners

NRC submissions for digital I&C software are rare and high-
stakes. Engage a nuclear-software consultant from the start
(Curtiss-Wright, Paragon, etc.). Cf.
`roadmap/business/certification_partners.md`.
