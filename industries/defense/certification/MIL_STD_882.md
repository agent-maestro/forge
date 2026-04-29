# MIL-STD-882 Compliance Guide — Monogate Forge

> MIL-STD-882E is the US Department of Defense system-safety
> standard. It defines four hazard severity categories
> (Catastrophic, Critical, Marginal, Negligible) crossed with
> five probability levels (Frequent through Eliminated),
> producing a Risk Assessment Code (RAC) matrix.
>
> Software-causing-hazard analysis is covered by Joint Software
> Systems Safety Engineering Handbook (JSSSEH) and DOD-STD-2167A.
> Most modern defense programs ALSO require DO-178C compliance
> for airworthiness; forge supports both tracks from one source.

---

## Quick map: forge artifact → MIL-STD-882 evidence

| MIL-STD-882 § | Artifact |
|---------------|----------|
| **Task 202** Preliminary Hazard Analysis (PHA) | `requires` clauses (input domain restrictions) catch precondition-violation hazards |
| **Task 203** Subsystem Hazard Analysis (SSHA) | `@verify(lean, ...)` proves the safety control law |
| **Task 204** System Hazard Analysis (SHA) | `--fpga-sim` confirms HW = SW so integrated-system behaviour matches design |
| **Task 205** Operating + Support Hazard Analysis | `ensures` clauses cap the actuator output to safe operating envelope |
| **Task 301** Safety Verification | `--target lean` output + `lake build` PASS = formal proof artifact |
| **Software Hazard Analysis** | The chain-order constraint + clamp pattern catches the "transcendental drives unbounded actuator" hazard at compile time |

## Per-RAC guidance

Because MIL-STD-882's RAC matrix combines severity × probability,
the forge mapping is severity-driven (probability is a
deployment / FMEA concern). For software-causing-hazard work,
the forge defaults match Catastrophic-level rigor.

| Severity | Recommended `where` constraint | Rationale |
|----------|-------------------------------|-----------|
| **Catastrophic** (loss of life, mission, weapon system) | `chain_order <= 1` + `precision = float64` + `@verify` REQUIRED on every fn in the path | Same bar as DO-178C DAL-A; identical evidence |
| **Critical** (severe injury, major damage) | `chain_order <= 2` + `@verify` on top-level + clamp on actuators | Matches DO-178C DAL-B / ISO 26262 ASIL-D |
| **Marginal** (minor injury, minor damage) | `chain_order <= 3`; `@verify` recommended on safety-affecting fns | DAL-C analog |
| **Negligible** | All forge defaults; no special constraints | DAL-D / QM analog |

## Worked example: `ins.eml` → safety case

Source: `industries/defense/navigation/ins.eml`

```eml
@target(fpga, clock_mhz = 200, precision = float64)
@verify(lean, theorem = "ins_attitude_update_bounded")
fn attitude_step(attitude: Real, rate_gyro: Real) -> Real
    requires (abs(attitude) < ATT_LIMIT)
    requires (abs(rate_gyro) < 100.0)
    ensures  (abs(result) < ATT_LIMIT * 2.0)
{ ... }
```

INS attitude divergence is a well-known Catastrophic hazard
(failed attitude → failed navigation → failed mission /
controlled flight into terrain). The `requires` clauses
constrain the inputs to the platform's physical envelope; the
`ensures` clause proves attitude growth per step is bounded.
`precision = float64` is the Catastrophic-tier default.

```bash
$ eml-compile ins.eml --target all -o ./out
$ # Submit for safety case
$ cp out/ins.lean ../monogate-lean/MonogateEML/INS.lean
$ cd ../monogate-lean && lake build MonogateEML.INS
```

What you submit to the safety review board:

| File | MIL-STD-882 task | Purpose |
|------|------------------|---------|
| `ins.eml` | Task 203 | SSHA design specification |
| `ins.c` | Task 301 | Implementation source |
| `ins.lean` | Task 301 | Formal verification artifact |
| `ins.v` + Verilator MATCH | Task 204 | SHA integration evidence |
| `--profile-only` output | Task 202 | PHA traceability |

---

## Dual-track DO-178C + MIL-STD-882

For airworthy military systems, the same `.eml` file produces
evidence for both standards simultaneously:

```bash
$ # Generate everything once
$ eml-compile ins.eml --target all -o ./out

$ # Submit ins.lean to FAA reviewer (DO-178C DAL-A)
$ # Submit ins.lean to military safety board (MIL-STD-882 Catastrophic)
```

One source. Two regulators. Same evidence package.

---

## What forge does NOT (yet) do

- TEMPEST emanations analysis
- COMSEC / cryptographic-operation analysis
- Anti-tamper evaluation
- DODI 8500.01 cybersecurity
- Mission-data-set encryption

These are toolchain-orthogonal — forge produces source-of-truth
control-law artifacts; the rest of the defense toolchain handles
the security and emanations side.
